"""
Evaluation API: datasets, cases, runs, results, comparison, human review.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import OrgContext, require_analyst, require_org_member
from app.db.session import get_db
from app.models.evaluation import EvaluationCase, EvaluationDataset, EvaluationResult, EvaluationRun
from app.services import evaluation as eval_svc

router = APIRouter(prefix="/organizations/{org_id}", tags=["evaluations"])


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
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    ds = await eval_svc.create_dataset(db, ctx.org_id, payload, user_id=ctx.user_id)
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
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    case = await eval_svc.add_case(db, dataset_id, ctx.org_id, payload)
    if not case:
        raise HTTPException(404, "Dataset not found")
    await db.commit()
    await db.refresh(case)
    return _case_out(case)


# ── Runs ──────────────────────────────────────────────────────────────────────

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
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    run = await eval_svc.create_run(db, ctx.org_id, payload, user_id=ctx.user_id)
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
        raise HTTPException(404, result["error"])
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
    payload: Annotated[dict, Body()],
    ctx: OrgContext = Depends(require_analyst),
    db: AsyncSession = Depends(get_db),
):
    status = payload.get("status")
    if status not in ("approved", "rejected", "needs_review"):
        raise HTTPException(422, "status must be approved | rejected | needs_review")

    result = await eval_svc.submit_human_review(
        db, result_id, ctx.org_id,
        status=status,
        note=payload.get("note"),
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
        "evaluator_details": r.evaluator_details,
        "error": r.error,
        "human_review_status": r.human_review_status,
        "human_review_note": r.human_review_note,
        "reviewed_by_id": r.reviewed_by_id,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        "created_at": r.created_at.isoformat(),
    }
