# Local Mistral Chat

A dependency-free browser chat interface for an Ollama-hosted Mistral model.

## Run

Start Ollama with your model loaded:

```bash
ollama serve
ollama run mistral
```

Then run the local web server:

```bash
python3 app.py
```

Open http://127.0.0.1:3000.

## Configuration

The server defaults to `http://127.0.0.1:11434` and model `mistral`.

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11434 OLLAMA_MODEL=mistral PORT=3000 python3 app.py
```

Chat history and per-chat settings are stored in browser local storage.
