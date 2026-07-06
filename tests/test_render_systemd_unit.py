import importlib.util
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
RENDERER_PATH = ROOT / "scripts/render-systemd-unit.py"
spec = importlib.util.spec_from_file_location("render_systemd_unit", RENDERER_PATH)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def test_quotes_systemd_special_characters_in_checkout_path(tmp_path):
    repository = tmp_path / 'LLM chat & 100% $cash "quoted" \\ path'
    repository.mkdir()
    template = (ROOT / "systemd/llm-interface.service").read_text()

    rendered = renderer.render_unit(template, repository)

    escaped_repository = renderer.systemd_path(repository.resolve())
    assert f"WorkingDirectory={escaped_repository}" in rendered
    escaped_command = (
        str(repository.resolve())
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("%", "%%")
        .replace("$", "$$")
    )
    assert (
        f'ExecStart=/usr/bin/env "{escaped_command}/scripts/run-llm-interface-service.sh"'
        in rendered
    )
    assert "@WORKING_DIRECTORY@" not in rendered
    assert "@EXEC_START@" not in rendered


@pytest.mark.parametrize("directory_name", ["ordinary", 'chat path & 100% $ "quoted"'])
def test_systemd_accepts_rendered_unit(tmp_path, directory_name):
    repository = tmp_path / directory_name
    script = repository / "scripts/run-llm-interface-service.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    unit = tmp_path / "rendered-test.service"
    unit.write_text(
        renderer.render_unit(
            (ROOT / "systemd/llm-interface.service").read_text(),
            repository,
        )
    )
    env = os.environ.copy()
    env["SYSTEMD_UNIT_PATH"] = (
        f"{tmp_path}:/lib/systemd/system:/usr/lib/systemd/system"
    )

    result = subprocess.run(
        ["systemd-analyze", "verify", str(unit)],
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr


def test_rejects_incomplete_or_duplicated_template_markers():
    with pytest.raises(ValueError, match="exactly one"):
        renderer.render_unit("WorkingDirectory=@WORKING_DIRECTORY@", "/tmp/example")
    with pytest.raises(ValueError, match="exactly one"):
        renderer.render_unit(
            "WorkingDirectory=@WORKING_DIRECTORY@\n"
            "Again=@WORKING_DIRECTORY@\n"
            "ExecStart=@EXEC_START@\n",
            "/tmp/example",
        )
