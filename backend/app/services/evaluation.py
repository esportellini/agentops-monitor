"""
Evaluation service: CRUD for datasets/cases/runs, run execution, comparison.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import EvaluationStatus
from app.models.evaluation import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)
from app.services.evaluator import DEFAULT_EVALUATORS, get_provider, run_evaluators


# ── Datasets ──────────────────────────────────────────────────────────────────

async def list_datasets(db: AsyncSession, organization_id: int) -> list[EvaluationDataset]:
    r = await db.execute(
        select(EvaluationDataset)
        .where(EvaluationDataset.organization_id == organization_id)
        .order_by(EvaluationDataset.created_at.desc())
    )
    return list(r.scalars().all())


async def get_dataset(db: AsyncSession, dataset_id: int, organization_id: int) -> EvaluationDataset | None:
    r = await db.execute(
        select(EvaluationDataset)
        .where(EvaluationDataset.id == dataset_id, EvaluationDataset.organization_id == organization_id)
        .options(selectinload(EvaluationDataset.cases))
    )
    return r.scalar_one_or_none()


async def create_dataset(db: AsyncSession, organization_id: int, data: dict, user_id: int | None = None) -> EvaluationDataset:
    ds = EvaluationDataset(
        organization_id=organization_id,
        project_id=data.get("project_id"),
        created_by_id=user_id,
        name=data["name"],
        description=data.get("description"),
        version=data.get("version", "1.0.0"),
        tags=data.get("tags"),
    )
    db.add(ds)
    await db.flush()
    return ds


async def add_case(db: AsyncSession, dataset_id: int, organization_id: int, data: dict) -> EvaluationCase | None:
    ds = await db.execute(
        select(EvaluationDataset).where(
            EvaluationDataset.id == dataset_id,
            EvaluationDataset.organization_id == organization_id,
        )
    )
    if ds.scalar_one_or_none() is None:
        return None

    case = EvaluationCase(
        dataset_id=dataset_id,
        input_data=data["input_data"],
        expected_output=data.get("expected_output"),
        expected_tools=data.get("expected_tools"),
        tags=data.get("tags"),
        metadata_=data.get("metadata"),
    )
    db.add(case)
    await db.flush()
    return case


# ── Runs ──────────────────────────────────────────────────────────────────────

async def list_runs(
    db: AsyncSession,
    organization_id: int,
    dataset_id: int | None = None,
    agent_id: int | None = None,
    limit: int = 50,
) -> list[EvaluationRun]:
    q = select(EvaluationRun).where(EvaluationRun.organization_id == organization_id)
    if dataset_id:
        q = q.where(EvaluationRun.dataset_id == dataset_id)
    if agent_id:
        q = q.where(EvaluationRun.agent_id == agent_id)
    r = await db.execute(q.order_by(EvaluationRun.created_at.desc()).limit(limit))
    return list(r.scalars().all())


async def get_run(db: AsyncSession, run_id: int, organization_id: int) -> EvaluationRun | None:
    r = await db.execute(
        select(EvaluationRun)
        .where(EvaluationRun.id == run_id, EvaluationRun.organization_id == organization_id)
        .options(selectinload(EvaluationRun.results).selectinload(EvaluationResult.case))
    )
    return r.scalar_one_or_none()


async def create_run(db: AsyncSession, organization_id: int, data: dict, user_id: int | None = None) -> EvaluationRun:
    run = EvaluationRun(
        organization_id=organization_id,
        dataset_id=data["dataset_id"],
        agent_id=data.get("agent_id"),
        triggered_by_id=user_id,
        name=data.get("name", "Evaluation run"),
        agent_version=data.get("agent_version"),
        provider=data.get("provider", "mock"),
        model=data.get("model"),
        prompt_version=data.get("prompt_version"),
        status=EvaluationStatus.PENDING,
        config=data.get("config"),
    )
    db.add(run)
    await db.flush()
    return run


async def execute_run(db: AsyncSession, run: EvaluationRun) -> EvaluationRun:
    """
    Execute all cases in the dataset synchronously.
    Uses the configured provider (default: mock).
    """
    # Load cases
    cases_r = await db.execute(
        select(EvaluationCase).where(EvaluationCase.dataset_id == run.dataset_id)
    )
    cases = list(cases_r.scalars().all())

    run.status = EvaluationStatus.RUNNING
    run.started_at = datetime.now(timezone.utc)
    run.total_cases = len(cases)
    await db.flush()

    cfg = run.config or {}
    evaluator_cfgs = cfg.get("evaluators", DEFAULT_EVALUATORS)
    provider_name = run.provider or "mock"

    try:
        provider = get_provider(provider_name)
    except ValueError:
        run.status = EvaluationStatus.FAILED
        await db.flush()
        return run

    total_cost = 0.0
    total_latency = 0
    passed_count = 0
    total_score = 0.0

    for case in cases:
        output = provider.run(case.input_data, cfg)

        passed, score, detail = run_evaluators(
            case_input=case.input_data,
            expected_output=case.expected_output,
            expected_tool_list=case.expected_tools,
            output=output,
            evaluator_configs=evaluator_cfgs,
        )

        result = EvaluationResult(
            run_id=run.id,
            case_id=case.id,
            actual_output=output.actual_output if not output.error else None,
            actual_tools_used=output.actual_tools_used,
            passed=passed,
            score=score,
            latency_ms=output.latency_ms,
            cost=output.cost,
            evaluator_details=detail,
            error=output.error,
        )
        db.add(result)

        if not output.error:
            total_cost += output.cost
            total_latency += output.latency_ms
            if passed:
                passed_count += 1
            total_score += score

    n = len(cases)
    run.status = EvaluationStatus.COMPLETED
    run.ended_at = datetime.now(timezone.utc)
    run.total_cost = total_cost
    run.average_latency_ms = total_latency / n if n else None
    run.pass_rate = passed_count / n if n else None
    run.average_score = total_score / n if n else None
    run.passed_cases = passed_count

    await db.flush()
    await db.refresh(run, ["results"])
    return run


# ── Comparison ────────────────────────────────────────────────────────────────

async def compare_runs(
    db: AsyncSession,
    run_id_a: int,
    run_id_b: int,
    organization_id: int,
) -> dict:
    """
    Compare two runs side by side.
    Returns metrics diff, improved cases, regressed cases.
    """
    run_a = await get_run(db, run_id_a, organization_id)
    run_b = await get_run(db, run_id_b, organization_id)

    if run_a is None or run_b is None:
        return {"error": "One or both runs not found"}

    # Build case_id → result map for each run
    def case_map(run: EvaluationRun) -> dict[int, EvaluationResult]:
        return {r.case_id: r for r in run.results}

    map_a = case_map(run_a)
    map_b = case_map(run_b)
    shared_ids = set(map_a) & set(map_b)

    improved = []   # B passed, A failed
    regressed = []  # A passed, B failed
    both_pass = 0
    both_fail = 0

    for cid in shared_ids:
        ra = map_a[cid]
        rb = map_b[cid]
        if ra.passed and not rb.passed:
            regressed.append(cid)
        elif not ra.passed and rb.passed:
            improved.append(cid)
        elif ra.passed and rb.passed:
            both_pass += 1
        else:
            both_fail += 1

    def run_summary(run: EvaluationRun) -> dict:
        return {
            "id": run.id,
            "name": run.name,
            "provider": run.provider,
            "model": run.model,
            "agent_version": run.agent_version,
            "prompt_version": run.prompt_version,
            "pass_rate": run.pass_rate,
            "average_score": run.average_score,
            "total_cost": run.total_cost,
            "average_latency_ms": run.average_latency_ms,
            "total_cases": run.total_cases,
            "passed_cases": run.passed_cases,
        }

    return {
        "run_a": run_summary(run_a),
        "run_b": run_summary(run_b),
        "shared_cases": len(shared_ids),
        "improved_cases": improved,    # case IDs where B is better
        "regressed_cases": regressed,  # case IDs where A was better
        "both_pass": both_pass,
        "both_fail": both_fail,
        "delta_pass_rate": (run_b.pass_rate or 0) - (run_a.pass_rate or 0),
        "delta_score": (run_b.average_score or 0) - (run_a.average_score or 0),
        "delta_cost": (run_b.total_cost or 0) - (run_a.total_cost or 0),
        "delta_latency_ms": (run_b.average_latency_ms or 0) - (run_a.average_latency_ms or 0),
    }


# ── Human review ──────────────────────────────────────────────────────────────

async def submit_human_review(
    db: AsyncSession,
    result_id: int,
    organization_id: int,
    status: str,
    note: str | None,
    reviewer_id: int | None,
) -> EvaluationResult | None:
    if status not in ("approved", "rejected", "needs_review"):
        raise ValueError(f"Invalid review status: {status}")

    r = await db.execute(
        select(EvaluationResult)
        .join(EvaluationRun, EvaluationRun.id == EvaluationResult.run_id)
        .where(EvaluationResult.id == result_id, EvaluationRun.organization_id == organization_id)
    )
    result = r.scalar_one_or_none()
    if result is None:
        return None

    result.human_review_status = status
    result.human_review_note = note
    result.reviewed_by_id = reviewer_id
    result.reviewed_at = datetime.now(timezone.utc)
    return result
