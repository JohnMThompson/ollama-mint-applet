#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${PORT:-17865}"
health_url="http://127.0.0.1:${port}/api/config"
python_bin="${PYTHON_BIN:-/usr/bin/python3}"

if "${python_bin}" "${repo_dir}/scripts/check-service-health.py" "${health_url}"
then
  echo "Local chat interface is already available at ${health_url}; leaving existing server in place."
  exit 0
fi

exec "${python_bin}" "${repo_dir}/app.py"
