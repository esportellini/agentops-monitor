"""
Alert service.

Evaluates alert rules against runtime data and creates incidents.
Rules use a simple structured condition format — no expression eval().

Condition schema:
    {"metric": "error_rate",     "op": "gt", "threshold": 0.05}
    {"metric": "cost_usd",       "op": "gt", "threshold": 10.0}
    {"metric": "latency_ms",     "op": "gt", "threshold": 5000}
    {"metric": "finding_type",   "op": "eq", "value": "prompt_injection"}

Supported metrics: error_rate, cost_usd, latency_ms, finding_type,
                   retry_count, token_count, agent_idle_hours
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import AlertIncident, AlertRule
from app.models.enums import AlertIncidentStatus, AlertRuleStatus, Severity

_OPS = {
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
}


def _eval_condition(condition: dict, data: dict[str, Any]) -> bool:
    """Evaluate a single rule condition against runtime data."""
    metric = condition.get("metric")
    op = condition.get("op", "gt")
    threshold = condition.get("threshold") or condition.get("value")

    val = data.get(metric)
    if val is None or metric not in data:
        return False

    fn = _OPS.get(op)
    if fn is None:
        return False

    try:
        return fn(val, threshold)
    except (TypeError, ValueError):
        return False


async def evaluate_rules_for_event(
    db: AsyncSession,
    organization_id: int,
    event_data: dict[str, Any],
) -> list[AlertIncident]:
    """
    Evaluate all active alert rules for the org against event_data.
    Creates an incident for each rule that fires.
    Returns created incidents.
    """
    result = await db.execute(
        select(AlertRule).where(
            AlertRule.organization_id == organization_id,
            AlertRule.status == AlertRuleStatus.ACTIVE,
        )
    )
    rules = list(result.scalars().all())

    created: list[AlertIncident] = []
    for rule in rules:
        try:
            if _eval_condition(rule.condition, event_data):
                incident = AlertIncident(
                    rule_id=rule.id,
                    status=AlertIncidentStatus.OPEN,
                    context=event_data,
                    triggered_at=datetime.now(timezone.utc),
                )
                db.add(incident)
                created.append(incident)
        except Exception:
            pass

    if created:
        await db.flush()

    return created


async def list_rules(db: AsyncSession, organization_id: int) -> list[AlertRule]:
    result = await db.execute(
        select(AlertRule)
        .where(AlertRule.organization_id == organization_id)
        .order_by(AlertRule.created_at.desc())
    )
    return list(result.scalars().all())


async def create_rule(
    db: AsyncSession,
    organization_id: int,
    data: dict[str, Any],
    created_by_id: int | None = None,
) -> AlertRule:
    rule = AlertRule(
        organization_id=organization_id,
        created_by_id=created_by_id,
        name=data["name"],
        description=data.get("description"),
        condition=data["condition"],
        severity=Severity(data.get("severity", "MEDIUM")),
        status=AlertRuleStatus.ACTIVE,
        notification_channels=data.get("notification_channels"),
    )
    db.add(rule)
    await db.flush()
    return rule


async def update_rule(
    db: AsyncSession,
    rule_id: int,
    organization_id: int,
    data: dict[str, Any],
) -> AlertRule | None:
    result = await db.execute(
        select(AlertRule).where(
            AlertRule.id == rule_id,
            AlertRule.organization_id == organization_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        return None
    for key in ("name", "description", "condition", "severity", "status", "notification_channels"):
        if key in data:
            setattr(rule, key, data[key])
    return rule


async def delete_rule(db: AsyncSession, rule_id: int, organization_id: int) -> bool:
    result = await db.execute(
        select(AlertRule).where(
            AlertRule.id == rule_id,
            AlertRule.organization_id == organization_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        return False
    await db.delete(rule)
    return True


async def list_incidents(
    db: AsyncSession,
    organization_id: int,
    status: str | None = None,
    limit: int = 50,
) -> list[AlertIncident]:
    q = (
        select(AlertIncident)
        .join(AlertRule, AlertRule.id == AlertIncident.rule_id)
        .where(AlertRule.organization_id == organization_id)
    )
    if status:
        q = q.where(AlertIncident.status == AlertIncidentStatus(status))
    q = q.order_by(AlertIncident.triggered_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_incident(
    db: AsyncSession,
    incident_id: int,
    organization_id: int,
    data: dict[str, Any],
    user_id: int | None = None,
) -> AlertIncident | None:
    result = await db.execute(
        select(AlertIncident)
        .join(AlertRule, AlertRule.id == AlertIncident.rule_id)
        .where(
            AlertIncident.id == incident_id,
            AlertRule.organization_id == organization_id,
        )
    )
    incident = result.scalar_one_or_none()
    if incident is None:
        return None

    now = datetime.now(timezone.utc)
    new_status = data.get("status")
    if new_status:
        incident.status = AlertIncidentStatus(new_status)
        if new_status == "ACKNOWLEDGED" and not incident.acknowledged_at:
            incident.acknowledged_at = now
            if user_id:
                incident.acknowledged_by_id = user_id
        if new_status == "RESOLVED" and not incident.resolved_at:
            incident.resolved_at = now
            if user_id:
                incident.resolved_by_id = user_id

    if "note" in data:
        incident.resolution_note = data["note"]

    return incident
