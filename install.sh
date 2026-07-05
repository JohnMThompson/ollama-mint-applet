#!/usr/bin/env bash
set -euo pipefail

readonly repository="${LLM_INTERFACE_REPOSITORY:-JohnMThompson/ollama-mint-applet}"
readonly api_base="${GITHUB_API_URL:-https://api.github.com}"
readonly requested_version="${VERSION:-latest}"

die() {
    printf 'Local LLM Chat installer: %s\n' "$*" >&2
    exit 1
}

for command in curl python3 sha256sum apt-get systemctl; do
    command -v "${command}" >/dev/null 2>&1 || die "required command not found: ${command}"
done

legacy_applet="${HOME}/.local/share/cinnamon/applets/local-mistral-chat@local"
legacy_service="${HOME}/.config/systemd/user/llm-interface.service"
if [[ -e "${legacy_applet}" || -L "${legacy_applet}" || -e "${legacy_service}" || -L "${legacy_service}" ]]; then
    die "legacy source installation detected. Remove the applet from the Cinnamon panel, then run:
  systemctl --user disable --now llm-interface.service
  rm -rf '${legacy_applet}'
  rm -f '${legacy_service}'
  systemctl --user daemon-reload
Then run this installer again. No files were changed."
fi

if [[ "${requested_version}" == "latest" ]]; then
    release_url="${api_base}/repos/${repository}/releases/latest"
else
    [[ "${requested_version}" =~ ^v?[0-9][0-9A-Za-z.+:~_-]*$ ]] ||
        die "invalid VERSION: ${requested_version}"
    tag="${requested_version}"
    [[ "${tag}" == v* ]] || tag="v${tag}"
    release_url="${api_base}/repos/${repository}/releases/tags/${tag}"
fi

work_dir="$(mktemp -d)"
cleanup() {
    rm -rf "${work_dir}"
}
trap cleanup EXIT

release_json="${work_dir}/release.json"
curl -fsSL --retry 3 -H 'Accept: application/vnd.github+json' \
    "${release_url}" -o "${release_json}" ||
    die "could not resolve GitHub release (${requested_version})"

mapfile -t release < <(python3 - "${release_json}" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    data = json.load(source)
if data.get("draft") or data.get("prerelease"):
    raise SystemExit("release must be published and stable")
tag = data.get("tag_name", "")
assets = data.get("assets", [])
debs = [a for a in assets if re.fullmatch(r"local-llm-chat_[^/]+_all\.deb", a.get("name", ""))]
sums = [a for a in assets if a.get("name") == "SHA256SUMS"]
if len(debs) != 1 or len(sums) != 1:
    raise SystemExit("release must contain one local-llm-chat_*_all.deb and SHA256SUMS")
print(tag)
print(debs[0]["name"])
print(debs[0]["browser_download_url"])
print(sums[0]["browser_download_url"])
PY
) || die "release metadata is invalid or required assets are missing"

[[ "${#release[@]}" -eq 4 ]] || die "release metadata is incomplete"
tag="${release[0]}"
package_name="${release[1]}"
package_path="${work_dir}/${package_name}"
checksum_path="${work_dir}/SHA256SUMS"

printf 'Installing Local LLM Chat release %s\n' "${tag}"
printf 'Downloading %s\n' "${package_name}"
curl -fsSL --retry 3 "${release[2]}" -o "${package_path}" ||
    die "failed to download ${package_name}"
curl -fsSL --retry 3 "${release[3]}" -o "${checksum_path}" ||
    die "failed to download SHA256SUMS"

expected="$(awk -v name="${package_name}" '$2 == name || $2 == "*" name { print $1; exit }' "${checksum_path}")"
[[ "${expected}" =~ ^[[:xdigit:]]{64}$ ]] ||
    die "SHA256SUMS has no valid entry for ${package_name}"
actual="$(sha256sum "${package_path}" | awk '{print $1}')"
[[ "${actual,,}" == "${expected,,}" ]] || die "checksum verification failed for ${package_name}"

printf 'Verified SHA-256: %s\n' "${actual}"
if [[ "${EUID}" -eq 0 ]]; then
    apt-get install -y "${package_path}"
else
    command -v sudo >/dev/null 2>&1 || die "sudo is required to install the Debian package"
    sudo apt-get install -y "${package_path}"
fi

systemctl --user daemon-reload ||
    die "package installed, but the user systemd manager could not be reloaded"
systemctl --user enable --now llm-interface.service ||
    die "package installed, but llm-interface.service could not be started"
printf 'Local LLM Chat %s is installed and running.\n' "${tag}"
