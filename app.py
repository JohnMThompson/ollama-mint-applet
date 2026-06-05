#!/usr/bin/env python3
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")
HANDOFF_TTL_SECONDS = 10 * 60
HANDOFFS = {}
HANDOFFS_LOCK = threading.Lock()


def create_handoff(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid chat handoff")

    messages = []
    total_length = 0
    for message in payload.get("messages") or []:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        total_length += len(content)
        if total_length > 500_000 or len(messages) >= 100:
            raise ValueError("Chat is too large to transfer")
        messages.append({"role": message["role"], "content": content})

    if not messages:
        raise ValueError("Chat has no messages to transfer")

    model = payload.get("model") or DEFAULT_MODEL
    if not isinstance(model, str) or len(model) > 200:
        raise ValueError("Invalid model")

    handoff_id = uuid.uuid4().hex
    now = time.time()
    with HANDOFFS_LOCK:
        expired = [key for key, value in HANDOFFS.items() if now - value["createdAt"] > HANDOFF_TTL_SECONDS]
        for key in expired:
            del HANDOFFS[key]
        HANDOFFS[handoff_id] = {
            "createdAt": now,
            "model": model,
            "messages": messages,
        }
    return handoff_id


def get_handoff(handoff_id):
    now = time.time()
    with HANDOFFS_LOCK:
        handoff = HANDOFFS.get(handoff_id)
        if not handoff or now - handoff["createdAt"] > HANDOFF_TTL_SECONDS:
            HANDOFFS.pop(handoff_id, None)
            return None
        return {
            "model": handoff["model"],
            "messages": [message.copy() for message in handoff["messages"]],
        }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        if not urlsplit(self.path).path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/config":
            return self.send_json({"ollamaBaseUrl": OLLAMA_BASE_URL, "defaultModel": DEFAULT_MODEL})
        if path == "/api/models":
            return self.proxy_models()
        if path.startswith("/api/handoffs/"):
            return self.get_chat_handoff(path.rsplit("/", 1)[-1])
        if not path.startswith("/api/"):
            return super().do_GET()
        self.send_error(404, "Not found")

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/chat":
            return self.proxy_chat()
        if path == "/api/handoffs":
            return self.create_chat_handoff()
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

    def create_chat_handoff(self):
        try:
            handoff_id = create_handoff(self.read_json_body())
        except json.JSONDecodeError:
            return self.send_json({"error": "Invalid JSON body"}, 400)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)
        return self.send_json({"id": handoff_id, "path": f"/?handoff={handoff_id}"}, 201)

    def get_chat_handoff(self, handoff_id):
        if not handoff_id or len(handoff_id) > 64:
            return self.send_json({"error": "Invalid chat handoff"}, 400)
        handoff = get_handoff(handoff_id)
        if not handoff:
            return self.send_json({"error": "Chat handoff not found or expired"}, 404)
        return self.send_json(handoff)

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
