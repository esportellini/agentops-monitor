"""
Evaluation tests.

Coverage:
- criar dataset
- adicionar caso
- executar run
- comparação exata (exact_match)
- estrutura JSON válida (json_structure)
- ferramenta esperada (expected_tools)
- limite de custo (cost_limit)
- limite de latência (latency_limit)
- presença de palavras (word_presence)
- revisão humana
- comparar dois runs
- isolamento por organização
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.evaluator import (
    MockProvider,
    ProviderContext,
    RunnerOutput,
    cost_limit,
    exact_match,
    expected_tools,
    json_structure,
    latency_limit,
    run_evaluators,
    word_presence,
)
from app.services.evaluation import (
    add_case,
    compare_runs,
    create_dataset,
    create_run,
    execute_run,
    get_dataset,
    list_datasets,
    submit_human_review,
)
from app.tests.factories import make_user_with_org, make_project, make_agent


# ── Evaluator unit tests (pure functions — no DB) ─────────────────────────────

def test_exact_match_pass():
    r = exact_match({}, {"answer": "yes"}, {"answer": "yes"}, {})
    assert r.passed
    assert r.score == 1.0


def test_exact_match_fail():
    r = exact_match({}, {"answer": "yes"}, {"answer": "no"}, {})
    assert not r.passed
    assert r.score == 0.0


def test_exact_match_field_subset():
    r = exact_match({}, {"a": 1, "b": 2}, {"a": 1, "b": 99}, {"fields": ["a"]})
    assert r.passed  # only field "a" compared


def test_exact_match_no_expected():
    r = exact_match({}, None, {"answer": "anything"}, {})
    assert r.passed  # no expectation → pass


def test_word_presence_all_found():
    r = word_presence({}, None, {"text": "The answer is yes and confirmed"}, {"keywords": ["yes", "confirmed"]})
    assert r.passed
    assert r.score == 1.0


def test_word_presence_missing():
    r = word_presence({}, None, {"text": "The answer is yes"}, {"keywords": ["yes", "confirmed"]})
    assert not r.passed
    assert r.score == 0.5


def test_word_presence_no_keywords():
    r = word_presence({}, None, {"text": "anything"}, {})
    assert r.passed


def test_json_structure_all_keys():
    r = json_structure({}, None, {"name": "x", "value": 1}, {"required_keys": ["name", "value"]})
    assert r.passed
    assert r.score == 1.0


def test_json_structure_missing_key():
    r = json_structure({}, None, {"name": "x"}, {"required_keys": ["name", "value"]})
    assert not r.passed
    assert r.score == 0.5
    assert "value" in r.detail["missing"]


def test_json_structure_no_output():
    r = json_structure({}, None, None, {"required_keys": ["name"]})
    assert not r.passed


def test_expected_tools_all_present():
    r = expected_tools({}, ["search", "summarize"], ["search", "summarize", "extra"], {})
    assert r.passed
    assert r.score == 1.0


def test_expected_tools_missing():
    r = expected_tools({}, ["search", "summarize"], ["search"], {})
    assert not r.passed
    assert r.score == 0.5
    assert "summarize" in r.detail["missing"]


def test_expected_tools_strict_no_unexpected():
    r = expected_tools({}, ["search"], ["search", "delete"], {"strict": True})
    assert not r.passed


def test_expected_tools_no_expected():
    r = expected_tools({}, None, ["any_tool"], {})
    assert r.passed


def test_cost_limit_pass():
    r = cost_limit(0.001, {"max_cost_usd": 0.01})
    assert r.passed


def test_cost_limit_fail():
    r = cost_limit(0.05, {"max_cost_usd": 0.01})
    assert not r.passed


def test_latency_limit_pass():
    r = latency_limit(200, {"max_latency_ms": 500})
    assert r.passed


def test_latency_limit_fail():
    r = latency_limit(1000, {"max_latency_ms": 500})
    assert not r.passed


# ── run_evaluators pipeline ───────────────────────────────────────────────────

def test_run_evaluators_all_pass():
    output = RunnerOutput(
        actual_output={"answer": "hello world", "name": "test"},
        actual_tools_used=["search"],
        latency_ms=100,
        cost=0.001,
    )
    passed, score, detail = run_evaluators(
        case_input={"q": "test"},
        expected_output={"answer": "hello world", "name": "test"},
        expected_tool_list=["search"],
        output=output,
        evaluator_configs=[
            {"name": "exact_match"},
            {"name": "expected_tools"},
            {"name": "cost_limit", "max_cost_usd": 0.01},
            {"name": "latency_limit", "max_latency_ms": 500},
        ],
    )
    assert passed
    assert score == 1.0


def test_run_evaluators_one_fails():
    output = RunnerOutput(
        actual_output={"answer": "wrong"},
        actual_tools_used=[],
        latency_ms=100,
        cost=0.001,
    )
    passed, score, detail = run_evaluators(
        case_input={},
        expected_output={"answer": "correct"},
        expected_tool_list=None,
        output=output,
        evaluator_configs=[{"name": "exact_match"}],
    )
    assert not passed
    assert score == 0.0


def test_run_evaluators_empty_list():
    output = RunnerOutput({}, [], 50, 0.0)
    passed, score, detail = run_evaluators({}, None, None, output, [])
    assert passed  # no evaluators → pass by default


# ── MockProvider ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mock_provider_returns_output():
    p = MockProvider()
    out = await p.run({"question": "hello"}, {}, ProviderContext(1, None))
    assert out.actual_output
    assert out.latency_ms > 0
    assert out.cost >= 0


@pytest.mark.asyncio
async def test_mock_provider_tools_called():
    p = MockProvider()
    out = await p.run({}, {"mock_tools_called": ["search", "summarize"]}, ProviderContext(1, None))
    assert "search" in out.actual_tools_used
    assert "summarize" in out.actual_tools_used


@pytest.mark.asyncio
async def test_mock_provider_output_override():
    p = MockProvider()
    out = await p.run({}, {"mock_output_override": {"answer": "overridden"}}, ProviderContext(1, None))
    assert out.actual_output["answer"] == "overridden"


# ── DB tests ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_dataset(db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="eval-ds@x.com", org_slug="eval-ds-org")
    await db.flush()

    ds = await create_dataset(db, org.id, {"name": "My Dataset", "version": "1.0.0"}, user_id=user.id)
    await db.flush()

    assert ds.id is not None
    assert ds.name == "My Dataset"
    assert ds.organization_id == org.id


@pytest.mark.asyncio
async def test_add_case(db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="eval-case@x.com", org_slug="eval-case-org")
    ds = await create_dataset(db, org.id, {"name": "DS"}, user_id=user.id)
    await db.flush()

    case = await add_case(db, ds.id, org.id, {
        "input_data": {"question": "What is 2+2?"},
        "expected_output": {"answer": "4"},
        "expected_tools": ["calculator"],
        "tags": ["math"],
    })
    await db.flush()

    assert case is not None
    assert case.input_data["question"] == "What is 2+2?"
    assert case.expected_tools == ["calculator"]


@pytest.mark.asyncio
async def test_add_case_wrong_org_returns_none(db: AsyncSession):
    _, org_a, _ = await make_user_with_org(db, email="eval-oa@x.com", org_slug="eval-org-a")
    _, org_b, _ = await make_user_with_org(db, email="eval-ob@x.com", org_slug="eval-org-b")
    ds = await create_dataset(db, org_a.id, {"name": "DS"})
    await db.flush()

    # Try to add case to org_a's dataset while claiming to be org_b
    result = await add_case(db, ds.id, org_b.id, {"input_data": {"q": "x"}})
    assert result is None  # org isolation enforced


@pytest.mark.asyncio
async def test_execute_run_mock(db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="eval-run@x.com", org_slug="eval-run-org")
    ds = await create_dataset(db, org.id, {"name": "Test DS"}, user_id=user.id)
    await db.flush()

    for i in range(3):
        await add_case(db, ds.id, org.id, {
            "input_data": {"q": f"question {i}"},
            "expected_output": {"provider": "mock"},
        })
    await db.flush()

    run = await create_run(db, org.id, {
        "dataset_id": ds.id,
        "name": "Test run",
        "provider": "mock",
        "config": {
            "evaluators": [
                {"name": "json_structure", "required_keys": ["answer", "provider"]},
                {"name": "cost_limit", "max_cost_usd": 1.0},
            ]
        },
    }, user_id=user.id)
    await db.flush()

    run = await execute_run(db, run)
    await db.flush()

    assert run.status.value == "COMPLETED"
    assert run.total_cases == 3
    assert run.total_cost is not None
    assert run.average_latency_ms is not None


@pytest.mark.asyncio
async def test_execute_run_exact_match(db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="eval-exact@x.com", org_slug="eval-exact-org")
    ds = await create_dataset(db, org.id, {"name": "Exact DS"})
    await db.flush()

    # Case where exact match should fail (mock doesn't return expected_output verbatim)
    await add_case(db, ds.id, org.id, {
        "input_data": {"q": "capital of France"},
        "expected_output": {"answer": "Paris"},
    })
    await db.flush()

    run = await create_run(db, org.id, {
        "dataset_id": ds.id,
        "name": "Exact match run",
        "provider": "mock",
        "config": {"evaluators": [{"name": "exact_match"}]},
    })
    await db.flush()

    run = await execute_run(db, run)
    await db.flush()

    # Mock doesn't return {"answer": "Paris"} so exact match fails
    assert run.status.value == "COMPLETED"
    assert run.passed_cases == 0  # exact match fails since mock echoes differently


@pytest.mark.asyncio
async def test_compare_runs(db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="eval-cmp@x.com", org_slug="eval-cmp-org")
    ds = await create_dataset(db, org.id, {"name": "Compare DS"})
    await db.flush()

    for i in range(4):
        await add_case(db, ds.id, org.id, {"input_data": {"q": f"q{i}"}})
    await db.flush()

    run_a = await create_run(db, org.id, {
        "dataset_id": ds.id, "name": "Run A", "provider": "mock",
        "config": {"evaluators": [{"name": "json_structure", "required_keys": []}]}
    })
    await db.flush()
    run_a = await execute_run(db, run_a)

    run_b = await create_run(db, org.id, {
        "dataset_id": ds.id, "name": "Run B", "provider": "mock",
        "config": {"evaluators": [{"name": "json_structure", "required_keys": []}]}
    })
    await db.flush()
    run_b = await execute_run(db, run_b)
    await db.flush()

    comparison = await compare_runs(db, run_a.id, run_b.id, org.id)

    assert "run_a" in comparison
    assert "run_b" in comparison
    assert comparison["shared_cases"] == 4
    assert "delta_pass_rate" in comparison
    assert "improved_cases" in comparison
    assert "regressed_cases" in comparison


@pytest.mark.asyncio
async def test_compare_runs_wrong_org(db: AsyncSession):
    _, org_a, _ = await make_user_with_org(db, email="cmp-oa@x.com", org_slug="cmp-org-a")
    _, org_b, _ = await make_user_with_org(db, email="cmp-ob@x.com", org_slug="cmp-org-b")
    ds_a = await create_dataset(db, org_a.id, {"name": "DS A"})
    await db.flush()

    run_a = await create_run(db, org_a.id, {"dataset_id": ds_a.id, "name": "R"})
    await db.flush()
    run_a = await execute_run(db, run_a)
    await db.flush()

    # org_b tries to compare org_a's run — must return error
    result = await compare_runs(db, run_a.id, run_a.id, org_b.id)
    assert "error" in result


@pytest.mark.asyncio
async def test_human_review(db: AsyncSession):
    user, org, _ = await make_user_with_org(db, email="eval-hr@x.com", org_slug="eval-hr-org")
    ds = await create_dataset(db, org.id, {"name": "HR DS"})
    await db.flush()

    await add_case(db, ds.id, org.id, {"input_data": {"q": "test"}})
    await db.flush()

    run = await create_run(db, org.id, {"dataset_id": ds.id, "name": "HR run", "provider": "mock",
                                        "config": {"evaluators": []}})
    await db.flush()
    run = await execute_run(db, run)
    await db.flush()

    assert run.results
    result_id = run.results[0].id

    reviewed = await submit_human_review(
        db, result_id, org.id,
        status="approved",
        note="Looks good",
        reviewer_id=user.id,
    )
    await db.flush()

    assert reviewed is not None
    assert reviewed.human_review_status == "approved"
    assert reviewed.human_review_note == "Looks good"
    assert reviewed.reviewed_by_id == user.id
    assert reviewed.reviewed_at is not None


@pytest.mark.asyncio
async def test_human_review_wrong_status(db: AsyncSession):
    _, org, _ = await make_user_with_org(db, email="eval-hrbad@x.com", org_slug="eval-hrbad-org")
    with pytest.raises(ValueError, match="Invalid review status"):
        await submit_human_review(db, 999, org.id, "invalid_status", None, None)
