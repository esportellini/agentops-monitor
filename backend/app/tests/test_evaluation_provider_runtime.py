import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import EvaluationResult
from app.models.pricing import ModelPricing
from app.services.evaluation import compare_runs, create_dataset, create_run, execute_run
from app.services.evaluator import (
    MOCK,
    PRICED,
    UNPRICED,
    OpenAIProvider,
    ProviderContext,
    ProviderRunError,
    RunnerOutput,
    provider_availability,
    validate_evaluator_configs,
)
from app.tests.factories import make_agent, make_project, make_user_with_org


class FakeResponses:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        value = self.outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def fake_response(text: str, input_tokens: int = 10, output_tokens: int = 2):
    return SimpleNamespace(
        output_text=text,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


@pytest.mark.asyncio
async def test_openai_provider_text_json_usage_and_no_tools():
    responses = FakeResponses([fake_response("Paris"), fake_response('{"decision":"allow"}')])
    provider = OpenAIProvider(client=SimpleNamespace(responses=responses))
    context = ProviderContext(organization_id=1, model="configured-model")

    text = await provider.run({"question": "capital?"}, {"instructions": "Be concise"}, context)
    structured = await provider.run({"decision": "?"}, {"output_mode": "json"}, context)

    assert text.actual_output == {"text": "Paris"}
    assert structured.actual_output == {"decision": "allow"}
    assert text.input_tokens == 10 and text.output_tokens == 2
    assert json.loads(responses.calls[0]["input"]) == {"question": "capital?"}
    assert "tools" not in responses.calls[0]
    assert responses.calls[0]["store"] is False
    assert responses.calls[0]["instructions"] == "Be concise"


@pytest.mark.asyncio
async def test_openai_invalid_json_is_safe_case_error():
    provider = OpenAIProvider(client=SimpleNamespace(responses=FakeResponses([fake_response("not json")])))
    out = await provider.run({}, {"output_mode": "json"}, ProviderContext(1, "model"))
    assert out.error == "Provider returned invalid JSON"
    assert out.actual_output == {}


@pytest.mark.asyncio
async def test_openai_auth_and_model_errors_are_safe_run_errors():
    class AuthenticationError(Exception):
        status_code = 401

    class BadRequestError(Exception):
        status_code = 400

    for exc, message in [
        (AuthenticationError("secret request dump"), "Provider authentication failed"),
        (BadRequestError("raw request"), "Provider rejected model or request"),
    ]:
        provider = OpenAIProvider(client=SimpleNamespace(responses=FakeResponses([exc])))
        with pytest.raises(ProviderRunError, match=message):
            await provider.run({}, {}, ProviderContext(1, "model"))


@pytest.mark.asyncio
async def test_openai_timeout_is_a_safe_case_error():
    class APITimeoutError(Exception):
        pass
    provider = OpenAIProvider(client=SimpleNamespace(responses=FakeResponses([APITimeoutError("raw request")])))
    output = await provider.run({}, {}, ProviderContext(1, "model"))
    assert output.error == "Provider request timed out"
    assert output.pricing_status == "ERROR"


def test_evaluator_config_validation_and_unknown_evaluator():
    with pytest.raises(ValueError, match="Unknown evaluator"):
        validate_evaluator_configs([{"name": "mystery"}])
    with pytest.raises(ValueError, match="fields"):
        validate_evaluator_configs([{"name": "exact_match", "fields": "text"}])
    with pytest.raises(ValueError, match="max_cost_usd"):
        validate_evaluator_configs([{"name": "cost_limit", "max_cost_usd": -1}])


@pytest.mark.asyncio
async def test_run_config_rejects_nested_provider_credentials(db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="eval-secret@x.com", org_slug="eval-secret")
    dataset = await create_dataset(db, org.id, {"name": "secret"})
    with pytest.raises(ValueError, match="credentials"):
        await create_run(db, org.id, {
            "dataset_id": dataset.id,
            "config": {"mock_output_override": {"OPENAI_API_KEY": "must-not-persist"}},
        })


def test_unpriced_cost_limit_is_not_reported_as_passed():
    from app.services.evaluator import cost_limit
    result = cost_limit(None, {"max_cost_usd": 1}, UNPRICED)
    assert not result.passed
    assert result.detail["indeterminate"] is True


def test_result_has_run_case_unique_constraint():
    constraints = {constraint.name for constraint in EvaluationResult.__table__.constraints}
    assert "uq_evaluation_result_run_case" in constraints


@pytest.mark.asyncio
async def test_dataset_project_and_run_agent_tenant_isolation(db: AsyncSession):
    _, org_a, _ = await make_user_with_org(db, email="eval-iso-a@x.com", org_slug="eval-iso-a")
    _, org_b, _ = await make_user_with_org(db, email="eval-iso-b@x.com", org_slug="eval-iso-b")
    project_a = await make_project(db, org_a, slug="eval-pa")
    project_b = await make_project(db, org_b, slug="eval-pb")
    agent_b = await make_agent(db, project_b, slug="eval-ab")

    with pytest.raises(ValueError, match="Project not found"):
        await create_dataset(db, org_a.id, {"name": "bad", "project_id": project_b.id})

    dataset = await create_dataset(db, org_a.id, {"name": "A", "project_id": project_a.id})
    with pytest.raises(ValueError, match="Agent not found"):
        await create_run(db, org_a.id, {"dataset_id": dataset.id, "agent_id": agent_b.id})
    with pytest.raises(ValueError, match="Dataset not found"):
        await create_run(db, org_b.id, {"dataset_id": dataset.id})

    project_a_other = await make_project(db, org_a, slug="eval-pa-other")
    agent_a_other = await make_agent(db, project_a_other, slug="eval-aa-other")
    with pytest.raises(ValueError, match="dataset project"):
        await create_run(db, org_a.id, {"dataset_id": dataset.id, "agent_id": agent_a_other.id})


@pytest.mark.asyncio
async def test_external_consent_and_model_are_required_only_for_openai(db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="eval-consent@x.com", org_slug="eval-consent")
    dataset = await create_dataset(db, org.id, {"name": "consent"})
    await create_run(db, org.id, {"dataset_id": dataset.id, "provider": "mock"})
    with pytest.raises(ValueError, match="model is required"):
        await create_run(db, org.id, {"dataset_id": dataset.id, "provider": "openai", "config": {"allow_external_provider_data": True}})
    with pytest.raises(ValueError, match="Explicit consent"):
        await create_run(db, org.id, {"dataset_id": dataset.id, "provider": "openai", "model": "model"})


@pytest.mark.asyncio
async def test_missing_openai_key_marks_run_failed_without_fallback(db: AsyncSession, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "openai_api_key", None)
    _, org, _ = await make_user_with_org(db, email="eval-no-key@x.com", org_slug="eval-no-key")
    dataset = await create_dataset(db, org.id, {"name": "no key"})
    run = await create_run(db, org.id, {
        "dataset_id": dataset.id, "provider": "openai", "model": "model",
        "config": {"allow_external_provider_data": True},
    })
    await execute_run(db, run)
    assert run.status.value == "FAILED"
    assert run.failure_reason == "OpenAI provider is not configured"
    assert run.executed_cases is None


def test_provider_availability_does_not_expose_key(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "openai_api_key", "sensitive-value")
    payload = provider_availability()
    assert payload[1] == {"id": "openai", "available": True}
    assert "sensitive-value" not in repr(payload)


@pytest.mark.asyncio
async def test_execute_openai_authoritative_pricing_and_idempotency(db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="eval-priced@x.com", org_slug="eval-priced")
    pricing = ModelPricing(
        organization_id=org.id,
        provider="openai",
        model="priced-model",
        input_price_per_million=Decimal("2"),
        output_price_per_million=Decimal("6"),
        effective_from=datetime.now(timezone.utc),
        active=True,
    )
    db.add(pricing)
    dataset = await create_dataset(db, org.id, {"name": "priced"})
    from app.services.evaluation import add_case
    await add_case(db, dataset.id, org.id, {"input_data": {"q": "x"}, "expected_output": {"text": "ok"}})
    run = await create_run(db, org.id, {
        "dataset_id": dataset.id,
        "provider": "openai",
        "model": "priced-model",
        "config": {"allow_external_provider_data": True, "evaluators": [{"name": "exact_match", "fields": ["text"]}]},
    })
    await db.flush()
    responses = FakeResponses([fake_response("ok", 1_000_000, 500_000)])
    provider = OpenAIProvider(client=SimpleNamespace(responses=responses))

    await execute_run(db, run, provider_override=provider)
    assert run.total_cost == pytest.approx(5.0)
    assert run.unpriced_cases == 0
    result = (await db.execute(select(EvaluationResult).where(EvaluationResult.run_id == run.id))).scalar_one()
    assert result.pricing_status == PRICED
    assert Decimal(str(result.cost)) == Decimal("5.0")
    assert result.pricing_id == pricing.id
    assert result.input_tokens == 1_000_000
    with pytest.raises(ValueError, match="already been executed"):
        await execute_run(db, run, provider_override=provider)
    assert len(responses.calls) == 1


@pytest.mark.asyncio
async def test_unknown_and_zero_pricing_are_distinct(db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="eval-zero@x.com", org_slug="eval-zero")
    db.add(ModelPricing(
        organization_id=org.id, provider="openai", model="free-model",
        input_price_per_million=Decimal("0"), output_price_per_million=Decimal("0"), active=True,
        effective_from=datetime.now(timezone.utc),
    ))
    from app.services.evaluation import add_case
    for model in ("unknown-model", "free-model"):
        dataset = await create_dataset(db, org.id, {"name": model})
        await add_case(db, dataset.id, org.id, {"input_data": {"model": model}})
        run = await create_run(db, org.id, {
            "dataset_id": dataset.id, "provider": "openai", "model": model,
            "config": {"allow_external_provider_data": True, "evaluators": []},
        })
        await execute_run(
            db, run,
            provider_override=OpenAIProvider(client=SimpleNamespace(responses=FakeResponses([fake_response("ok")]))),
        )
        result = run.results[0]
        if model == "unknown-model":
            assert result.pricing_status == UNPRICED and result.cost is None
            assert run.unpriced_cases == 1
        else:
            assert result.pricing_status == PRICED and result.cost == 0
            assert run.unpriced_cases == 0


@pytest.mark.asyncio
async def test_per_case_errors_continue_and_aggregate(db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="eval-errors@x.com", org_slug="eval-errors")
    dataset = await create_dataset(db, org.id, {"name": "errors"})
    from app.services.evaluation import add_case
    for i in range(3):
        await add_case(db, dataset.id, org.id, {"input_data": {"i": i}})
    run = await create_run(db, org.id, {
        "dataset_id": dataset.id, "provider": "openai", "model": "unknown",
        "config": {"allow_external_provider_data": True, "evaluators": []},
    })

    class MixedProvider:
        name = "openai"
        calls = 0
        async def run(self, case_input, config, context):
            self.calls += 1
            if self.calls == 2:
                return RunnerOutput({}, [], 30, error="Provider request timed out")
            return RunnerOutput({"text": "ok"}, [], 20, input_tokens=1, output_tokens=1)

    provider = MixedProvider()
    await execute_run(db, run, provider_override=provider)
    assert run.status.value == "COMPLETED"
    assert len(run.results) == 3
    assert run.error_cases == 1
    assert run.pass_rate == pytest.approx(2 / 3)
    assert provider.calls == 3


@pytest.mark.asyncio
async def test_compare_rejects_different_datasets(db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="eval-compare-ds@x.com", org_slug="eval-compare-ds")
    first = await create_dataset(db, org.id, {"name": "first"})
    second = await create_dataset(db, org.id, {"name": "second"})
    run_a = await create_run(db, org.id, {"dataset_id": first.id})
    run_b = await create_run(db, org.id, {"dataset_id": second.id})
    result = await compare_runs(db, run_a.id, run_b.id, org.id)
    assert result["error"] == "Runs must use the same dataset"


def test_pricing_status_constants_are_explicit():
    assert {MOCK, PRICED, UNPRICED} == {"MOCK", "PRICED", "UNPRICED"}
