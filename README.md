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

## Install the Debian Package

On Linux Mint or another Debian-based distribution, download the package from the [latest GitHub release](https://github.com/JohnMThompson/ollama-mint-applet/releases/latest) and install it:

```bash
curl -LO https://github.com/JohnMThompson/ollama-mint-applet/releases/download/v0.1.0/local-llm-chat_0.1.0_all.deb
sudo apt install ./local-llm-chat_0.1.0_all.deb
systemctl --user daemon-reload
systemctl --user enable --now llm-interface.service
```

The package installs the server and web UI under `/usr/lib/llm-interface`, the applet under `/usr/share/cinnamon/applets`, and the user service under `/usr/lib/systemd/user`. The service is enabled automatically for future login sessions; the final two commands make it available immediately without logging out.

Add the applet after installation:

1. Right-click the Cinnamon panel and open **Applets**.
2. Find **Local LLM Chat**.
3. Add it to the panel.

The browser interface is available at <http://127.0.0.1:17865>.

### Upgrade from the Legacy Installer

If you previously installed from source with `scripts/install-cinnamon-applet.sh`, first remove **Local LLM Chat** from the Cinnamon panel. Then remove the user-local copies so they do not override packaged files:

```bash
systemctl --user disable --now llm-interface.service
rm -f ~/.config/systemd/user/llm-interface.service
rm -rf ~/.local/share/cinnamon/applets/local-mistral-chat@local
systemctl --user daemon-reload
```

Install the release package normally after completing this cleanup.

### Uninstall the Package

Remove the applet from the Cinnamon panel, then run:

```bash
systemctl --user disable --now llm-interface.service
sudo apt remove local-llm-chat
```

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

Pass a version argument to override the version from the applet metadata:

```bash
./scripts/build-deb.sh 0.1.1
```

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
