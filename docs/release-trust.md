# Release Artifact Trust

Each tagged release publishes:

- A versioned `install.sh`
- A versioned Debian package
- `SHA256SUMS` covering both files
- GitHub artifact attestations covering all three files

The documented `releases/latest/download/install.sh` URL redirects to an
installer attached to a specific GitHub release. The installer then selects an
explicit release through the GitHub API and verifies the downloaded Debian
package against that release's checksum file.

The checksum detects download corruption and mismatched assets. Because the
checksum and package share the same release, the checksum alone does not
protect against compromise of the repository or its release credentials.
GitHub artifact attestations additionally bind the files to this repository,
the tagged source commit, and the release workflow using a Sigstore-signed
statement.

With GitHub CLI 2.49 or newer, verify downloaded release files before using
them:

```bash
gh attestation verify install.sh --repo JohnMThompson/ollama-mint-applet
gh attestation verify local-llm-chat_VERSION_all.deb --repo JohnMThompson/ollama-mint-applet
sha256sum --check --ignore-missing SHA256SUMS
```

The workflow's external actions are pinned to full commit digests. Maintainers
must review and deliberately update those digests when upgrading an action.
