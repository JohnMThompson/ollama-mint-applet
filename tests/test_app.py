import time
import threading
import unittest
from email.message import Message
from io import BytesIO
from unittest import mock

import app


def request_handler(headers):
    handler = object.__new__(app.Handler)
    handler.headers = Message()
    for name, value in headers.items():
        handler.headers[name] = value
    handler.server = mock.Mock(server_address=("127.0.0.1", 17865))
    handler.send_json = mock.Mock()
    return handler


class RequestSourceValidationTests(unittest.TestCase):
    def test_accepts_local_host_and_same_origin(self):
        handler = request_handler(
            {"Host": "127.0.0.1:17865", "Origin": "http://localhost:17865"}
        )

        self.assertTrue(handler.validate_request_source())
        handler.send_json.assert_not_called()

    def test_rejects_dns_rebinding_host(self):
        handler = request_handler({"Host": "attacker.example"})

        self.assertFalse(handler.validate_request_source())
        handler.send_json.assert_called_once_with({"error": "Invalid Host header"}, 403)

    def test_rejects_cross_origin_browser_request(self):
        handler = request_handler(
            {"Host": "localhost:17865", "Origin": "https://attacker.example"}
        )

        self.assertFalse(handler.validate_request_source())
        handler.send_json.assert_called_once_with(
            {"error": "Cross-origin request denied"}, 403
        )

    def test_post_rejects_simple_content_type(self):
        handler = request_handler(
            {"Host": "localhost:17865", "Content-Type": "text/plain"}
        )
        handler.path = "/api/chat"

        handler.do_POST()

        handler.send_json.assert_called_once_with(
            {"error": "Content-Type must be application/json"}, 415
        )


class RequestResourceLimitTests(unittest.TestCase):
    def body_handler(self, body, declared_length=None, path="/api/models/load"):
        handler = request_handler(
            {
                "Host": "localhost:17865",
                "Content-Type": "application/json",
                "Content-Length": str(
                    len(body) if declared_length is None else declared_length
                ),
            }
        )
        handler.path = path
        handler.rfile = BytesIO(body)
        return handler

    def test_rejects_oversized_body_before_reading(self):
        limit = app.MAX_REQUEST_BODY_BYTES["/api/models/load"]
        handler = self.body_handler(b"", declared_length=limit + 1)

        with self.assertRaisesRegex(app.RequestBodyError, "exceeds") as raised:
            handler.read_json_body()

        self.assertEqual(raised.exception.status, 413)

    def test_rejects_incomplete_body(self):
        handler = self.body_handler(b"{}", declared_length=20)

        with self.assertRaisesRegex(app.RequestBodyError, "Incomplete") as raised:
            handler.read_json_body()

        self.assertEqual(raised.exception.status, 400)

    def test_requires_content_length(self):
        handler = self.body_handler(b"{}")
        del handler.headers["Content-Length"]

        with self.assertRaises(app.RequestBodyError) as raised:
            handler.read_json_body()

        self.assertEqual(raised.exception.status, 411)

    def test_reports_body_read_timeout(self):
        handler = self.body_handler(b"{}", declared_length=2)
        handler.rfile = mock.Mock()
        handler.rfile.read.side_effect = app.socket.timeout()

        with self.assertRaisesRegex(app.RequestBodyError, "Timed out") as raised:
            handler.read_json_body()

        self.assertEqual(raised.exception.status, 408)

    def test_server_rejects_work_beyond_concurrency_limit(self):
        server = object.__new__(app.BoundedThreadingHTTPServer)
        server._request_slots = threading.BoundedSemaphore(0)
        request = mock.Mock()
        server.shutdown_request = mock.Mock()

        server.process_request(request, ("127.0.0.1", 1234))

        request.sendall.assert_called_once()
        self.assertIn(b"503 Service Unavailable", request.sendall.call_args.args[0])
        server.shutdown_request.assert_called_once_with(request)


