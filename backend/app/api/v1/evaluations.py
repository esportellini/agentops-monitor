"""
Evaluation API: datasets, cases, runs, results, comparison, human review.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import OrgContext, require_analyst, require_org_member
from app.db.session import get_db
from app.models.evaluation import EvaluationCase, EvaluationDataset, EvaluationResult, EvaluationRun
from app.services import evaluation as eval_svc
from app.services.evaluator import provider_availability

router = APIRouter(prefix="/organizations/{org_id}", tags=["evaluations"])


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    version: str = Field(default="1.0.0", min_length=1, max_length=50)
    project_id: int | None = None
    tags: list[str] | None = None


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_data: dict[str, Any]
    expected_output: dict[str, Any] | None = None
    expected_tools: list[str] | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluators: list[dict[str, Any]] | None = None
    instructions: str | None = Field(default=None, max_length=20_000)
    output_mode: str = "text"
    allow_external_provider_data: bool = False
    mock_latency_ms: int | None = Field(default=None, ge=0, le=60_000)
    mock_cost: float | None = Field(default=None, ge=0)
    mock_error_rate: float | None = Field(default=None, ge=0, le=1)
    mock_output_override: dict[str, Any] | None = None
    mock_tools_called: list[str] | None = None


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: int
    name: str = Field(default="Evaluation run", min_length=1, max_length=255)
    provider: str = "mock"
    model: str | None = Field(default=None, max_length=100)
    agent_id: int | None = None
    agent_version: str | None = Field(default=None, max_length=100)
    prompt_version: str | None = Field(default=None, max_length=100)
    config: RunConfig = Field(default_factory=RunConfig)


class HumanReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    note: str | None = None


# ── Datasets ──────────────────────────────────────────────────────────────────

@router.get("/evaluation-datasets")
async def list_datasets(
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    datasets = await eval_svc.list_datasets(db, ctx.org_id)
    return {"items": [_ds_out(d) for d in datasets]}


@router.post("/evaluation-datasets", status_code=201)
async def create_dataset(
    payload: Annotated[DatasetCreate, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    try:
        ds = await eval_svc.create_dataset(db, ctx.org_id, payload.model_dump(), user_id=ctx.user_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await db.commit()
    await db.refresh(ds)
    return _ds_out(ds)


@router.get("/evaluation-datasets/{dataset_id}")
async def get_dataset(
    dataset_id: int,
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    ds = await eval_svc.get_dataset(db, dataset_id, ctx.org_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    return {**_ds_out(ds), "cases": [_case_out(c) for c in ds.cases]}


@router.post("/evaluation-datasets/{dataset_id}/cases", status_code=201)
async def add_case(
    dataset_id: int,
    payload: Annotated[CaseCreate, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    case = await eval_svc.add_case(db, dataset_id, ctx.org_id, payload.model_dump())
    if not case:
        raise HTTPException(404, "Dataset not found")
    await db.commit()
    await db.refresh(case)
    return _case_out(case)


# ── Runs ──────────────────────────────────────────────────────────────────────

@router.get("/evaluations/providers")
async def list_providers(
    ctx: OrgContext = Depends(require_org_member),
):
    return {"providers": provider_availability()}

@router.get("/evaluation-runs")
async def list_runs(
    dataset_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    runs = await eval_svc.list_runs(db, ctx.org_id, dataset_id=dataset_id, agent_id=agent_id, limit=limit)
    return {"items": [_run_out(r) for r in runs]}


@router.post("/evaluation-runs", status_code=201)
async def create_and_execute_run(
    payload: Annotated[RunCreate, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    data = payload.model_dump(exclude_none=True)
    if data.get("config", {}).get("evaluators") is None:
        data["config"].pop("evaluators", None)
    try:
        run = await eval_svc.create_run(db, ctx.org_id, data, user_id=ctx.user_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await db.flush()
    run = await eval_svc.execute_run(db, run)
    await db.commit()
    await db.refresh(run)
    return _run_out(run)


@router.get("/evaluation-runs/compare")
async def compare_runs(
    run_a: int = Query(...),
    run_b: int = Query(...),
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    result = await eval_svc.compare_runs(db, run_a, run_b, ctx.org_id)
    if "error" in result:
        status = 404 if result.get("error_code") == "not_found" else 422
        raise HTTPException(status, result["error"])
    return result


@router.get("/evaluation-runs/{run_id}")
async def get_run(
    run_id: int,
    ctx: OrgContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db),
):
    run = await eval_svc.get_run(db, run_id, ctx.org_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return {**_run_out(run), "results": [_result_out(r) for r in run.results]}


# ── Human review ──────────────────────────────────────────────────────────────

@router.post("/evaluation-results/{result_id}/human-review")
async def human_review(
    result_id: int,
    payload: Annotated[HumanReviewCreate, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    status = payload.status
    if status not in ("approved", "rejected", "needs_review"):
        raise HTTPException(422, "status must be approved | rejected | needs_review")

    result = await eval_svc.submit_human_review(
        db, result_id, ctx.org_id,
        status=status,
        note=payload.note,
        reviewer_id=ctx.user_id,
    )
    if not result:
        raise HTTPException(404, "Result not found")
    await db.commit()
    return _result_out(result)


# ── Serialisers ───────────────────────────────────────────────────────────────

def _ds_out(d: EvaluationDataset) -> dict:
    return {
        "id": d.id,
        "organization_id": d.organization_id,
        "project_id": d.project_id,
        "name": d.name,
        "description": d.description,
        "version": d.version,
        "tags": d.tags,
        "created_at": d.created_at.isoformat(),
    }


def _case_out(c: EvaluationCase) -> dict:
    return {
        "id": c.id,
        "dataset_id": c.dataset_id,
        "input_data": c.input_data,
        "expected_output": c.expected_output,
        "expected_tools": c.expected_tools,
        "tags": c.tags,
        "metadata": c.metadata_,
        "created_at": c.created_at.isoformat(),
    }


def _run_out(r: EvaluationRun) -> dict:
    return {
        "id": r.id,
        "organization_id": r.organization_id,
        "dataset_id": r.dataset_id,
        "agent_id": r.agent_id,
        "name": r.name,
        "agent_version": r.agent_version,
        "provider": r.provider,
        "model": r.model,
        "provider_api": r.provider_api,
        "prompt_version": r.prompt_version,
        "status": r.status,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "total_cost": r.total_cost,
        "average_latency_ms": r.average_latency_ms,
        "pass_rate": r.pass_rate,
        "average_score": r.average_score,
        "total_cases": r.total_cases,
        "passed_cases": r.passed_cases,
        "executed_cases": r.executed_cases,
        "error_cases": r.error_cases,
        "unpriced_cases": r.unpriced_cases,
        "failure_reason": r.failure_reason,
        "config": r.config,
        "created_at": r.created_at.isoformat(),
    }


def _result_out(r: EvaluationResult) -> dict:
    return {
        "id": r.id,
        "run_id": r.run_id,
        "case_id": r.case_id,
        "actual_output": r.actual_output,
        "actual_tools_used": r.actual_tools_used,
        "passed": r.passed,
        "score": r.score,
        "latency_ms": r.latency_ms,
        "cost": r.cost,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "pricing_status": r.pricing_status,
        "pricing_id": r.pricing_id,
        "input_price_per_million": float(r.input_price_per_million) if r.input_price_per_million is not None else None,
        "output_price_per_million": float(r.output_price_per_million) if r.output_price_per_million is not None else None,
        "evaluator_details": r.evaluator_details,
        "error": r.error,
        "human_review_status": r.human_review_status,
        "human_review_note": r.human_review_note,
        "reviewed_by_id": r.reviewed_by_id,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        "created_at": r.created_at.isoformat(),
    }
