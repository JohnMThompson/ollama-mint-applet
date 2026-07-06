from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "systemd/llm-interface.service"


def service_directives():
    directives = {}
    section = None
    for raw_line in SERVICE.read_text().splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line
        elif section == "[Service]" and "=" in line:
            name, value = line.split("=", 1)
            directives[name] = value
    return directives


def test_service_avoids_unsupported_user_service_sandboxing():
    directives = service_directives()

    for name in (
        "NoNewPrivileges",
        "PrivateDevices",
        "PrivateTmp",
        "ProtectControlGroups",
        "ProtectHome",
        "ProtectKernelModules",
        "ProtectKernelTunables",
        "ProtectSystem",
        "RestrictAddressFamilies",
        "RestrictNamespaces",
        "RestrictRealtime",
        "RestrictSUIDSGID",
        "LockPersonality",
        "MemoryDenyWriteExecute",
        "CapabilityBoundingSet",
        "AmbientCapabilities",
        "SystemCallArchitectures",
    ):
        assert name not in directives


def test_service_sets_restrictive_umask():
    directives = service_directives()

    assert directives["UMask"] == "0077"
