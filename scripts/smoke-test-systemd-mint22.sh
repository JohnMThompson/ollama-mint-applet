#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
service_name="llm-interface.service"
source_unit="${HOME}/.config/systemd/user/${service_name}"
source_applet="${HOME}/.local/share/cinnamon/applets/local-mistral-chat@local"
package_unit="/usr/lib/systemd/user/${service_name}"

die() {
    printf 'systemd smoke test: %s\n' "$*" >&2
    exit 1
}

[[ "${1:-}" == "--confirm-disposable-mint-22" ]] ||
    die "run only on a disposable Mint 22 Cinnamon test machine:
  $0 --confirm-disposable-mint-22"

# shellcheck source=/dev/null
source /etc/os-release
[[ "${ID:-}" == "linuxmint" && "${VERSION_ID:-}" == "22"* ]] ||
    die "Linux Mint 22 is required (found ${PRETTY_NAME:-unknown})"
systemctl --user show-environment >/dev/null ||
    die "a functioning user systemd manager is required"
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null ||
    die "Ollama must be running on loopback"
[[ ! -e "${source_unit}" && ! -e "${source_applet}" ]] ||
    die "legacy/source installation already exists; use a clean test account"
if dpkg-query -W -f='${Status}' local-llm-chat 2>/dev/null |
    grep -q 'install ok installed'; then
    die "local-llm-chat is already installed; use a clean test machine"
fi

check_api() {
    python3 - <<'PY'
import json
import urllib.request

def read(path):
    with urllib.request.urlopen(f"http://127.0.0.1:17865{path}", timeout=10) as response:
        if response.status != 200:
            raise SystemExit(f"{path} returned HTTP {response.status}")
        return json.load(response)

config = read("/api/config")
if config.get("application") != "local-llm-chat" or config.get("apiVersion") != 1:
    raise SystemExit("/api/config did not identify Local LLM Chat API version 1")
models = read("/api/models")
if not isinstance(models.get("models"), list):
    raise SystemExit("/api/models did not return a model list")
PY
}

cleanup_source_install() {
    systemctl --user disable --now "${service_name}" >/dev/null 2>&1 || true
    rm -f "${source_unit}"
    rm -rf "${source_applet}"
    systemctl --user daemon-reload >/dev/null 2>&1 || true
}
trap cleanup_source_install EXIT

printf 'Testing source-installed user unit...\n'
"${repo_dir}/scripts/install-cinnamon-applet.sh"
systemd-analyze --user verify "${source_unit}"
systemctl --user restart "${service_name}"
check_api
cleanup_source_install
trap - EXIT

printf 'Testing packaged user unit...\n'
"${repo_dir}/scripts/build-deb.sh"
version="$(tr -d '[:space:]' < "${repo_dir}/VERSION")"
package="${repo_dir}/dist/local-llm-chat_${version}_all.deb"
sudo apt-get install -y "${package}"
systemd-analyze --user verify "${package_unit}"
systemctl --user daemon-reload
systemctl --user enable --now "${service_name}"
systemctl --user restart "${service_name}"
check_api

printf 'Both systemd installation paths passed on %s.\n' "${PRETTY_NAME}"
printf 'The package remains installed for inspection; remove it with sudo apt remove local-llm-chat.\n'
