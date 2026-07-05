import hashlib
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


def make_command(path, name, body):
    command = path / name
    command.write_text("#!/usr/bin/env bash\nset -e\n" + body)
    command.chmod(0o755)


def installer_environment(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    package = tmp_path / "local-llm-chat_1.2.3_all.deb"
    package.write_bytes(b"test Debian package")
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{digest}  {package.name}\n")
    release = tmp_path / "release.json"
    release.write_text(json.dumps({
        "tag_name": "v1.2.3",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": package.name, "browser_download_url": f"file://{package}"},
            {"name": "SHA256SUMS", "browser_download_url": f"file://{sums}"},
        ],
    }))
    make_command(bin_dir, "curl", r'''
out=""
url=""
while (($#)); do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -H|--retry) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
if [[ "$url" == */releases/latest || "$url" == */releases/tags/v1.2.3 ]]; then cp "$RELEASE_JSON" "$out"
elif [[ "$url" == file://* ]]; then cp "${url#file://}" "$out"
else exit 22
fi
''')
    make_command(bin_dir, "apt-get", 'printf "apt-get %s\\n" "$*" >> "$COMMAND_LOG"\n')
    make_command(bin_dir, "sudo", '"$@"\n')
    make_command(bin_dir, "systemctl", 'printf "systemctl %s\\n" "$*" >> "$COMMAND_LOG"\n')
    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{env['PATH']}",
        "HOME": str(home),
        "GITHUB_API_URL": "https://api.test",
        "RELEASE_JSON": str(release),
        "COMMAND_LOG": str(tmp_path / "commands.log"),
    })
    return env, home, package


def test_installs_verified_latest_release_and_starts_service(tmp_path):
    env, _, package = installer_environment(tmp_path)
    result = subprocess.run(
        ["bash", str(INSTALLER)], env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    log = Path(env["COMMAND_LOG"]).read_text()
    assert f"apt-get install -y " in log
    assert package.name in result.stdout
    assert "systemctl --user daemon-reload" in log
    assert "systemctl --user enable --now llm-interface.service" in log


def test_rerun_is_idempotent_upgrade_path(tmp_path):
    env, _, _ = installer_environment(tmp_path)

    first = subprocess.run(
        ["bash", str(INSTALLER)], env=env, text=True, capture_output=True
    )
    second = subprocess.run(
        ["bash", str(INSTALLER)], env=env, text=True, capture_output=True
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert Path(env["COMMAND_LOG"]).read_text().count("apt-get install -y") == 2


def test_installs_requested_release_for_rollback(tmp_path):
    env, _, _ = installer_environment(tmp_path)
    env["VERSION"] = "1.2.3"

    result = subprocess.run(
        ["bash", str(INSTALLER)], env=env, text=True, capture_output=True
    )

    assert result.returncode == 0, result.stderr
    assert "release v1.2.3" in result.stdout


def test_legacy_installation_fails_before_downloading(tmp_path):
    env, home, _ = installer_environment(tmp_path)
    legacy = home / ".config/systemd/user/llm-interface.service"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy")
    result = subprocess.run(
        ["bash", str(INSTALLER)], env=env, text=True, capture_output=True
    )
    assert result.returncode != 0
    assert "legacy source installation detected" in result.stderr
    assert not Path(env["COMMAND_LOG"]).exists()


def test_checksum_mismatch_fails_before_install(tmp_path):
    env, _, package = installer_environment(tmp_path)
    package.write_bytes(b"tampered")
    result = subprocess.run(
        ["bash", str(INSTALLER)], env=env, text=True, capture_output=True
    )
    assert result.returncode != 0
    assert "checksum verification failed" in result.stderr
    assert not Path(env["COMMAND_LOG"]).exists()