class ChatHandoffTests(unittest.TestCase):
    def setUp(self):
        with app.HANDOFFS_LOCK:
            app.HANDOFFS.clear()

    def test_round_trip_filters_invalid_and_empty_messages(self):
        handoff_id = app.create_handoff(
            {
                "model": "mistral:latest",
                "messages": [
                    {"role": "user", "content": "How does this work?"},
                    {"role": "assistant", "content": "Like this."},
                    {"role": "system", "content": "ignored"},
                    {"role": "assistant", "content": "   "},
                ],
            }
        )

        self.assertEqual(
            app.get_handoff(handoff_id),
            {
                "model": "mistral:latest",
                "messages": [
                    {"role": "user", "content": "How does this work?"},
                    {"role": "assistant", "content": "Like this."},
                ],
            },
        )

    def test_rejects_empty_transcript(self):
        with self.assertRaisesRegex(ValueError, "no messages"):
            app.create_handoff({"messages": []})

    def test_rejects_oversized_transcript(self):
        with self.assertRaisesRegex(ValueError, "too large"):
            app.create_handoff(
                {
                    "messages": [
                        {"role": "user", "content": "x" * 500_001},
                    ]
                }
            )

    def test_expired_handoff_is_removed(self):
        with mock.patch.object(app.time, "time", return_value=time.time()):
            handoff_id = app.create_handoff(
                {"messages": [{"role": "user", "content": "Temporary"}]}
            )

        with mock.patch.object(
            app.time,
            "time",
            return_value=time.time() + app.HANDOFF_TTL_SECONDS + 1,
        ):
            self.assertIsNone(app.get_handoff(handoff_id))

        self.assertNotIn(handoff_id, app.HANDOFFS)

    def test_returned_handoff_does_not_mutate_stored_copy(self):
        handoff_id = app.create_handoff(
            {"messages": [{"role": "user", "content": "Original"}]}
        )

        first = app.get_handoff(handoff_id)
        first["messages"][0]["content"] = "Changed"

        self.assertEqual(
            app.get_handoff(handoff_id)["messages"][0]["content"],
            "Original",
        )

    def test_evicts_oldest_handoff_at_count_limit(self):
        with mock.patch.object(app, "MAX_HANDOFFS", 2), mock.patch.object(
            app.time, "time", side_effect=[100, 101, 102]
        ):
            first = app.create_handoff(
                {"messages": [{"role": "user", "content": "first"}]}
            )
            second = app.create_handoff(
                {"messages": [{"role": "user", "content": "second"}]}
            )
            third = app.create_handoff(
                {"messages": [{"role": "user", "content": "third"}]}
            )

        self.assertNotIn(first, app.HANDOFFS)
        self.assertIn(second, app.HANDOFFS)
        self.assertIn(third, app.HANDOFFS)

    def test_evicts_oldest_handoff_at_aggregate_byte_limit(self):
        with mock.patch.object(app, "MAX_HANDOFF_BYTES", 9), mock.patch.object(
            app.time, "time", side_effect=[100, 101]
        ):
            first = app.create_handoff(
                {"messages": [{"role": "user", "content": "12345"}]}
            )
            second = app.create_handoff(
                {"messages": [{"role": "user", "content": "67890"}]}
            )

        self.assertNotIn(first, app.HANDOFFS)
        self.assertIn(second, app.HANDOFFS)

    def test_server_service_action_removes_idle_expired_handoffs(self):
        with mock.patch.object(app.time, "time", return_value=100):
            handoff_id = app.create_handoff(
                {"messages": [{"role": "user", "content": "temporary"}]}
            )
        server = object.__new__(app.BoundedThreadingHTTPServer)

        with mock.patch.object(
            app.time,
            "time",
            return_value=100 + app.HANDOFF_TTL_SECONDS + 1,
        ):
            server.service_actions()

        self.assertNotIn(handoff_id, app.HANDOFFS)


