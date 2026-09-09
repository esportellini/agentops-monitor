"""Release metadata and baseline HTTP hardening."""

import pytest
from httpx import AsyncClient

from app.main import app


def test_openapi_reports_release_version():
    assert app.version == "0.2.0"


@pytest.mark.asyncio
async def test_responses_include_baseline_security_headers(client: AsyncClient):
    response = await client.get("/api/v1/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
