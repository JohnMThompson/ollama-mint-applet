import importlib.util
import os
from pathlib import Path
import subprocess
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "scripts/check-service-health.py"
spec = importlib.util.spec_from_file_location("service_health", CHECKER_PATH)
service_health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service_health)


def test_health_check_accepts_only_expected_application_identity():
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = b'{"application":"local-llm-chat","apiVersion":1}'
    with mock.patch.object(service_health.urllib.request, "urlopen", return_value=response):
        assert service_health.is_local_llm_chat_available("http://service/api/config")


def test_health_check_rejects_unrelated_http_200():
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = b'{"status":"ok"}'
    with mock.patch.object(service_health.urllib.request, "urlopen", return_value=response):
        assert not service_health.is_local_llm_chat_available(
            "http://service/api/config"
        )


def test_health_check_rejects_unavailable_service():
    assert not service_health.is_local_llm_chat_available(
        "http://127.0.0.1:1/api/config"
    )


def test_wrapper_starts_app_when_health_check_fails(tmp_path):
    log = tmp_path / "python.log"
    python = tmp_path / "python"
    python.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  *check-service-health.py) exit "$HEALTH_STATUS" ;;\n'
        '  *) printf "%s\\n" "$*" > "$PYTHON_LOG" ;;\n'
        "esac\n"
    )
    python.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PYTHON_BIN": str(python),
            "PYTHON_LOG": str(log),
            "HEALTH_STATUS": "1",
        }
    )

    result = subprocess.run(
        [str(ROOT / "scripts/run-llm-interface-service.sh")],
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert log.read_text().strip().endswith("/app.py")


def test_wrapper_leaves_identified_service_running(tmp_path):
    log = tmp_path / "python.log"
    python = tmp_path / "python"
    python.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  *check-service-health.py) exit "$HEALTH_STATUS" ;;\n'
        '  *) printf "%s\\n" "$*" > "$PYTHON_LOG" ;;\n'
        "esac\n"
    )
    python.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PYTHON_BIN": str(python),
            "PYTHON_LOG": str(log),
            "HEALTH_STATUS": "0",
        }
    )

    result = subprocess.run(
        [str(ROOT / "scripts/run-llm-interface-service.sh")],
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "already available" in result.stdout
    assert not log.exists()
