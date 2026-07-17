#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${PORT:-17865}"
health_url="http://127.0.0.1:${port}/api/config"
python_bin="${PYTHON_BIN:-/usr/bin/python3}"
health_recheck_seconds="${HEALTH_RECHECK_SECONDS:-5}"

announced_existing_server=0
while "${python_bin}" "${repo_dir}/scripts/check-service-health.py" "${health_url}"; do
  if [[ "${announced_existing_server}" -eq 0 ]]; then
    echo "Local chat interface is already available at ${health_url}; waiting for it to stop before starting the managed server."
    announced_existing_server=1
  fi
  sleep "${health_recheck_seconds}"
done

exec "${python_bin}" "${repo_dir}/app.py"
