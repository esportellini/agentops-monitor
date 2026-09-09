"""Keep public package and service versions aligned for releases."""

import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.2.0"


def test_product_versions_are_consistent():
    frontend = json.loads((ROOT / "frontend" / "package.json").read_text())
    sdk = tomllib.loads((ROOT / "sdk-python" / "pyproject.toml").read_text())
    backend_version = (ROOT / "backend" / "app" / "version.py").read_text()
    sdk_init = (ROOT / "sdk-python" / "agentops_monitor" / "__init__.py").read_text()
    sdk_transport = (ROOT / "sdk-python" / "agentops_monitor" / "_transport.py").read_text()

    assert frontend["version"] == EXPECTED_VERSION
    assert sdk["project"]["version"] == EXPECTED_VERSION
    assert re.search(rf'PRODUCT_VERSION\s*=\s*"{EXPECTED_VERSION}"', backend_version)
    assert f'__version__ = "{EXPECTED_VERSION}"' in sdk_init
    assert f"agentops-monitor-python/{EXPECTED_VERSION}" in sdk_transport