class StaticAssetHeaderTests(unittest.TestCase):
    def test_static_assets_disable_browser_cache(self):
        handler = object.__new__(app.Handler)
        handler.path = "/app.js?v=2"
        headers = []
        handler.send_header = lambda name, value: headers.append((name, value))

        with mock.patch.object(
            app.SimpleHTTPRequestHandler,
            "end_headers",
        ):
            handler.end_headers()

        self.assertIn(("Cache-Control", "no-store"), headers)

    def test_api_responses_disable_browser_cache(self):
        handler = object.__new__(app.Handler)
        handler.path = "/api/handoffs/example"
        headers = []
        handler.send_header = lambda name, value: headers.append((name, value))

        with mock.patch.object(
            app.SimpleHTTPRequestHandler,
            "end_headers",
        ):
            handler.end_headers()

        self.assertIn(("Cache-Control", "no-store"), headers)


class ModelStatusTests(unittest.TestCase):
    def test_default_keep_alive_is_an_integer(self):
        self.assertEqual(app.OLLAMA_LOAD_KEEP_ALIVE, -1)

    def test_model_status_marks_running_models_and_selects_first(self):
        responses = [
            {
                "models": [
                    {"name": "mistral:latest", "modified_at": "today"},
                    {"name": "llama3.2:latest", "modified_at": "yesterday"},
                ]
            },
            {
                "models": [
                    {"name": "llama3.2:latest"},
                    {"name": "mistral:latest"},
                ]
            },
        ]

        with mock.patch.object(app, "ollama_json", side_effect=responses):
            status = app.get_model_status()

        self.assertEqual(status["activeModel"], "llama3.2:latest")
        self.assertEqual(
            [model["running"] for model in status["models"]],
            [True, True],
        )

    def test_model_status_has_no_active_model_when_nothing_is_running(self):
        with mock.patch.object(
            app,
            "ollama_json",
            side_effect=[{"models": [{"name": "mistral:latest"}]}, {"models": []}],
        ):
            status = app.get_model_status()

        self.assertIsNone(status["activeModel"])
        self.assertFalse(status["models"][0]["running"])

    def test_load_model_requires_a_downloaded_model(self):
        with mock.patch.object(
            app,
            "get_model_status",
            return_value={
                "models": [{"name": "mistral:latest"}],
                "runningModels": [],
            },
        ), mock.patch.object(app, "ollama_json") as ollama_json:
            with self.assertRaisesRegex(ValueError, "not downloaded"):
                app.load_ollama_model("unknown:latest")

        ollama_json.assert_not_called()

    def test_load_model_uses_configured_keep_alive(self):
        before = {
            "models": [{"name": "mistral:latest"}],
            "runningModels": [],
        }
        after = {
            "models": [{"name": "mistral:latest", "running": True}],
            "runningModels": ["mistral:latest"],
            "activeModel": "mistral:latest",
        }
        with mock.patch.object(
            app,
            "get_model_status",
            side_effect=[before, after],
        ), mock.patch.object(app, "ollama_json") as ollama_json:
            status = app.load_ollama_model("mistral:latest")

        ollama_json.assert_called_once_with(
            "/api/generate",
            {
                "model": "mistral:latest",
                "keep_alive": app.OLLAMA_LOAD_KEEP_ALIVE,
                "stream": False,
            },
            timeout=300,
        )
        self.assertEqual(status, after)

    def test_ollama_http_error_includes_response_message(self):
        error = app.urllib.error.HTTPError(
            "http://ollama/api/generate",
            400,
            "Bad Request",
            {},
            mock.Mock(read=lambda: b'{"error":"invalid duration"}'),
        )
        with mock.patch.object(app.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(app.OllamaError, "invalid duration"):
                app.ollama_json("/api/generate", {"model": "mistral"})


if __name__ == "__main__":
    unittest.main()
