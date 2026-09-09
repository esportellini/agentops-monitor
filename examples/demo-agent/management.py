"""Small management API client used by the reproducible demo."""
from __future__ import annotations

import time
from typing import Any, Callable

import httpx


class ManagementClient:
    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.org_id: int | None = None

    def close(self) -> None:
        self.http.close()

    def login(self, email: str, password: str) -> None:
        response = self.http.post("/api/v1/auth/login", json={"email": email, "password": password})
        self._check(response)
        self.http.headers["Authorization"] = f"Bearer {response.json()['access_token']}"

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.http.request(method, path, **kwargs)
        self._check(response)
        return response.json() if response.content else None

    @staticmethod
    def _check(response: httpx.Response) -> None:
        if response.is_error:
            raise RuntimeError(f"management API returned HTTP {response.status_code} for {response.request.method} {response.request.url.path}")

    def org_path(self, suffix: str) -> str:
        if self.org_id is None:
            raise RuntimeError("organization has not been resolved")
        return f"/api/v1/organizations/{self.org_id}/{suffix.lstrip('/')}"

    def resolve_organization(self, slug: str) -> dict[str, Any]:
        rows = self.request("GET", "/api/v1/organizations")
        org = next((row for row in rows if row["slug"] == slug), None)
        if org is None:
            raise RuntimeError(f"organization slug {slug!r} was not found")
        self.org_id = org["id"]
        return org

    def get_or_create(self, list_path: str, create_path: str, predicate: Callable[[dict], bool], payload: dict) -> dict:
        data = self.request("GET", list_path)
        rows = data.get("items", data) if isinstance(data, dict) else data
        found = next((row for row in rows if predicate(row)), None)
        return found or self.request("POST", create_path, json=payload)

    def wait_for(self, fetch: Callable[[], list[dict]], predicate: Callable[[dict], bool], timeout: float = 15.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = next((row for row in fetch() if predicate(row)), None)
            if found:
                return found
            time.sleep(0.15)
        raise TimeoutError("timed out waiting for management API state")

    def find_trace(self, name: str, agent_id: int) -> dict:
        data = self.request("GET", self.org_path("traces"), params={"search": name, "agent_id": agent_id, "limit": 200})
        row = next((item for item in data["items"] if item["name"] == name), None)
        if row is None:
            raise RuntimeError(f"trace {name!r} not found")
        return self.request("GET", self.org_path(f"traces/{row['id']}"))

    def findings_for_trace(self, trace_id: int, agent_id: int) -> list[dict]:
        data = self.request("GET", self.org_path("security/findings"), params={"agent_id": agent_id, "limit": 200})
        return [row for row in data["items"] if row["trace_id"] == trace_id]

    def incidents_for_trace(self, external_trace_id: str, agent_id: int) -> list[dict]:
        data = self.request("GET", self.org_path("alerts/incidents"), params={"agent_id": agent_id, "limit": 200})
        return [row for row in data["items"] if row["external_trace_id"] == external_trace_id]
