#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${PORT:-3000}"
health_url="http://127.0.0.1:${port}/api/config"

if /usr/bin/python3 - "${health_url}" <<'PY'
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=2) as response:
        raise SystemExit(0 if response.status == 200 else 1)
except Exception:
    raise SystemExit(1)
PY
then
  echo "Local chat interface is already available at ${health_url}; leaving existing server in place."
  exit 0
fi

exec /usr/bin/python3 "${repo_dir}/app.py"
