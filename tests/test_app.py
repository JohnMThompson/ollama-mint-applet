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


if __name__ == "__main__":
    unittest.main()
