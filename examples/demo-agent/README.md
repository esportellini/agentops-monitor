# Demo agent

This runner is started by `python scripts/demo.py`. It logs in through the management API, resolves or creates resources by slug/name, creates a short-lived ingest key, runs every scenario through the real Python SDK, writes a safe report, and revokes the key.

The default path is deterministic and offline. Use `--with-openai` only to opt in to an optional externally configured provider path; all required checks continue to use the mock provider.
