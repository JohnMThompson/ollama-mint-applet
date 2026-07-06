import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
UUID = "local-mistral-chat@local"
APPLET_SOURCE = ROOT / "cinnamon" / UUID


def required_applet_files():
    applet_source = (APPLET_SOURCE / "applet.js").read_text()
    local_modules = re.findall(
        r"imports\.applets\[metadata\.uuid\]\.([A-Za-z][A-Za-z0-9]*)",
        applet_source,
    )
    return {
        "applet.js",
        "metadata.json",
        "settings-schema.json",
        "stylesheet.css",
        *(f"{module}.js" for module in local_modules),
    }


def assert_complete_applet_layout(applet_directory):
    missing = required_applet_files() - {
        path.name for path in applet_directory.iterdir() if path.is_file()
    }
    assert not missing, f"missing runtime applet files: {sorted(missing)}"


def test_source_installer_copies_every_runtime_applet_file(tmp_path):
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    home.mkdir()
    fake_bin.mkdir()
    systemctl = fake_bin / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 0\n")
    systemctl.chmod(0o755)
    env = os.environ.copy()
    env.update({"HOME": str(home), "PATH": f"{fake_bin}:{env['PATH']}"})

    subprocess.run(
        [str(ROOT / "scripts/install-cinnamon-applet.sh")],
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    assert_complete_applet_layout(
        home / ".local/share/cinnamon/applets" / UUID
    )


def test_debian_package_contains_every_runtime_applet_file(tmp_path):
    output = tmp_path / "dist"
    package_root = tmp_path / "package"
    env = os.environ.copy()
    env.update({"OUTPUT_DIR": str(output), "SOURCE_DATE_EPOCH": "1700000000"})
    subprocess.run(
        [str(ROOT / "scripts/build-deb.sh")],
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "dpkg-deb",
            "--extract",
            str(output / "local-llm-chat_0.1.0_all.deb"),
            str(package_root),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert_complete_applet_layout(
        package_root / "usr/share/cinnamon/applets" / UUID
    )
