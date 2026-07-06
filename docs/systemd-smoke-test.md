# Linux Mint 22 systemd Smoke Test

The systemd sandbox must be validated on a disposable Linux Mint 22 Cinnamon
machine because mount namespaces and user-manager restrictions depend on the
host systemd environment. Unit-file parsing tests alone are insufficient.

Prerequisites:

- A clean test account without an existing Local LLM Chat installation
- Ollama running at `http://127.0.0.1:11434`
- A functioning `systemctl --user` session
- `sudo` access for the package-install phase

From a repository checkout, run:

```bash
./scripts/smoke-test-systemd-mint22.sh --confirm-disposable-mint-22
```

The test deliberately exercises both supported layouts. It:

1. Generates and installs the source unit in `~/.config/systemd/user`.
2. Runs `systemd-analyze --user verify` and starts/restarts that unit.
3. Verifies `/api/config` identifies this application.
4. Verifies `/api/models` reaches loopback Ollama and returns a model list.
5. Removes the source installation.
6. Builds and installs the Debian package.
7. Repeats verification against `/usr/lib/systemd/user/llm-interface.service`.

The package is left installed for log and status inspection. Record the Mint
version, systemd version, package version, and test output in Issue #9 before
closing it.
