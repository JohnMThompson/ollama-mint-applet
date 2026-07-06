import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import app


class MockOllamaHandler(BaseHTTPRequestHandler):
    chat_requests = []

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            return self.send_json(
                {"models": [{"name": "mistral", "modified_at": "today"}]}
            )
        if self.path == "/api/ps":
            return self.send_json({"models": [{"name": "mistral"}]})
        return self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/generate":
            return self.send_json({"done": True})
        if self.path == "/api/chat":
            self.chat_requests.append(payload)
            body = (
                b'{"message":{"content":"first "}}\n'
                b'{"message":{"content":"second"},"done":true}'
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return self.send_json({"error": "not found"}, 404)

    def log_message(self, _format, *_args):
        pass


class QuietApplicationHandler(app.Handler):
    def log_message(self, _format, *_args):
        pass


class RunningServers:
    def __init__(self):
        self.ollama = ThreadingHTTPServer(("127.0.0.1", 0), MockOllamaHandler)
        self.application = app.BoundedThreadingHTTPServer(
            ("127.0.0.1", 0), QuietApplicationHandler
        )
        self.threads = [
            threading.Thread(target=self.ollama.serve_forever, daemon=True),
            threading.Thread(target=self.application.serve_forever, daemon=True),
        ]
        self.original_ollama_url = app.OLLAMA_BASE_URL

    def __enter__(self):
        MockOllamaHandler.chat_requests.clear()
        app.OLLAMA_BASE_URL = f"http://127.0.0.1:{self.ollama.server_port}"
        for thread in self.threads:
            thread.start()
        return self

    def __exit__(self, *_args):
        self.application.shutdown()
        self.ollama.shutdown()
        for thread in self.threads:
            thread.join()
        self.application.server_close()
        self.ollama.server_close()
        app.OLLAMA_BASE_URL = self.original_ollama_url
        with app.HANDOFFS_LOCK:
            app.HANDOFFS.clear()

    def request(self, method, path, payload=None, headers=None, body=None):
        headers = dict(headers or {})
        if payload is not None:
            body = json.dumps(payload).encode()
            headers.setdefault("Content-Type", "application/json")
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.application.server_port, timeout=5
        )
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
        result = response.status, dict(response.getheaders()), response_body
        connection.close()
        return result


def decode_json(body):
    return json.loads(body.decode())


def test_running_server_proxies_models_and_model_loading():
    with RunningServers() as servers:
        status, _, body = servers.request("GET", "/api/config")
        assert status == 200
        assert decode_json(body)["application"] == "local-llm-chat"

        status, _, body = servers.request("GET", "/api/models")
        assert status == 200
        assert decode_json(body)["activeModel"] == "mistral"

        status, _, body = servers.request(
            "POST", "/api/models/load", {"model": "mistral"}
        )
        assert status == 200
        assert decode_json(body)["activeModel"] == "mistral"


def test_running_server_streams_final_unterminated_ollama_record():
    with RunningServers() as servers:
        status, headers, body = servers.request(
            "POST",
            "/api/chat",
            {
                "model": "mistral",
                "messages": [{"role": "user", "content": "Hello"}],
                "options": {"temperature": 0.4},
            },
        )

        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        records = [json.loads(line) for line in body.splitlines()]
        assert [record["message"]["content"] for record in records] == [
            "first ",
            "second",
        ]
        assert MockOllamaHandler.chat_requests[-1]["options"] == {
            "temperature": 0.4
        }


def test_running_server_handoffs_are_single_use():
    with RunningServers() as servers:
        status, _, body = servers.request(
            "POST",
            "/api/handoffs",
            {
                "model": "mistral",
                "messages": [{"role": "user", "content": "Transfer me"}],
            },
        )
        assert status == 201
        handoff_id = decode_json(body)["id"]

        first_status, _, first_body = servers.request(
            "GET", f"/api/handoffs/{handoff_id}"
        )
        second_status, _, _ = servers.request(
            "GET", f"/api/handoffs/{handoff_id}"
        )

        assert first_status == 200
        assert decode_json(first_body)["messages"][0]["content"] == "Transfer me"
        assert second_status == 404


def test_running_server_returns_structured_errors_without_forwarding():
    invalid_requests = [
        (b"{invalid", "application/json"),
        (b"[]", "application/json"),
        (
            json.dumps(
                {
                    "messages": [{"role": "user", "content": "Hello"}],
                    "options": {"temperature": "hot"},
                }
            ).encode(),
            "application/json",
        ),
        (b"{}", "text/plain"),
        (b"\xff", "application/json"),
    ]
    with RunningServers() as servers:
        for body, content_type in invalid_requests:
            status, _, response_body = servers.request(
                "POST",
                "/api/chat",
                headers={"Content-Type": content_type},
                body=body,
            )
            assert status in {400, 415}
            assert isinstance(decode_json(response_body)["error"], str)
        assert MockOllamaHandler.chat_requests == []


def test_running_server_rejects_invalid_host_origin_and_oversized_body():
    with RunningServers() as servers:
        connection = http.client.HTTPConnection(
            "127.0.0.1", servers.application.server_port, timeout=5
        )
        connection.putrequest("GET", "/api/config", skip_host=True)
        connection.putheader("Host", "attacker.example")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 403
        response.read()
        connection.close()

        status, _, _ = servers.request(
            "GET",
            "/api/config",
            headers={"Origin": "https://attacker.example"},
        )
        assert status == 403

        connection = http.client.HTTPConnection(
            "127.0.0.1", servers.application.server_port, timeout=5
        )
        connection.putrequest("POST", "/api/chat")
        connection.putheader("Content-Type", "application/json")
        connection.putheader(
            "Content-Length", str(app.MAX_REQUEST_BODY_BYTES["/api/chat"] + 1)
        )
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 413
        assert "exceeds" in decode_json(response.read())["error"]
        connection.close()

        connection = http.client.HTTPConnection(
            "127.0.0.1", servers.application.server_port, timeout=5
        )
        connection.putrequest("POST", "/api/chat")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", "invalid")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 400
        assert "Content-Length" in decode_json(response.read())["error"]
        connection.close()


def test_running_server_reports_unavailable_ollama():
    with RunningServers() as servers:
        app.OLLAMA_BASE_URL = "http://127.0.0.1:1"
        status, _, body = servers.request("GET", "/api/models")

        assert status == 502
        assert "Unable to reach Ollama" in decode_json(body)["error"]
