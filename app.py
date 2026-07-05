#!/usr/bin/env python3
import json
import os
import socket
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
OLLAMA_LOAD_KEEP_ALIVE = os.environ.get("OLLAMA_LOAD_KEEP_ALIVE", "-1")
try:
    OLLAMA_LOAD_KEEP_ALIVE = int(OLLAMA_LOAD_KEEP_ALIVE)
except ValueError:
    pass
HANDOFF_TTL_SECONDS = 10 * 60
MAX_HANDOFFS = 100
MAX_HANDOFF_BYTES = 5_000_000
HANDOFFS = {}
HANDOFFS_LOCK = threading.Lock()
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}
REQUEST_TIMEOUT_SECONDS = 30
MAX_CONCURRENT_REQUESTS = 16
MAX_REQUEST_BODY_BYTES = {
    "/api/chat": 2_000_000,
    "/api/handoffs": 600_000,
    "/api/models/load": 4_000,
}


class OllamaError(Exception):
    pass


class RequestBodyError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def ollama_json(path, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            message = body.get("error") or str(exc)
        except (json.JSONDecodeError, UnicodeDecodeError):
            message = str(exc)
        raise OllamaError(message) from exc


def get_model_status():
    tags = ollama_json("/api/tags", timeout=10)
    running = ollama_json("/api/ps", timeout=10)
    running_names = [
        model.get("name", "")
        for model in running.get("models", [])
        if model.get("name")
    ]
    models = [
        {
            "name": model.get("name", ""),
            "modified_at": model.get("modified_at", ""),
            "running": model.get("name", "") in running_names,
        }
        for model in tags.get("models", [])
        if model.get("name")
    ]
    return {
        "models": models,
        "runningModels": running_names,
        "activeModel": running_names[0] if running_names else None,
        "defaultModel": DEFAULT_MODEL,
    }


def load_ollama_model(model_name):
    status = get_model_status()
    downloaded_names = [model["name"] for model in status["models"]]
    if model_name not in downloaded_names:
        raise ValueError("Model is not downloaded")
    ollama_json(
        "/api/generate",
        {
            "model": model_name,
            "keep_alive": OLLAMA_LOAD_KEEP_ALIVE,
            "stream": False,
        },
        timeout=300,
    )
    return get_model_status()


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
        total_length += len(content.encode("utf-8"))
        if total_length > 500_000 or len(messages) >= 100:
            raise ValueError("Chat is too large to transfer")
        messages.append({"role": message["role"], "content": content})

    if not messages:
        raise ValueError("Chat has no messages to transfer")
    if total_length > MAX_HANDOFF_BYTES:
        raise ValueError("Chat is too large to transfer")

    model = payload.get("model") or DEFAULT_MODEL
    if not isinstance(model, str) or len(model) > 200:
        raise ValueError("Invalid model")

    handoff_id = uuid.uuid4().hex
    now = time.time()
    with HANDOFFS_LOCK:
        cleanup_handoffs_locked(now)
        while HANDOFFS and (
            len(HANDOFFS) >= MAX_HANDOFFS
            or sum(item["sizeBytes"] for item in HANDOFFS.values()) + total_length
            > MAX_HANDOFF_BYTES
        ):
            oldest = min(
                HANDOFFS,
                key=lambda key: (HANDOFFS[key]["createdAt"], key),
            )
            del HANDOFFS[oldest]
        HANDOFFS[handoff_id] = {
            "createdAt": now,
            "model": model,
            "messages": messages,
            "sizeBytes": total_length,
        }
    return handoff_id


def cleanup_handoffs_locked(now):
    expired = [
        key
        for key, value in HANDOFFS.items()
        if now - value["createdAt"] > HANDOFF_TTL_SECONDS
    ]
    for key in expired:
        del HANDOFFS[key]
    return len(expired)


def cleanup_handoffs(now=None):
    with HANDOFFS_LOCK:
        return cleanup_handoffs_locked(time.time() if now is None else now)


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
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if not self.validate_request_source():
            return
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
        if not self.validate_request_source():
            return
        path = urlsplit(self.path).path
        if path.startswith("/api/") and self.headers.get_content_type() != "application/json":
            return self.send_json({"error": "Content-Type must be application/json"}, 415)
        if path == "/api/chat":
            return self.proxy_chat()
        if path == "/api/models/load":
            return self.load_model()
        if path == "/api/handoffs":
            return self.create_chat_handoff()
        self.send_error(404, "Not found")

    def validate_request_source(self):
        host_header = self.headers.get("Host", "")
        try:
            parsed_host = urlsplit(f"//{host_header}")
            host = parsed_host.hostname
            port = parsed_host.port
        except ValueError:
            host = None
            port = None
        expected_port = self.server.server_address[1]
        if (
            host not in LOOPBACK_HOSTS
            or "@" in host_header
            or (port is not None and port != expected_port)
        ):
            self.send_json({"error": "Invalid Host header"}, 403)
            return False

        origin = self.headers.get("Origin")
        if origin:
            try:
                parsed_origin = urlsplit(origin)
                origin_port = parsed_origin.port or (80 if parsed_origin.scheme == "http" else None)
            except ValueError:
                parsed_origin = None
                origin_port = None
            if (
                parsed_origin is None
                or parsed_origin.scheme != "http"
                or parsed_origin.hostname not in LOOPBACK_HOSTS
                or origin_port != expected_port
                or parsed_origin.username is not None
                or parsed_origin.path not in {"", "/"}
            ):
                self.send_json({"error": "Cross-origin request denied"}, 403)
                return False
        return True

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise RequestBodyError(411, "Content-Length is required")
        try:
            length = int(content_length)
        except ValueError as exc:
            raise RequestBodyError(400, "Invalid Content-Length") from exc
        if length < 0:
            raise RequestBodyError(400, "Invalid Content-Length")
        limit = MAX_REQUEST_BODY_BYTES.get(urlsplit(self.path).path, 0)
        if length > limit:
            raise RequestBodyError(413, f"Request body exceeds {limit} bytes")
        try:
            body = self.rfile.read(length)
        except (TimeoutError, socket.timeout) as exc:
            raise RequestBodyError(408, "Timed out reading request body") from exc
        if len(body) != length:
            raise RequestBodyError(400, "Incomplete request body")
        return json.loads(body.decode("utf-8"))

    def proxy_models(self):
        try:
            return self.send_json(get_model_status())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OllamaError) as exc:
            return self.send_json({"error": f"Unable to reach Ollama at {OLLAMA_BASE_URL}: {exc}"}, 502)

    def load_model(self):
        try:
            body = self.read_json_body()
            model_name = body.get("model")
            if not isinstance(model_name, str) or not model_name.strip() or len(model_name) > 200:
                raise ValueError("Invalid model")
            status = load_ollama_model(model_name.strip())
            return self.send_json(status)
        except RequestBodyError as exc:
            return self.send_json({"error": str(exc)}, exc.status)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.send_json({"error": "Invalid JSON body"}, 400)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)
        except (urllib.error.URLError, TimeoutError, OllamaError) as exc:
            return self.send_json({"error": f"Unable to load model: {exc}"}, 502)

    def create_chat_handoff(self):
        try:
            handoff_id = create_handoff(self.read_json_body())
        except RequestBodyError as exc:
            return self.send_json({"error": str(exc)}, exc.status)
        except (json.JSONDecodeError, UnicodeDecodeError):
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
        except RequestBodyError as exc:
            return self.send_json({"error": str(exc)}, exc.status)
        except (json.JSONDecodeError, UnicodeDecodeError):
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


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    request_queue_size = MAX_CONCURRENT_REQUESTS

    def __init__(self, *args, **kwargs):
        self._request_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(REQUEST_TIMEOUT_SECONDS)
        return request, address

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: 26\r\n"
                    b"Connection: close\r\n\r\n"
                    b'{"error":"Server is busy"}'
                )
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()

    def service_actions(self):
        cleanup_handoffs()


def main():
    port = int(os.environ.get("PORT", "17865"))
    server = BoundedThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving chat UI at http://127.0.0.1:{port}")
    print(f"Proxying Ollama at {OLLAMA_BASE_URL} with default model {DEFAULT_MODEL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
