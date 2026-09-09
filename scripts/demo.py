"""Start the local stack and run the reproducible end-to-end demo."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker", "compose", "--project-name", "agentops-monitor-demo",
    "-f", "docker-compose.yml", "-f", "docker-compose.demo.yml", "--profile", "demo",
]


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def wait_http(url: str, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status < 500:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"service did not become ready at {url}: {last_error}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Start AgentOps Monitor and run its real end-to-end demo")
    result.add_argument("--reset", action="store_true", help="Remove local demo containers and volumes before starting")
    result.add_argument("--with-openai", action="store_true", help="Opt in to the optional OpenAI evaluation path")
    result.add_argument("--interactive-approval", action="store_true", help="Wait for a tool approval decision in the dashboard")
    return result


def main() -> int:
    args = parser().parse_args()
    run(["docker", "--version"])
    run(["docker", "compose", "version"])
    if args.reset:
        run([*COMPOSE, "down", "--volumes", "--remove-orphans"])
    run([*COMPOSE, "up", "--detach", "--build", "postgres", "redis", "backend", "frontend"])
    wait_http("http://localhost:8000/api/v1/health")
    wait_http("http://localhost:3000/login")
    command = [*COMPOSE, "run", "--rm", "demo-runner"]
    if args.with_openai:
        command.append("--with-openai")
    if args.interactive_approval:
        command.append("--interactive-approval")
    run(command)
    print("Dashboard: http://localhost:3000")
    print("Backend:   http://localhost:8000")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode or 1)
