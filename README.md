# Linux Mint Local LLM Applet

A small, dependency-free chat interface for Ollama models.

The project includes:

- A browser chat UI served by `python3 app.py`
- A local Python proxy for Ollama's chat API
- An optional Linux Mint Cinnamon panel applet that opens a quick chat popup
- A Debian package that installs the complete application and user service

## Screenshots

### Cinnamon applet popup

![Local LLM  Chat Cinnamon applet popup](docs/applet-popup.png)

### Full browser UI

![Local LLM Chat browser interface](docs/web-ui.png)

## Requirements

- Linux with Python 3.10 or newer
- Ollama installed and running
- At least one model pulled into Ollama
- Linux Mint Cinnamon 6.x if you want the panel applet

No Python packages or Node packages are required.

## Install Ollama and Mistral

Install Ollama on Linux:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Start Ollama:

```bash
ollama serve
```

If Ollama was installed as a system service, start it with:

```bash
sudo systemctl start ollama
```

Pull and test Mistral:

```bash
ollama pull mistral
ollama run mistral
```

Type `/bye` to exit the Ollama terminal chat.

Useful checks:

```bash
ollama -v
ollama list
curl http://127.0.0.1:11434/api/tags
```

Official references:

- Ollama Linux install: <https://docs.ollama.com/linux>
- Mistral model page: <https://ollama.com/library/mistral>

## Install

On Linux Mint, install or upgrade to the latest published release with one command:

```sh
curl -fsSL https://github.com/JohnMThompson/ollama-mint-applet/releases/latest/download/install.sh | bash
```

The installer resolves an explicit stable GitHub release, verifies the Debian
package against that release's `SHA256SUMS`, installs or upgrades it with
`apt-get`, and enables and starts `llm-interface.service` for the current user.
It is safe to rerun. The package installs the server and web UI under
`/usr/lib/llm-interface`, the applet under `/usr/share/cinnamon/applets`, and
the user service under `/usr/lib/systemd/user`.

