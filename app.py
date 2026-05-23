#!/usr/bin/env python3
import json
import os
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self):
        if self.path == "/api/config":
            return self.send_json({"ollamaBaseUrl": OLLAMA_BASE_URL, "defaultModel": DEFAULT_MODEL})
        if self.path == "/api/models":
            return self.proxy_models()
        if not self.path.startswith("/api/"):
            return super().do_GET()
        self.send_error(404, "Not found")

    def do_POST(self):
        if self.path == "/api/chat":
            return self.proxy_chat()
        self.send_error(404, "Not found")

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def proxy_models(self):
        try:
            with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            models = [
                {"name": model.get("name", ""), "modified_at": model.get("modified_at", "")}
                for model in data.get("models", [])
            ]
            return self.send_json({"models": models, "defaultModel": DEFAULT_MODEL})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return self.send_json({"error": f"Unable to reach Ollama at {OLLAMA_BASE_URL}: {exc}"}, 502)

    def proxy_chat(self):
        try:
            body = self.read_json_body()
        except json.JSONDecodeError:
            return self.send_json({"error": "Invalid JSON body"}, 400)

        payload = {
            "model": body.get("model") or DEFAULT_MODEL,
            "messages": body.get("messages") or [],
            "stream": True,
            "options": body.get("options") or {},
        }

        request = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                for line in response:
                    if line:
                        self.wfile.write(line)
                        self.wfile.flush()
        except (urllib.error.URLError, TimeoutError) as exc:
            error = json.dumps({"error": f"Ollama request failed: {exc}", "done": True}) + "\n"
            self.wfile.write(error.encode("utf-8"))
            self.wfile.flush()


def main():
    port = int(os.environ.get("PORT", "3000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving chat UI at http://127.0.0.1:{port}")
    print(f"Proxying Ollama at {OLLAMA_BASE_URL} with default model {DEFAULT_MODEL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
