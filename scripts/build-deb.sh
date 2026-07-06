#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(tr -d '[:space:]' < "${repo_dir}/VERSION")"
requested_version="${1:-${version}}"
architecture="all"
package_name="local-llm-chat"
build_root="$(mktemp -d)"
package_root="${build_root}/${package_name}_${version}_${architecture}"
output_dir="${OUTPUT_DIR:-${repo_dir}/dist}"
source_date_epoch="${SOURCE_DATE_EPOCH:-$(git -C "${repo_dir}" log -1 --format=%ct)}"

cleanup() {
    rm -rf "${build_root}"
}
trap cleanup EXIT

command -v dpkg-deb >/dev/null 2>&1 || {
    echo "dpkg-deb is required to build the package." >&2
    exit 1
}

if [[ ! "${version}" =~ ^[0-9][0-9A-Za-z.+:~_-]*$ ]]; then
    echo "Invalid Debian package version: ${version}" >&2
    exit 1
fi
if [[ ! "${source_date_epoch}" =~ ^[0-9]+$ ]]; then
    echo "SOURCE_DATE_EPOCH must be a non-negative integer." >&2
    exit 1
fi
export SOURCE_DATE_EPOCH="${source_date_epoch}"
export TZ=UTC
export LC_ALL=C
if [[ "${requested_version}" != "${version}" ]]; then
    echo "Requested version ${requested_version} does not match VERSION (${version})." >&2
    exit 1
fi
python3 - "${repo_dir}/cinnamon/local-mistral-chat@local/metadata.json" "${version}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    metadata = json.load(source)
if metadata.get("version") != sys.argv[2]:
    raise SystemExit(
        f"Cinnamon metadata version {metadata.get('version')!r} "
        f"does not match VERSION ({sys.argv[2]})"
    )
PY

install -d \
    "${package_root}/DEBIAN" \
    "${package_root}/usr/lib/llm-interface/scripts" \
    "${package_root}/usr/lib/llm-interface/web" \
    "${package_root}/usr/lib/systemd/user" \
    "${package_root}/etc/systemd/user/default.target.wants" \
    "${package_root}/usr/share/cinnamon/applets/local-mistral-chat@local" \
    "${package_root}/usr/share/doc/${package_name}" \
    "${output_dir}"

sed "s/@VERSION@/${version}/g" \
    "${repo_dir}/packaging/debian/control" \
    > "${package_root}/DEBIAN/control"
install -m 0644 "${repo_dir}/app.py" "${package_root}/usr/lib/llm-interface/app.py"
install -m 0755 \
    "${repo_dir}/scripts/run-llm-interface-service.sh" \
    "${package_root}/usr/lib/llm-interface/scripts/run-llm-interface-service.sh"
install -m 0755 \
    "${repo_dir}/scripts/check-service-health.py" \
    "${package_root}/usr/lib/llm-interface/scripts/check-service-health.py"
install -m 0644 "${repo_dir}/web/"* "${package_root}/usr/lib/llm-interface/web/"
install -m 0644 \
    "${repo_dir}/cinnamon/local-mistral-chat@local/"* \
    "${package_root}/usr/share/cinnamon/applets/local-mistral-chat@local/"
python3 "${repo_dir}/scripts/render-systemd-unit.py" \
    "${repo_dir}/systemd/llm-interface.service" \
    "/usr/lib/llm-interface" \
    "${package_root}/usr/lib/systemd/user/llm-interface.service"
chmod 0644 "${package_root}/usr/lib/systemd/user/llm-interface.service"
ln -s /usr/lib/systemd/user/llm-interface.service \
    "${package_root}/etc/systemd/user/default.target.wants/llm-interface.service"
install -m 0644 "${repo_dir}/README.md" "${package_root}/usr/share/doc/${package_name}/README.md"
install -m 0644 "${repo_dir}/LICENSE" "${package_root}/usr/share/doc/${package_name}/copyright"
sed "s/@VERSION@/${version}/g" "${repo_dir}/packaging/debian/changelog" \
    | gzip -9n > "${package_root}/usr/share/doc/${package_name}/changelog.gz"
chmod 0644 "${package_root}/usr/share/doc/${package_name}/changelog.gz"

output_path="${output_dir}/${package_name}_${version}_${architecture}.deb"
find "${package_root}" -exec \
    touch --no-dereference --date="@${SOURCE_DATE_EPOCH}" {} +
dpkg-deb --root-owner-group --uniform-compression --build \
    "${package_root}" "${output_path}"
(
    cd "${output_dir}"
    sha256sum "$(basename "${output_path}")" > SHA256SUMS
)
echo "Built ${output_path}"
echo "Wrote ${output_dir}/SHA256SUMS"
