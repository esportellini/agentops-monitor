"""Tenant-scoped evaluation CRUD, provider execution, comparison, and review."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import EvaluationStatus
from app.models.evaluation import EvaluationCase, EvaluationDataset, EvaluationResult, EvaluationRun
from app.models.project import Agent, Project
from app.services import audit
from app.services.evaluator import (
    DEFAULT_EVALUATORS,
    ERROR,
    MOCK,
    PRICED,
    UNPRICED,
    EvaluationProvider,
    ProviderContext,
    ProviderRunError,
    RunnerOutput,
    get_provider,
    run_evaluators,
    validate_evaluator_configs,
)
from app.services.pricing import resolve_model_call_pricing


async def list_datasets(db: AsyncSession, organization_id: int) -> list[EvaluationDataset]:
    result = await db.execute(
        select(EvaluationDataset).where(EvaluationDataset.organization_id == organization_id).order_by(EvaluationDataset.created_at.desc())
    )
    return list(result.scalars().all())


async def get_dataset(db: AsyncSession, dataset_id: int, organization_id: int) -> EvaluationDataset | None:
    result = await db.execute(
        select(EvaluationDataset)
        .where(EvaluationDataset.id == dataset_id, EvaluationDataset.organization_id == organization_id)
        .options(selectinload(EvaluationDataset.cases))
    )
    return result.scalar_one_or_none()


async def create_dataset(db: AsyncSession, organization_id: int, data: dict, user_id: int | None = None) -> EvaluationDataset:
    project_id = data.get("project_id")
    if project_id is not None:
        project = (await db.execute(
            select(Project).where(Project.id == project_id, Project.organization_id == organization_id)
        )).scalar_one_or_none()
        if project is None:
            raise ValueError("Project not found in this organization")
    dataset = EvaluationDataset(
        organization_id=organization_id,
        project_id=project_id,
        created_by_id=user_id,
        name=data["name"],
        description=data.get("description"),
        version=data.get("version", "1.0.0"),
        tags=data.get("tags"),
    )
    db.add(dataset)
    await db.flush()
    await audit.write(
        db, organization_id=organization_id, user_id=user_id,
        event_type="evaluation.dataset.created", message="Evaluation dataset created",
        entity_type="evaluation_dataset", entity_id=str(dataset.id),
        after_data={"project_id": project_id, "version": dataset.version},
    )
    return dataset


async def add_case(db: AsyncSession, dataset_id: int, organization_id: int, data: dict) -> EvaluationCase | None:
    dataset = (await db.execute(
        select(EvaluationDataset).where(EvaluationDataset.id == dataset_id, EvaluationDataset.organization_id == organization_id)
    )).scalar_one_or_none()
    if dataset is None:
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


async def list_runs(db: AsyncSession, organization_id: int, dataset_id: int | None = None, agent_id: int | None = None, limit: int = 50) -> list[EvaluationRun]:
    query = select(EvaluationRun).where(EvaluationRun.organization_id == organization_id)
    if dataset_id is not None:
        query = query.where(EvaluationRun.dataset_id == dataset_id)
    if agent_id is not None:
        query = query.where(EvaluationRun.agent_id == agent_id)
    result = await db.execute(query.order_by(EvaluationRun.created_at.desc()).limit(limit))
    return list(result.scalars().all())


async def get_run(db: AsyncSession, run_id: int, organization_id: int) -> EvaluationRun | None:
    result = await db.execute(
        select(EvaluationRun)
        .where(EvaluationRun.id == run_id, EvaluationRun.organization_id == organization_id)
        .options(selectinload(EvaluationRun.results).selectinload(EvaluationResult.case))
    )
    return result.scalar_one_or_none()


def _validate_run_config(provider: str, model: str | None, config: dict) -> list[dict]:
    if provider not in {"mock", "openai"}:
        raise ValueError("provider must be mock or openai")
    forbidden = {"api_key", "openai_api_key"}

    def contains_credentials(value: Any) -> bool:
        if isinstance(value, dict):
            return any(str(key).lower() in forbidden or contains_credentials(item) for key, item in value.items())
        if isinstance(value, list):
            return any(contains_credentials(item) for item in value)
        return False

    if contains_credentials(config):
        raise ValueError("Provider credentials cannot be supplied in run config")
    output_mode = config.get("output_mode", "text")
    if output_mode not in {"text", "json"}:
        raise ValueError("output_mode must be text or json")
    instructions = config.get("instructions")
    if instructions is not None and (not isinstance(instructions, str) or len(instructions) > 20_000):
        raise ValueError("instructions must be a string of at most 20000 characters")
    if provider == "openai":
        if not model or not model.strip():
            raise ValueError("model is required for OpenAI evaluation runs")
        if config.get("allow_external_provider_data") is not True:
            raise ValueError("Explicit consent is required to send dataset inputs to OpenAI")
    evaluator_configs = config.get("evaluators", DEFAULT_EVALUATORS)
    return validate_evaluator_configs(evaluator_configs)


async def create_run(db: AsyncSession, organization_id: int, data: dict, user_id: int | None = None) -> EvaluationRun:
    dataset = (await db.execute(
        select(EvaluationDataset).where(
            EvaluationDataset.id == data["dataset_id"],
            EvaluationDataset.organization_id == organization_id,
        )
    )).scalar_one_or_none()
    if dataset is None:
        raise ValueError("Dataset not found in this organization")

    agent_id = data.get("agent_id")
    if agent_id is not None:
        agent = (await db.execute(
            select(Agent).join(Project, Project.id == Agent.project_id).where(
                Agent.id == agent_id, Project.organization_id == organization_id,
            )
        )).scalar_one_or_none()
        if agent is None:
            raise ValueError("Agent not found in this organization")
        if dataset.project_id is not None and agent.project_id != dataset.project_id:
            raise ValueError("Agent must belong to the dataset project")

    provider = data.get("provider") or "mock"
    model = data.get("model")
    config = data.get("config") or {}
    _validate_run_config(provider, model, config)
    run = EvaluationRun(
        organization_id=organization_id,
        dataset_id=dataset.id,
        agent_id=agent_id,
        triggered_by_id=user_id,
        name=data.get("name") or "Evaluation run",
        agent_version=data.get("agent_version"),
        provider=provider,
        model=model,
        provider_api="responses" if provider == "openai" else "mock",
        prompt_version=data.get("prompt_version"),
        status=EvaluationStatus.PENDING,
        config=config,
    )
    db.add(run)
    await db.flush()
    await audit.write(
        db, organization_id=organization_id, user_id=user_id,
        event_type="evaluation.run.created", message="Evaluation run created",
        entity_type="evaluation_run", entity_id=str(run.id),
        after_data={"dataset_id": dataset.id, "agent_id": agent_id, "provider": provider, "model": model},
    )
    return run


async def _fail_run(db: AsyncSession, run: EvaluationRun, reason: str) -> EvaluationRun:
    run.status = EvaluationStatus.FAILED
    run.failure_reason = reason
    run.ended_at = datetime.now(timezone.utc)
    await audit.write(
        db, organization_id=run.organization_id, user_id=run.triggered_by_id,
        event_type="evaluation.run.failed", message=reason,
        entity_type="evaluation_run", entity_id=str(run.id),
        after_data={"provider": run.provider, "model": run.model},
    )
    await db.flush()
    return run


async def execute_run(db: AsyncSession, run: EvaluationRun, provider_override: EvaluationProvider | None = None) -> EvaluationRun:
    if run.status != EvaluationStatus.PENDING:
        raise ValueError("Evaluation run has already been executed")

    dataset = (await db.execute(
        select(EvaluationDataset).where(
            EvaluationDataset.id == run.dataset_id,
            EvaluationDataset.organization_id == run.organization_id,
        )
    )).scalar_one_or_none()
    if dataset is None:
        return await _fail_run(db, run, "Dataset is not accessible")
    config = run.config or {}
    try:
        evaluator_configs = _validate_run_config(run.provider or "mock", run.model, config)
        provider = provider_override or get_provider(run.provider or "mock")
    except (ValueError, ProviderRunError) as exc:
        return await _fail_run(db, run, str(exc))

    cases = list((await db.execute(
        select(EvaluationCase).where(EvaluationCase.dataset_id == dataset.id).order_by(EvaluationCase.id)
    )).scalars().all())
    run.status = EvaluationStatus.RUNNING
    run.started_at = datetime.now(timezone.utc)
    run.total_cases = len(cases)
    run.executed_cases = 0
    run.error_cases = 0
    run.unpriced_cases = 0
    await audit.write(
        db, organization_id=run.organization_id, user_id=run.triggered_by_id,
        event_type="evaluation.run.started", message="Evaluation run started",
        entity_type="evaluation_run", entity_id=str(run.id),
        after_data={"total_cases": len(cases), "provider": run.provider, "model": run.model},
    )
    await db.flush()

    known_cost = Decimal("0")
    latencies: list[int] = []
    scores: list[float] = []
    passed_count = 0
    context = ProviderContext(run.organization_id, run.model)

    for case in cases:
        try:
            output = await provider.run(case.input_data, config, context)
        except ProviderRunError as exc:
            return await _fail_run(db, run, str(exc))
        except Exception:
            output = RunnerOutput({}, [], None, error="Provider execution failed", pricing_status=ERROR)

        pricing_id = None
        input_price = None
        output_price = None
        if not output.error and (run.provider or "mock") == "openai":
            if output.input_tokens is None or output.output_tokens is None:
                output.pricing_status = UNPRICED
                output.cost = None
            else:
                resolution = await resolve_model_call_pricing(
                    db,
                    organization_id=run.organization_id,
                    provider="openai",
                    model=run.model or "",
                    input_tokens=output.input_tokens,
                    output_tokens=output.output_tokens,
                    at=datetime.now(timezone.utc),
                )
                output.pricing_status = resolution.status
                output.cost = resolution.cost_usd
                if resolution.pricing is not None:
                    pricing_id = resolution.pricing.id
                    input_price = resolution.pricing.input_price_per_million
                    output_price = resolution.pricing.output_price_per_million
        elif output.error:
            output.pricing_status = ERROR
            output.cost = None
        else:
            output.pricing_status = MOCK

        if output.error:
            passed, score, details = False, None, {"provider": {"passed": False, "reason": output.error}}
            run.error_cases += 1
        else:
            passed, score, details = run_evaluators(
                case.input_data, case.expected_output, case.expected_tools, output, evaluator_configs
            )
            scores.append(score)
            if passed:
                passed_count += 1
            if output.pricing_status == UNPRICED:
                run.unpriced_cases += 1
            elif output.cost is not None:
                known_cost += Decimal(str(output.cost))

        if output.latency_ms is not None:
            latencies.append(output.latency_ms)
        db.add(EvaluationResult(
            run_id=run.id,
            case_id=case.id,
            actual_output=output.actual_output if not output.error else None,
            actual_tools_used=output.actual_tools_used,
            passed=passed,
            score=score,
            latency_ms=output.latency_ms,
            cost=float(output.cost) if output.cost is not None else None,
            input_tokens=output.input_tokens,
            output_tokens=output.output_tokens,
            pricing_status=output.pricing_status,
            pricing_id=pricing_id,
            input_price_per_million=input_price,
            output_price_per_million=output_price,
            evaluator_details=details,
            error=output.error,
        ))
        run.executed_cases += 1
        await db.flush()

    run.status = EvaluationStatus.COMPLETED
    run.ended_at = datetime.now(timezone.utc)
    run.total_cost = float(known_cost)
    run.average_latency_ms = sum(latencies) / len(latencies) if latencies else None
    run.pass_rate = passed_count / len(cases) if cases else None
    run.average_score = sum(scores) / len(scores) if scores else None
    run.passed_cases = passed_count
    await audit.write(
        db, organization_id=run.organization_id, user_id=run.triggered_by_id,
        event_type="evaluation.run.completed", message="Evaluation run completed",
        entity_type="evaluation_run", entity_id=str(run.id),
        after_data={
            "total_cases": run.total_cases, "passed_cases": passed_count,
            "error_cases": run.error_cases, "unpriced_cases": run.unpriced_cases,
        },
    )
    await db.flush()
    await db.refresh(run, ["results"])
    return run


async def compare_runs(db: AsyncSession, run_id_a: int, run_id_b: int, organization_id: int) -> dict:
    run_a = await get_run(db, run_id_a, organization_id)
    run_b = await get_run(db, run_id_b, organization_id)
    if run_a is None or run_b is None:
        return {"error": "One or both runs not found", "error_code": "not_found"}
    if run_a.dataset_id != run_b.dataset_id:
        return {"error": "Runs must use the same dataset", "error_code": "different_dataset"}
    map_a = {result.case_id: result for result in run_a.results}
    map_b = {result.case_id: result for result in run_b.results}
    shared_ids = set(map_a) & set(map_b)
    improved, regressed = [], []
    both_pass = both_fail = 0
    for case_id in shared_ids:
        first, second = map_a[case_id], map_b[case_id]
        if first.passed and not second.passed:
            regressed.append(case_id)
        elif not first.passed and second.passed:
            improved.append(case_id)
        elif first.passed and second.passed:
            both_pass += 1
        else:
            both_fail += 1

    def summary(item: EvaluationRun) -> dict:
        return {
            "id": item.id, "name": item.name, "provider": item.provider, "model": item.model,
            "agent_version": item.agent_version, "prompt_version": item.prompt_version,
            "pass_rate": item.pass_rate, "average_score": item.average_score,
            "total_cost": item.total_cost, "average_latency_ms": item.average_latency_ms,
            "total_cases": item.total_cases, "passed_cases": item.passed_cases,
            "error_cases": item.error_cases, "unpriced_cases": item.unpriced_cases,
        }

    cost_complete = not (run_a.unpriced_cases or run_b.unpriced_cases)
    return {
        "run_a": summary(run_a), "run_b": summary(run_b), "shared_cases": len(shared_ids),
        "improved_cases": sorted(improved), "regressed_cases": sorted(regressed),
        "both_pass": both_pass, "both_fail": both_fail,
        "delta_pass_rate": (run_b.pass_rate or 0) - (run_a.pass_rate or 0),
        "delta_score": (run_b.average_score or 0) - (run_a.average_score or 0),
        "delta_cost": (run_b.total_cost or 0) - (run_a.total_cost or 0),
        "delta_latency_ms": (run_b.average_latency_ms or 0) - (run_a.average_latency_ms or 0),
        "cost_comparison_complete": cost_complete,
    }


async def submit_human_review(db: AsyncSession, result_id: int, organization_id: int, status: str, note: str | None, reviewer_id: int | None) -> EvaluationResult | None:
    if status not in {"approved", "rejected", "needs_review"}:
        raise ValueError(f"Invalid review status: {status}")
    result = (await db.execute(
        select(EvaluationResult).join(EvaluationRun, EvaluationRun.id == EvaluationResult.run_id).where(
            EvaluationResult.id == result_id, EvaluationRun.organization_id == organization_id,
        )
    )).scalar_one_or_none()
    if result is None:
        return None
    result.human_review_status = status
    result.human_review_note = note
    result.reviewed_by_id = reviewer_id
    result.reviewed_at = datetime.now(timezone.utc)
    await audit.write(
        db, organization_id=organization_id, user_id=reviewer_id,
        event_type="evaluation.result.reviewed", message="Evaluation result reviewed",
        entity_type="evaluation_result", entity_id=str(result.id), after_data={"status": status},
    )
    return result
