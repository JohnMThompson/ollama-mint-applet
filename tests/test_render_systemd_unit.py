import importlib.util
from pathlib import Path

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

    escaped_repository = (
        str(repository.resolve())
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("%", "%%")
    )
    assert f'WorkingDirectory="{escaped_repository}"' in rendered
    escaped_command = escaped_repository.replace("$", "$$")
    assert (
        f'ExecStart="{escaped_command}/scripts/run-llm-interface-service.sh"'
        in rendered
    )
    assert "@WORKING_DIRECTORY@" not in rendered
    assert "@EXEC_START@" not in rendered


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
