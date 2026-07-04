import time
import unittest
from unittest import mock

import app


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

    def test_api_responses_do_not_get_static_cache_header(self):
        handler = object.__new__(app.Handler)
        handler.path = "/api/handoffs/example"
        headers = []
        handler.send_header = lambda name, value: headers.append((name, value))

        with mock.patch.object(
            app.SimpleHTTPRequestHandler,
            "end_headers",
        ):
            handler.end_headers()

        self.assertNotIn(("Cache-Control", "no-store"), headers)


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
