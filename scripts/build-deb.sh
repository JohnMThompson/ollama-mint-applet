#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="${1:-$(python3 -c 'import json; print(json.load(open("'"${repo_dir}"'/cinnamon/local-mistral-chat@local/metadata.json"))["version"])')}"
architecture="all"
package_name="local-llm-chat"
build_root="$(mktemp -d)"
package_root="${build_root}/${package_name}_${version}_${architecture}"
output_dir="${repo_dir}/dist"

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
install -m 0644 "${repo_dir}/web/"* "${package_root}/usr/lib/llm-interface/web/"
install -m 0644 \
    "${repo_dir}/cinnamon/local-mistral-chat@local/"* \
    "${package_root}/usr/share/cinnamon/applets/local-mistral-chat@local/"
sed "s|@REPO_DIR@|/usr/lib/llm-interface|g" \
    "${repo_dir}/systemd/llm-interface.service" \
    > "${package_root}/usr/lib/systemd/user/llm-interface.service"
chmod 0644 "${package_root}/usr/lib/systemd/user/llm-interface.service"
ln -s /usr/lib/systemd/user/llm-interface.service \
    "${package_root}/etc/systemd/user/default.target.wants/llm-interface.service"
install -m 0644 "${repo_dir}/README.md" "${package_root}/usr/share/doc/${package_name}/README.md"
install -m 0644 "${repo_dir}/LICENSE" "${package_root}/usr/share/doc/${package_name}/copyright"
sed "s/@VERSION@/${version}/g" "${repo_dir}/packaging/debian/changelog" \
    | gzip -9n > "${package_root}/usr/share/doc/${package_name}/changelog.gz"
chmod 0644 "${package_root}/usr/share/doc/${package_name}/changelog.gz"

output_path="${output_dir}/${package_name}_${version}_${architecture}.deb"
dpkg-deb --root-owner-group --build "${package_root}" "${output_path}"
echo "Built ${output_path}"
