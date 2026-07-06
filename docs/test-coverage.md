# Test Coverage

The automated suite covers the application at four layers.

| Area | Coverage |
| --- | --- |
| HTTP service | Running server requests for configuration, model discovery/loading, chat streaming, single-use handoffs, security headers, malformed JSON and UTF-8, schema errors, body limits, Host validation, and Origin validation |
| Ollama integration | Real HTTP proxying against a deterministic mock Ollama server, including a final NDJSON record without a newline |
| Browser | Headless Chrome coverage for persisted-state migration, retention, storage failures, keyboard behavior, accessibility state, streaming generation, cancellation, and reload persistence |
| Cinnamon applet | Isolated NDJSON parser coverage for chunk boundaries, final records, Unicode, upstream errors, and malformed records; JavaScript syntax checks for the GJS integration |
| Packaging | Installer behavior, authoritative versions, systemd rendering and verification, sandbox directives, release checksums, and byte-for-byte reproducible Debian builds |

Linux Mint desktop integration that requires a real Cinnamon session remains in
the documented Mint 22 smoke test rather than CI.
