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


def test_service_applies_privilege_and_filesystem_restrictions():
    directives = service_directives()

    for name in (
        "NoNewPrivileges",
        "PrivateDevices",
        "PrivateTmp",
        "ProtectControlGroups",
        "ProtectKernelModules",
        "ProtectKernelTunables",
        "ProtectSystem",
        "RestrictNamespaces",
        "RestrictRealtime",
        "RestrictSUIDSGID",
        "LockPersonality",
        "MemoryDenyWriteExecute",
    ):
        assert directives[name] in {"yes", "strict"}
    assert directives["CapabilityBoundingSet"] == ""
    assert directives["AmbientCapabilities"] == ""


def test_service_preserves_source_reads_and_loopback_network_families():
    directives = service_directives()

    assert directives["ProtectHome"] == "read-only"
    families = set(directives["RestrictAddressFamilies"].split())
    assert families == {"AF_UNIX", "AF_INET", "AF_INET6"}
