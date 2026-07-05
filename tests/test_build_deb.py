import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_build_rejects_version_different_from_authoritative_version():
    result = subprocess.run(
        [str(ROOT / "scripts/build-deb.sh"), "999.0.0"],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "does not match VERSION" in result.stderr
