import json
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

    def test_rejects_invalid_content_length(self):
        handler = self.body_handler(b"{}")
        handler.headers.replace_header("Content-Length", "invalid")

        with self.assertRaisesRegex(app.RequestBodyError, "Content-Length") as raised:
            handler.read_json_body()

        self.assertEqual(raised.exception.status, 400)

    def test_rejects_invalid_utf8(self):
        handler = self.body_handler(b"\xff")

        with self.assertRaisesRegex(app.RequestBodyError, "Invalid JSON") as raised:
            handler.read_json_body()

        self.assertEqual(raised.exception.status, 400)

    def test_rejects_non_object_json(self):
        for body in (b"[]", b'"text"', b"null"):
            with self.subTest(body=body):
                handler = self.body_handler(body)
                with self.assertRaisesRegex(app.RequestBodyError, "must be an object"):
                    handler.read_json_body()

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


class RequestSchemaValidationTests(unittest.TestCase):
    def test_chat_payload_normalizes_forwarded_fields(self):
        self.assertEqual(
            app.validate_chat_payload(
                {
                    "model": " mistral:latest ",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "options": {"temperature": 0.4},
                    "untrusted": "discarded",
                }
            ),
            {
                "model": "mistral:latest",
                "messages": [{"role": "user", "content": "Hello"}],
                "options": {"temperature": 0.4},
                "stream": True,
            },
        )

    def test_chat_payload_rejects_incorrect_field_types(self):
        valid = {"messages": [{"role": "user", "content": "Hello"}]}
        invalid_payloads = (
            {**valid, "model": 42},
            {**valid, "options": []},
            {**valid, "options": {"temperature": "hot"}},
            {**valid, "options": {"temperature": True}},
            {**valid, "options": {"temperature": -0.1}},
            {**valid, "options": {"temperature": 2.1}},
            {**valid, "options": {"num_ctx": 4096}},
            {**valid, "options": {"unknown": {"nested": True}}},
            {"messages": "not an array"},
            {"messages": [{"role": "user", "content": 42}]},
            {"messages": [{"role": "invalid", "content": "Hello"}]},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                app.validate_chat_payload(payload)

    def test_invalid_nested_options_return_400_without_reaching_ollama(self):
        body = json.dumps(
            {
                "messages": [{"role": "user", "content": "Hello"}],
                "options": {"temperature": "hot", "unknown": {"nested": True}},
            }
        ).encode()
        handler = request_handler(
            {
                "Host": "localhost:17865",
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            }
        )
        handler.path = "/api/chat"
        handler.rfile = BytesIO(body)

        with mock.patch.object(app.urllib.request, "urlopen") as urlopen:
            handler.proxy_chat()

        handler.send_json.assert_called_once()
        self.assertEqual(handler.send_json.call_args.args[1], 400)
        urlopen.assert_not_called()


class ChatHandoffTests(unittest.TestCase):
    def setUp(self):
        with app.HANDOFFS_LOCK:
            app.HANDOFFS.clear()

    def test_round_trip_preserves_valid_messages(self):
        handoff_id = app.create_handoff(
            {
                "model": "mistral:latest",
                "messages": [
                    {"role": "user", "content": "How does this work?"},
                    {"role": "assistant", "content": "Like this."},
                ],
            }
        )

        self.assertEqual(
            app.consume_handoff(handoff_id),
            {
                "model": "mistral:latest",
                "messages": [
                    {"role": "user", "content": "How does this work?"},
                    {"role": "assistant", "content": "Like this."},
                ],
            },
        )

    def test_rejects_invalid_handoff_messages(self):
        for message in (
            {"role": "system", "content": "not transferable"},
            {"role": "assistant", "content": "   "},
            "not an object",
        ):
            with self.subTest(message=message), self.assertRaises(ValueError):
                app.create_handoff({"messages": [message]})

    def test_rejects_empty_transcript(self):
        with self.assertRaisesRegex(ValueError, "message"):
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
            self.assertIsNone(app.consume_handoff(handoff_id))

        self.assertNotIn(handoff_id, app.HANDOFFS)

    def test_handoff_can_only_be_consumed_once(self):
        handoff_id = app.create_handoff(
            {"messages": [{"role": "user", "content": "Original"}]}
        )

        first = app.consume_handoff(handoff_id)

        self.assertEqual(first["messages"][0]["content"], "Original")
        self.assertIsNone(app.consume_handoff(handoff_id))

    def test_concurrent_consumers_only_deliver_handoff_once(self):
        handoff_id = app.create_handoff(
            {"messages": [{"role": "user", "content": "One reader"}]}
        )
        barrier = threading.Barrier(3)
        results = []

        def consume():
            barrier.wait()
            results.append(app.consume_handoff(handoff_id))

        threads = [threading.Thread(target=consume) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(sum(result is not None for result in results), 1)

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
    def response_headers(self, path):
        handler = object.__new__(app.Handler)
        handler.path = path
        headers = []
        handler.send_header = lambda name, value: headers.append((name, value))
        with mock.patch.object(app.SimpleHTTPRequestHandler, "end_headers"):
            handler.end_headers()
        return dict(headers)

    def test_static_assets_disable_browser_cache(self):
        self.assertEqual(
            self.response_headers("/app.js?v=2")["Cache-Control"],
            "no-store",
        )

    def test_api_responses_disable_browser_cache(self):
        self.assertEqual(
            self.response_headers("/api/handoffs/example")["Cache-Control"],
            "no-store",
        )

    def test_browser_security_headers_are_restrictive(self):
        headers = self.response_headers("/")

        self.assertEqual(headers["Content-Security-Policy"], app.CONTENT_SECURITY_POLICY)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertEqual(headers["Cross-Origin-Resource-Policy"], "same-origin")


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
