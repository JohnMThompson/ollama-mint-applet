#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work_dir="$(mktemp -d)"

cleanup() {
    rm -rf "${work_dir}"
}
trap cleanup EXIT

epoch="${SOURCE_DATE_EPOCH:-$(git -C "${repo_dir}" log -1 --format=%ct)}"
version="$(tr -d '[:space:]' < "${repo_dir}/VERSION")"
package_name="local-llm-chat_${version}_all.deb"

SOURCE_DATE_EPOCH="${epoch}" OUTPUT_DIR="${work_dir}/first" \
    "${repo_dir}/scripts/build-deb.sh"
SOURCE_DATE_EPOCH="${epoch}" OUTPUT_DIR="${work_dir}/second" \
    "${repo_dir}/scripts/build-deb.sh"

first="${work_dir}/first/${package_name}"
second="${work_dir}/second/${package_name}"
if ! cmp --silent "${first}" "${second}"; then
    echo "Package builds are not reproducible:" >&2
    sha256sum "${first}" "${second}" >&2
    exit 1
fi

sha256sum "${first}"
echo "Reproducible build verified with SOURCE_DATE_EPOCH=${epoch}."