Tested on Linux Mint 21.3 Cinnamon. Linux Mint 22 compatibility is expected but
has not yet been runtime-validated; see
[Issue #9](https://github.com/JohnMThompson/ollama-mint-applet/issues/9).
Mint 22 is not claimed as fully supported until its Cinnamon and user-systemd
smoke test passes. Installation requires `curl`, Python 3, `sha256sum`,
`apt-get`, systemd user services, and `sudo`.

Add the applet after installation:

1. Right-click the Cinnamon panel and open **Applets**.
2. Find **Local LLM Chat**.
3. Add it to the panel.

The browser interface is available at <http://127.0.0.1:17865>.

### Legacy Source Installations

The installer stops without changing files if it detects a source installation
that would override packaged files. Remove **Local LLM Chat** from the Cinnamon
panel, then run the cleanup commands printed by the installer and rerun it.

### Uninstall and Roll Back

Remove the applet from the Cinnamon panel, then run:

```bash
systemctl --user disable --now llm-interface.service
sudo apt remove local-llm-chat
```

To roll back, choose a previous tag from
[GitHub Releases](https://github.com/JohnMThompson/ollama-mint-applet/releases)
and pass it to the same verified installer:

```sh
curl -fsSL https://github.com/JohnMThompson/ollama-mint-applet/releases/download/v0.1.0/install.sh | VERSION=v0.1.0 bash
```

This installs the package attached to that exact release. Package configuration
is retained; use `sudo apt purge local-llm-chat` instead of `remove` to discard it.
See [Release Artifact Trust](docs/release-trust.md) for checksum guarantees and
artifact-attestation verification.

## Install from Source

Source installation is intended for development. Clone the repository and run the installer:

```bash
git clone https://github.com/JohnMThompson/ollama-mint-applet.git
cd ollama-mint-applet
bash scripts/install-cinnamon-applet.sh
```

This copies the applet and service into your home directory and keeps the service tied to the checkout. Rerun the installer after source changes.

Build a Debian package from source with:

```bash
./scripts/build-deb.sh
```

`VERSION` is authoritative for package, release, and applet versions. A supplied
build version must match it:

```bash
./scripts/build-deb.sh 0.3.0
```

Reproduce a package with an explicit source timestamp:

```bash
SOURCE_DATE_EPOCH=1700000000 ./scripts/build-deb.sh
```

The build normalizes package metadata, ownership, timestamps, compression,
locale, and timezone. Verify two isolated builds are byte-for-byte identical:

```bash
./scripts/check-reproducible-build.sh
```

Release validation of the hardened user service is documented in the
[Linux Mint 22 systemd smoke test](docs/systemd-smoke-test.md).

The automated backend, browser, applet, and packaging checks are summarized in
the [test coverage matrix](docs/test-coverage.md).

## Run the Browser UI from Source

```bash
python3 app.py
```

The browser UI stores chat history and per-chat settings in browser local storage.

## Configuration

The server defaults to:

- Ollama URL: `http://127.0.0.1:11434`
- Model: `mistral`
- UI port: `17865`

Override them when running from source:

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11434 OLLAMA_MODEL=mistral PORT=17865 python3 app.py
```

### Configure the Applet Model

The applet detects installed Ollama models from the local server and shows them in a model dropdown inside the popup. Select a model there to use it for future applet messages.

The same model list is also available in the applet's Cinnamon preferences:

- Local chat server URL, default `http://127.0.0.1:17865`
- Ollama model, default `mistral`

To change the applet model:

1. Right-click the `✨` panel applet.
2. Open **Configure**.
3. Set **Ollama model** to any detected model already available in Ollama.

Install another model with:

```bash
ollama pull llama3.2
```

The full browser UI has its own model selector. The applet preference only controls the Cinnamon popup.

Model-generated browser chat titles are disabled by default because they require
a second inference after the first response. Enable them per chat in
**Settings** if improved titles are worth the additional compute and model
contention. A local fallback title is always created without another inference.

When either interface opens, it checks Ollama for a running model. A running model is selected automatically. If none is running, the interface lists downloaded models and loads the one you choose. Models loaded this way remain active until Ollama unloads them or stops; change this by setting `OLLAMA_LOAD_KEEP_ALIVE` to another Ollama duration such as `30m`.

### Continue a Popup Chat in the Browser

Click **Open Full Chat** to transfer the popup's current conversation into a new saved browser chat. The browser opens with the transferred chat selected, preserving its messages and model so you can continue the conversation with the full web interface.

The transfer is held briefly by the local server and is only available on the local machine. Opening the full chat with an empty popup continues to open the browser normally.

## Service Commands

Check the local chat service:

```bash
systemctl --user status llm-interface.service
```

Restart it:

```bash
systemctl --user restart llm-interface.service
```

View logs:

```bash
journalctl --user -u llm-interface.service -f
```

Disable autostart:

```bash
systemctl --user disable --now llm-interface.service
```

## Troubleshooting

Check that Ollama is running:

```bash
curl http://127.0.0.1:11434/api/tags
```

Check that this app's server is running:

```bash
curl http://127.0.0.1:17865/api/config
```

Check Cinnamon applet logs:

```bash
tail -n 120 ~/.xsession-errors
```

Search only for this applet:

```bash
grep -Ei "local-mistral-chat|lookingglass|error" ~/.xsession-errors
```

If port `17865` is already in use, either stop the other process or run this app with another port:

```bash
PORT=17866 python3 app.py
```

If you change the port for the service, update both:

- `systemd/llm-interface.service`
- `cinnamon/local-mistral-chat@local/applet.js`

Then rerun:

```bash
bash scripts/install-cinnamon-applet.sh
```

## Uninstall the Cinnamon Applet

Remove the applet from the panel in Cinnamon's Applets settings, then run:

```bash
systemctl --user disable --now llm-interface.service
rm -f ~/.config/systemd/user/llm-interface.service
rm -rf ~/.local/share/cinnamon/applets/local-mistral-chat@local
systemctl --user daemon-reload
```

## Notes

- The browser UI persists chat history in browser local storage.
- The Cinnamon applet is a quick-chat surface and does not share browser history.
- The app binds to `127.0.0.1` only.
