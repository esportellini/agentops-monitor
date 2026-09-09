from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "examples" / "demo-agent"
sys.path.insert(0, str(DEMO_DIR))

from management import ManagementClient
from reporting import assert_report_safe, write_report
import verification


class FakeManagement(ManagementClient):
    def __init__(self, responses):
        self.responses = list(responses)

    def request(self, method, path, **kwargs):
        return self.responses.pop(0)


def test_get_or_create_resolves_dynamic_id_and_creates_when_missing():
    found = FakeManagement([[{"id": 17, "slug": "demo"}]])
    assert found.get_or_create("/list", "/create", lambda x: x["slug"] == "demo", {})["id"] == 17
    created = FakeManagement([[], {"id": 29, "slug": "demo"}])
    assert created.get_or_create("/list", "/create", lambda x: x["slug"] == "demo", {"slug": "demo"})["id"] == 29


def test_report_rejects_secret_keys_and_values(tmp_path):
    with pytest.raises(ValueError):
        assert_report_safe({"api_key": "hidden"})
    with pytest.raises(ValueError):
        assert_report_safe({"error": "request used super-secret"}, ("super-secret",))
    target = tmp_path / "report.json"
    write_report(str(target), {"status": "PASS", "entities": {"trace_id": 3}}, ("not-present",))
    assert json.loads(target.read_text())["status"] == "PASS"


def test_runner_source_never_logs_or_reports_runtime_key():
    source = (DEMO_DIR / "run_demo.py").read_text(encoding="utf-8")
    assert "print(self.key" not in source
    assert '"api_key": self.key' not in source
    assert "key_result.pop(\"key\")" in source
    assert "api-keys/{self.ids['api_key']}/revoke" in source


def test_required_scenarios_are_wired():
    source = (DEMO_DIR / "run_demo.py").read_text(encoding="utf-8")
    for method in ("self.normal", "self.security", "self.blocked_tool", "self.cost_limit", "self.error_trace", "self.evaluations", "self.dashboard_api"):
        assert method in source
    assert "self.approval(True)" in source
    assert "self.approval(False)" in source


def test_scenario_verifiers_use_run_scoped_fakes():
    detail = {
        "external_trace_id": "current-run", "risk_level": "HIGH", "total_cost": .5,
        "cost_records": [{"cost_usd": .5}],
        "spans": [
            {"id": 10, "name": "orchestrate", "input_data": {}},
            {"name": "retrieve", "parent_span_id": 10},
            {"name": "generate", "model_calls": [{"pricing_status": "PRICED"}]},
        ],
    }
    verification.normal_trace(detail, [{"event_type": "trace.finished", "external_trace_id": "current-run"}])
    security_detail = {"external_trace_id": "current-run", "risk_level": "HIGH", "spans": [{"input_data": {"contact": "[EMAIL_REDACTED]"}}]}
    findings = [{"finding_type": name} for name in ("pii_email", "bearer_token_detected", "prompt_injection")]
    verification.security(security_detail, findings, [{"event_type": "security.finding.created", "external_trace_id": "current-run"}], ("raw@example.test", "Bearer raw", "Ignore raw"))
    verification.blocked_side_effect([], {"status": "BLOCKED"}, "TOOL_BLOCKED")
    approved_detail = {"spans": [{"tool_calls": [{"approval_id": 41}]}]}
    verification.approval(["once"], {"status": "used"}, approved_detail, 41, True, "executed")
    verification.approval([], {"status": "rejected"}, {"spans": []}, 42, False, "rejected")
    verification.evaluation({"status": "COMPLETED", "total_cases": 2}, {"status": "COMPLETED"}, {"delta_pass_rate": 1, "improved_cases": [1, 2]})


def test_demo_help_does_not_require_docker():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "demo.py"), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--reset" in result.stdout and "--with-openai" in result.stdout and "--interactive-approval" in result.stdout
