# Contributing

Contributions are welcome through focused pull requests.

## Setup

1. Install Python 3.12, Node.js 20, Docker, and Docker Compose.
2. Copy `.env.example` to `.env` for manual development.
3. Install backend dependencies with `python -m pip install -r backend/requirements.txt`.
4. Install the SDK with `python -m pip install -e "./sdk-python[dev]"`.
5. Install frontend dependencies with `cd frontend && npm ci`.

## Validate changes

Run the relevant unit suites and frontend checks described in [README.md](README.md). Changes that affect integrated behavior must also pass:

```bash
python scripts/demo.py --reset
```

## Pull requests

Keep changes scoped, explain observable behavior, add meaningful regression coverage, and update documentation when contracts or operations change. Never commit `.env`, credentials, runtime reports, logs, database files, or real user data.

Report security issues privately according to [SECURITY.md](SECURITY.md), rather than opening a public issue.
