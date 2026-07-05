#!/usr/bin/env python3
import json
import sys
import urllib.request


def is_local_llm_chat_available(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return (
            response.status == 200
            and isinstance(payload, dict)
            and payload.get("application") == "local-llm-chat"
            and payload.get("apiVersion") == 1
        )
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: check-service-health.py URL")
    raise SystemExit(0 if is_local_llm_chat_available(sys.argv[1]) else 1)
