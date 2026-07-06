#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
uuid="local-mistral-chat@local"
applet_src="${repo_dir}/cinnamon/${uuid}"
applet_dest="${HOME}/.local/share/cinnamon/applets/${uuid}"
service_src="${repo_dir}/systemd/llm-interface.service"
service_dest="${HOME}/.config/systemd/user/llm-interface.service"

install -d "${applet_dest}"
install -m 0644 "${applet_src}/"* "${applet_dest}/"

install -d "$(dirname "${service_dest}")"
python3 "${repo_dir}/scripts/render-systemd-unit.py" \
    "${service_src}" "${repo_dir}" "${service_dest}"

systemctl --user daemon-reload
systemctl --user enable --now llm-interface.service

echo "Installed ${uuid}."
echo "Add it from Cinnamon Applets, or reload Cinnamon if it is already listed."
echo "Service status: systemctl --user status llm-interface.service"
