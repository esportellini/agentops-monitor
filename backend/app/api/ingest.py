"""
Ingest API — authenticated by API key, not user JWT.

All endpoints are under /ingest (not /api/v1) to make the distinction
clear and allow independent rate limiting at the proxy level.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ingest_auth import IngestContext, api_key_auth
from app.core.logging import get_logger
from app.db.session import get_db
from app.schemas.ingest import (
    BatchItem,
    BatchRequest,
    BatchResponse,
    BatchItemResult,
    ModelCallCreate,
    SpanCreate,
    SpanOut,
    SpanUpdate,
    ToolCallCreate,
    ToolPolicyCheck,
    ToolPolicyCheckOut,
    TraceEventCreate,
    TraceFinish,
    TraceOut,
    TraceStart,
)
from app.services import ingest as ingest_svc
from app.services.ingest import IngestError
from app.repositories import trace as trace_repo
from app.services.policy import evaluate_tool_preflight

router = APIRouter(prefix="/ingest", tags=["ingest"])
log = get_logger(__name__)

_BATCH_MAX_ITEMS = 500
_BATCH_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


def _err(e: IngestError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


# ── Traces ────────────────────────────────────────────────────────────────────

@router.post("/traces/start", response_model=TraceOut, status_code=status.HTTP_201_CREATED)
async def trace_start(
    body: TraceStart,
    ctx: IngestContext = Depends(api_key_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        trace = await ingest_svc.start_trace(db, ctx, body)
        await db.commit()
        return trace
    except IngestError as e:
        raise _err(e)


@router.post("/traces/{external_trace_id}/finish", response_model=TraceOut)
async def trace_finish(
    external_trace_id: str,
    body: TraceFinish,
    ctx: IngestContext = Depends(api_key_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        trace = await ingest_svc.finish_trace(db, ctx, external_trace_id, body)
        await db.commit()
        return trace
    except IngestError as e:
        raise _err(e)


# ── Spans ─────────────────────────────────────────────────────────────────────

@router.post("/traces/{external_trace_id}/spans", response_model=SpanOut, status_code=status.HTTP_201_CREATED)
async def span_create(
    external_trace_id: str,
    body: SpanCreate,
    ctx: IngestContext = Depends(api_key_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        span = await ingest_svc.create_span(db, ctx, external_trace_id, body)
        await db.commit()
        return span
    except IngestError as e:
        raise _err(e)


@router.patch("/spans/{external_span_id}", response_model=SpanOut)
async def span_update(
    external_span_id: str,
    body: SpanUpdate,
    ctx: IngestContext = Depends(api_key_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        span = await ingest_svc.update_span(db, ctx, external_span_id, body)
        await db.commit()
        return span
    except IngestError as e:
        raise _err(e)


# ── Tool calls ────────────────────────────────────────────────────────────────

@router.post("/policy/check-tool", response_model=ToolPolicyCheckOut)
async def policy_check_tool(
    body: ToolPolicyCheck,
    ctx: IngestContext = Depends(api_key_auth),
    db: AsyncSession = Depends(get_db),
):
    trace = await trace_repo.get_trace_by_external_id(
        db, body.external_trace_id, ctx.organization_id
    )
    if trace is None or (ctx.project_id is not None and trace.project_id != ctx.project_id):
        raise HTTPException(status_code=404, detail="Trace not found")
    result = await evaluate_tool_preflight(db, trace, body.tool_name, body.target_url)
    return {
        "decision": result.decision.value,
        "reason_code": result.reason_code,
        "reason": result.reason,
        "policy_id": result.policy_id,
        "limits": {
            "token_state": result.limits.token_state.value,
            "cost_state": result.limits.cost_state.value,
            "total_tokens": result.limits.total_tokens,
            "known_cost_usd": float(result.limits.known_cost_usd),
            "unpriced_model_calls": result.limits.unpriced_model_calls,
        },
    }

@router.post("/spans/{external_span_id}/tool-calls", status_code=status.HTTP_201_CREATED)
async def tool_call_create(
    external_span_id: str,
    body: ToolCallCreate,
    ctx: IngestContext = Depends(api_key_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        tc = await ingest_svc.create_tool_call(db, ctx, external_span_id, body)
        await db.commit()
        return {"id": tc.id, "span_id": tc.span_id, "tool_name": tc.tool_name, "status": tc.status}
    except IngestError as e:
        raise _err(e)


# ── Model calls ───────────────────────────────────────────────────────────────

@router.post("/spans/{external_span_id}/model-calls", status_code=status.HTTP_201_CREATED)
async def model_call_create(
    external_span_id: str,
    body: ModelCallCreate,
    ctx: IngestContext = Depends(api_key_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        mc = await ingest_svc.create_model_call(db, ctx, external_span_id, body)
        await db.commit()
        return {
            "id": mc.id,
            "span_id": mc.span_id,
            "provider": mc.provider,
            "model": mc.model,
            "input_tokens": mc.input_tokens,
            "output_tokens": mc.output_tokens,
            "estimated_cost": float(mc.estimated_cost),
            "occurred_at": mc.occurred_at,
            "pricing_status": mc.pricing_status,
            "pricing_id": mc.pricing_id,
            "status": mc.status,
        }
    except IngestError as e:
        raise _err(e)


# ── Events ────────────────────────────────────────────────────────────────────

@router.post("/traces/{external_trace_id}/events", status_code=status.HTTP_201_CREATED)
async def event_create(
    external_trace_id: str,
    body: TraceEventCreate,
    ctx: IngestContext = Depends(api_key_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        event = await ingest_svc.create_event(db, ctx, external_trace_id, body)
        await db.commit()
        return {"id": event.id, "trace_id": event.trace_id, "event_type": event.event_type}
    except IngestError as e:
        raise _err(e)


# ── Batch ─────────────────────────────────────────────────────────────────────

@router.post("/batch", response_model=BatchResponse)
async def batch_ingest(
    request: Request,
    body: BatchRequest,
    ctx: IngestContext = Depends(api_key_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Process multiple ingest events in one request.
    Each item is processed independently; failures don't abort the others.
    Returns a per-item result list so the SDK can retry only failed items.
    """
    # Payload size guard (already limited by Pydantic max_length, but belt-and-suspenders)
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _BATCH_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Payload exceeds {_BATCH_MAX_BYTES // 1024 // 1024}MB limit")

    results: list[BatchItemResult] = []
    accepted = 0
    failed = 0

    for i, item in enumerate(body.items):
        try:
            async with db.begin_nested():
                await _process_batch_item(db, ctx, item)
                # Surface database errors inside this item's savepoint.
                await db.flush()
            results.append(BatchItemResult(index=i, ok=True))
            accepted += 1
        except Exception as e:
            log.warning(
                "ingest.batch.item_failed",
                index=i,
                type=item.type,
                error_type=type(e).__name__,
            )
            results.append(BatchItemResult(index=i, ok=False, error="Item processing failed"))
            failed += 1

    # Commit what succeeded (partial success)
    try:
        await db.commit()
    except Exception as e:
        log.error("ingest.batch.commit_failed", error_type=type(e).__name__)
        raise HTTPException(status_code=500, detail="Failed to persist batch")

    return BatchResponse(accepted=accepted, failed=failed, results=results)


async def _process_batch_item(db: AsyncSession, ctx: IngestContext, item: BatchItem) -> None:
    p = item.payload

    if item.type == "trace_start":
        await ingest_svc.start_trace(db, ctx, TraceStart(**p))

    elif item.type == "trace_finish":
        if not item.external_trace_id:
            raise IngestError("external_trace_id required for trace_finish")
        await ingest_svc.finish_trace(db, ctx, item.external_trace_id, TraceFinish(**p))

    elif item.type == "span":
        if not item.external_trace_id:
            raise IngestError("external_trace_id required for span")
        await ingest_svc.create_span(db, ctx, item.external_trace_id, SpanCreate(**p))

    elif item.type == "span_update":
        if not item.external_span_id:
            raise IngestError("external_span_id required for span_update")
        await ingest_svc.update_span(db, ctx, item.external_span_id, SpanUpdate(**p))

    elif item.type == "tool_call":
        if not item.external_span_id:
            raise IngestError("external_span_id required for tool_call")
        await ingest_svc.create_tool_call(db, ctx, item.external_span_id, ToolCallCreate(**p))

    elif item.type == "model_call":
        if not item.external_span_id:
            raise IngestError("external_span_id required for model_call")
        await ingest_svc.create_model_call(db, ctx, item.external_span_id, ModelCallCreate(**p))

    elif item.type == "event":
        if not item.external_trace_id:
            raise IngestError("external_trace_id required for event")
        await ingest_svc.create_event(db, ctx, item.external_trace_id, TraceEventCreate(**p))

    else:
        raise IngestError(f"Unknown batch item type: {item.type}")
