import subprocess
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text().strip()


def test_build_rejects_version_different_from_authoritative_version():
    result = subprocess.run(
        [str(ROOT / "scripts/build-deb.sh"), "999.0.0"],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "does not match VERSION" in result.stderr


def test_build_rejects_invalid_source_date_epoch(tmp_path):
    env = os.environ.copy()
    env.update({"SOURCE_DATE_EPOCH": "invalid", "OUTPUT_DIR": str(tmp_path)})

    result = subprocess.run(
        [str(ROOT / "scripts/build-deb.sh")],
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "SOURCE_DATE_EPOCH" in result.stderr


def test_build_is_reproducible(tmp_path):
    hashes = []
    for output_name in ("first", "second"):
        output = tmp_path / output_name
        env = os.environ.copy()
        env.update({"SOURCE_DATE_EPOCH": "1700000000", "OUTPUT_DIR": str(output)})
        subprocess.run(
            [str(ROOT / "scripts/build-deb.sh")],
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        hashes.append((output / f"local-llm-chat_{VERSION}_all.deb").read_bytes())

    assert hashes[0] == hashes[1]
