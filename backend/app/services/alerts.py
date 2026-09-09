"""Validated runtime alert evaluation and incident management."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.alert import AlertIncident, AlertRule
from app.models.enums import AlertIncidentStatus, AlertRuleStatus, Severity
from app.models.project import Agent, Project
from app.services import audit as audit_svc
from app.services.security import ALL_FINDING_TYPES

log = get_logger(__name__)

SECURITY_FINDING_CREATED = "security.finding.created"
TRACE_FINISHED = "trace.finished"
SUPPORTED_EVENTS = {SECURITY_FINDING_CREATED, TRACE_FINISHED}

EVENT_METRICS = {
    SECURITY_FINDING_CREATED: {"event_type", "finding_type", "severity", "action_taken"},
    TRACE_FINISHED: {
        "event_type", "trace_status", "risk_level", "total_cost_usd",
        "total_tokens", "duration_ms", "unpriced_model_calls",
    },
}
NUMERIC_METRICS = {
    "total_cost_usd", "total_tokens", "duration_ms", "unpriced_model_calls",
}
ENUM_VALUES = {
    "finding_type": set(ALL_FINDING_TYPES),
    "severity": {item.value for item in Severity},
    "risk_level": {item.value for item in Severity},
    "trace_status": {"RUNNING", "SUCCESS", "ERROR", "BLOCKED", "CANCELLED"},
    "action_taken": {"detect", "redact", "alert", "block"},
    "event_type": SUPPORTED_EVENTS,
}
OPERATORS = {"eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in"}
ORDER_OPERATORS = {"gt", "gte", "lt", "lte"}
MEMBERSHIP_OPERATORS = {"in", "not_in"}
METRIC_ALIASES = {
    "cost_usd": "total_cost_usd",
    "token_count": "total_tokens",
    "latency_ms": "duration_ms",
}


class AlertRuleValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeAlertEvent:
    event_type: str
    organization_id: int
    project_id: int | None
    agent_id: int | None
    trace_id: int | None
    span_id: int | None
    source_type: str
    source_id: str
    occurred_at: datetime
    data: dict[str, Any]


def _event_for_metric(metric: str) -> str:
    normalized = METRIC_ALIASES.get(metric, metric)
    if normalized in EVENT_METRICS[SECURITY_FINDING_CREATED]:
        return SECURITY_FINDING_CREATED
    return TRACE_FINISHED


def normalize_condition(event_type: str, condition: dict[str, Any]) -> dict[str, Any]:
    if event_type not in SUPPORTED_EVENTS:
        raise AlertRuleValidationError("Unsupported event_type")
    if not isinstance(condition, dict):
        raise AlertRuleValidationError("condition must be an object")
    raw_metric = str(condition.get("metric", ""))
    metric = METRIC_ALIASES.get(raw_metric, raw_metric)
    op = str(condition.get("op", "eq"))
    if metric not in EVENT_METRICS[event_type]:
        raise AlertRuleValidationError("Metric is not supported for this event_type")
    if op not in OPERATORS:
        raise AlertRuleValidationError("Unsupported operator")
    if "value" in condition:
        value = condition["value"]
    elif "threshold" in condition:
        value = condition["threshold"]
    else:
        raise AlertRuleValidationError("condition.value is required")

    if metric in NUMERIC_METRICS:
        if op in MEMBERSHIP_OPERATORS:
            if not isinstance(value, list) or not value or any(
                isinstance(item, bool) or not isinstance(item, (int, float, Decimal))
                for item in value
            ):
                raise AlertRuleValidationError("Numeric membership requires a numeric list")
        elif isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise AlertRuleValidationError("Numeric metric requires a numeric value")
    else:
        if op in ORDER_OPERATORS:
            raise AlertRuleValidationError("Ordered operators require a numeric metric")
        if op in MEMBERSHIP_OPERATORS:
            if not isinstance(value, list) or not value or any(not isinstance(v, str) for v in value):
                raise AlertRuleValidationError("Membership requires a string list")
        elif not isinstance(value, str):
            raise AlertRuleValidationError("Text metric requires a string value")
        allowed = ENUM_VALUES.get(metric)
        candidates = value if isinstance(value, list) else [value]
        if allowed is not None and any(candidate not in allowed for candidate in candidates):
            raise AlertRuleValidationError(f"Invalid value for {metric}")
    return {"metric": metric, "op": op, "value": value}


def normalize_rule_data(data: dict[str, Any], current: AlertRule | None = None) -> dict[str, Any]:
    event_type = data.get("event_type", current.event_type if current else None)
    condition = data.get("condition", current.condition if current else None)
    if event_type is None and isinstance(condition, dict):
        event_type = _event_for_metric(str(condition.get("metric", "")))
    return {
        "event_type": event_type,
        "condition": normalize_condition(event_type, condition),
    }


def _compare(actual: Any, op: str, expected: Any) -> bool:
    try:
        if op == "eq":
            return actual == expected
        if op == "neq":
            return actual != expected
        if op == "gt":
            return actual > expected
        if op == "gte":
            return actual >= expected
        if op == "lt":
            return actual < expected
        if op == "lte":
            return actual <= expected
        if op == "in":
            return actual in expected
        if op == "not_in":
            return actual not in expected
    except (TypeError, ValueError):
        return False
    return False


def _condition_matches(condition: dict[str, Any], event: RuntimeAlertEvent) -> bool:
    actual = event.event_type if condition["metric"] == "event_type" else event.data.get(condition["metric"])
    if actual is None:
        return False
    return _compare(actual, condition["op"], condition["value"])


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _incident_context(rule: AlertRule, event: RuntimeAlertEvent) -> dict[str, Any]:
    condition = rule.condition
    actual = event.event_type if condition["metric"] == "event_type" else event.data[condition["metric"]]
    context = {
        "metric": condition["metric"],
        "operator": condition["op"],
        "expected": _json_value(condition["value"]),
        "actual": _json_value(actual),
        "trace_id": event.trace_id,
        "agent_id": event.agent_id,
    }
    if event.event_type == TRACE_FINISHED:
        context["unpriced_model_calls"] = event.data.get("unpriced_model_calls", 0)
    return context


async def _matching_rules(db: AsyncSession, event: RuntimeAlertEvent) -> list[AlertRule]:
    rows = await db.execute(select(AlertRule).where(
        AlertRule.organization_id == event.organization_id,
        AlertRule.event_type == event.event_type,
        AlertRule.status == AlertRuleStatus.ACTIVE,
    ))
    return [
        rule for rule in rows.scalars().all()
        if (rule.project_id is None or rule.project_id == event.project_id)
        and (rule.agent_id is None or rule.agent_id == event.agent_id)
    ]


async def _evaluate_runtime_event(
    db: AsyncSession, event: RuntimeAlertEvent
) -> list[AlertIncident]:
    created: list[AlertIncident] = []
    rules = await _matching_rules(db, event)
    for rule in rules:
        try:
            normalized_condition = normalize_condition(rule.event_type, rule.condition)
        except AlertRuleValidationError:
            log.exception(
                "alert.evaluation.failed", rule_id=rule.id,
                event_type=event.event_type, source_id=event.source_id,
            )
            continue
        if normalized_condition != rule.condition:
            rule.condition = normalized_condition
        matched = _condition_matches(normalized_condition, event)
        log.info(
            "alert.rule.evaluated", rule_id=rule.id, event_type=event.event_type,
            source_type=event.source_type, source_id=event.source_id, matched=matched,
        )
        if not matched:
            continue
        dedupe_key = f"{rule.id}:{event.event_type}:{event.source_type}:{event.source_id}"
        try:
            async with db.begin_nested():
                existing = await db.scalar(select(AlertIncident.id).where(
                    AlertIncident.dedupe_key == dedupe_key
                ))
                if existing is not None:
                    log.info("alert.incident.deduplicated", rule_id=rule.id, source_id=event.source_id)
                    continue
                incident = AlertIncident(
                    rule_id=rule.id,
                    event_type=event.event_type,
                    source_type=event.source_type,
                    source_id=event.source_id,
                    trace_id=event.trace_id,
                    project_id=event.project_id,
                    agent_id=event.agent_id,
                    severity=rule.severity,
                    dedupe_key=dedupe_key,
                    status=AlertIncidentStatus.OPEN,
                    context=_incident_context(rule, event),
                    triggered_at=event.occurred_at,
                )
                db.add(incident)
                await db.flush()
                await audit_svc.write(
                    db,
                    organization_id=event.organization_id,
                    event_type="alert.incident.created",
                    entity_type="alert_incident",
                    entity_id=str(incident.id),
                    severity=rule.severity,
                    message="Runtime alert incident created",
                    after_data={
                        "incident_id": incident.id, "rule_id": rule.id,
                        "event_type": event.event_type, "source_type": event.source_type,
                        "source_id": event.source_id,
                    },
                )
            created.append(incident)
            log.info(
                "alert.incident.created", incident_id=incident.id, rule_id=rule.id,
                event_type=event.event_type, source_id=event.source_id,
            )
        except IntegrityError:
            log.info("alert.incident.deduplicated", rule_id=rule.id, source_id=event.source_id)
        except Exception:
            log.exception(
                "alert.evaluation.failed", rule_id=rule.id,
                event_type=event.event_type, source_id=event.source_id,
            )
    return created


async def evaluate_runtime_event(
    db: AsyncSession, event: RuntimeAlertEvent
) -> list[AlertIncident]:
    """Evaluate an event without allowing alert failures to poison ingest."""
    try:
        async with db.begin_nested():
            return await _evaluate_runtime_event(db, event)
    except Exception:
        log.exception(
            "alert.evaluation.failed", event_type=event.event_type,
            source_type=event.source_type, source_id=event.source_id,
        )
        return []


async def evaluate_rules_for_event(
    db: AsyncSession,
    organization_id: int,
    event_data: dict[str, Any],
) -> list[AlertIncident]:
    """Compatibility wrapper for the pre-runtime service API."""
    known_metrics = set().union(*EVENT_METRICS.values()) | set(METRIC_ALIASES)
    metric = next((key for key in event_data if key in known_metrics), "")
    event_type = event_data.get("event_type") or _event_for_metric(metric)
    encoded = json.dumps(event_data, sort_keys=True, default=str).encode()
    event = RuntimeAlertEvent(
        event_type=event_type,
        organization_id=organization_id,
        project_id=event_data.get("project_id"),
        agent_id=event_data.get("agent_id"),
        trace_id=event_data.get("trace_id"),
        span_id=event_data.get("span_id"),
        source_type=str(event_data.get("source_type", "legacy_event")),
        source_id=str(event_data.get("source_id", hashlib.sha256(encoded).hexdigest())),
        occurred_at=datetime.now(timezone.utc),
        data={METRIC_ALIASES.get(k, k): v for k, v in event_data.items()},
    )
    return await evaluate_runtime_event(db, event)


async def _validate_scope(
    db: AsyncSession, organization_id: int, project_id: int | None, agent_id: int | None
) -> None:
    if project_id is not None and await db.scalar(select(Project.id).where(
        Project.id == project_id, Project.organization_id == organization_id,
    )) is None:
        raise AlertRuleValidationError("Invalid project scope")
    if agent_id is not None:
        agent_project = await db.scalar(
            select(Agent.project_id).join(Project).where(
                Agent.id == agent_id, Project.organization_id == organization_id,
            )
        )
        if agent_project is None or (project_id is not None and agent_project != project_id):
            raise AlertRuleValidationError("Invalid agent scope")


async def list_rules(db: AsyncSession, organization_id: int) -> list[AlertRule]:
    rows = await db.execute(
        select(AlertRule).where(AlertRule.organization_id == organization_id)
        .order_by(AlertRule.created_at.desc())
    )
    return list(rows.scalars().all())


async def create_rule(
    db: AsyncSession,
    organization_id: int,
    data: dict[str, Any],
    created_by_id: int | None = None,
) -> AlertRule:
    normalized = normalize_rule_data(data)
    await _validate_scope(db, organization_id, data.get("project_id"), data.get("agent_id"))
    rule = AlertRule(
        organization_id=organization_id,
        project_id=data.get("project_id"),
        agent_id=data.get("agent_id"),
        created_by_id=created_by_id,
        name=data["name"],
        description=data.get("description"),
        event_type=normalized["event_type"],
        condition=normalized["condition"],
        severity=Severity(data.get("severity", "MEDIUM")),
        status=AlertRuleStatus(data.get("status", "ACTIVE")),
        notification_channels=None,
    )
    db.add(rule)
    await db.flush()
    await audit_svc.write(
        db, organization_id=organization_id, user_id=created_by_id,
        event_type="alert.rule.created", entity_type="alert_rule", entity_id=str(rule.id),
        message="Alert rule created", after_data={
            "rule_id": rule.id, "event_type": rule.event_type, "status": rule.status.value,
        },
    )
    return rule


async def update_rule(
    db: AsyncSession,
    rule_id: int,
    organization_id: int,
    data: dict[str, Any],
    user_id: int | None = None,
) -> AlertRule | None:
    rule = await db.scalar(select(AlertRule).where(
        AlertRule.id == rule_id, AlertRule.organization_id == organization_id,
    ))
    if rule is None:
        return None
    normalized = normalize_rule_data(data, rule)
    project_id = data.get("project_id", rule.project_id)
    agent_id = data.get("agent_id", rule.agent_id)
    await _validate_scope(db, organization_id, project_id, agent_id)
    for key in ("name", "description", "project_id", "agent_id"):
        if key in data:
            setattr(rule, key, data[key])
    rule.event_type = normalized["event_type"]
    rule.condition = normalized["condition"]
    if "severity" in data:
        rule.severity = Severity(data["severity"])
    if "status" in data:
        rule.status = AlertRuleStatus(data["status"])
    await audit_svc.write(
        db, organization_id=organization_id, user_id=user_id,
        event_type="alert.rule.updated", entity_type="alert_rule", entity_id=str(rule.id),
        message="Alert rule updated", after_data={
            "rule_id": rule.id, "event_type": rule.event_type, "status": rule.status.value,
        },
    )
    return rule


async def delete_rule(
    db: AsyncSession, rule_id: int, organization_id: int, user_id: int | None = None
) -> bool:
    rule = await db.scalar(select(AlertRule).where(
        AlertRule.id == rule_id, AlertRule.organization_id == organization_id,
    ))
    if rule is None:
        return False
    rule.status = AlertRuleStatus.INACTIVE
    await audit_svc.write(
        db, organization_id=organization_id, user_id=user_id,
        event_type="alert.rule.deactivated", entity_type="alert_rule", entity_id=str(rule.id),
        message="Alert rule deactivated", after_data={"rule_id": rule.id, "status": "INACTIVE"},
    )
    return True


async def list_incidents(
    db: AsyncSession,
    organization_id: int,
    *,
    status: str | None = None,
    severity: str | None = None,
    rule_id: int | None = None,
    event_type: str | None = None,
    project_id: int | None = None,
    agent_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
) -> list[AlertIncident]:
    query = select(AlertIncident).join(AlertRule).where(
        AlertRule.organization_id == organization_id
    )
    if status:
        query = query.where(AlertIncident.status == AlertIncidentStatus(status))
    if severity:
        query = query.where(AlertIncident.severity == Severity(severity))
    if rule_id is not None:
        query = query.where(AlertIncident.rule_id == rule_id)
    if event_type:
        query = query.where(AlertIncident.event_type == event_type)
    if project_id is not None:
        query = query.where(AlertIncident.project_id == project_id)
    if agent_id is not None:
        query = query.where(AlertIncident.agent_id == agent_id)
    if date_from is not None:
        query = query.where(AlertIncident.triggered_at >= date_from)
    if date_to is not None:
        query = query.where(AlertIncident.triggered_at <= date_to)
    rows = await db.execute(query.order_by(AlertIncident.triggered_at.desc()).limit(limit))
    return list(rows.scalars().all())


async def get_incident(
    db: AsyncSession, incident_id: int, organization_id: int
) -> AlertIncident | None:
    return await db.scalar(select(AlertIncident).join(AlertRule).where(
        AlertIncident.id == incident_id, AlertRule.organization_id == organization_id,
    ))


async def transition_incident(
    db: AsyncSession,
    incident_id: int,
    organization_id: int,
    outcome: str,
    user_id: int,
    note: str | None = None,
) -> tuple[AlertIncident | None, str | None]:
    incident = await get_incident(db, incident_id, organization_id)
    if incident is None:
        return None, "not_found"
    now = datetime.now(timezone.utc)
    if outcome == "ACKNOWLEDGED":
        allowed = [AlertIncidentStatus.OPEN]
        values = {
            "status": AlertIncidentStatus.ACKNOWLEDGED,
            "acknowledged_at": now,
            "acknowledged_by_id": user_id,
        }
        event_type = "alert.incident.acknowledged"
    elif outcome == "RESOLVED":
        allowed = [AlertIncidentStatus.OPEN, AlertIncidentStatus.ACKNOWLEDGED]
        values = {
            "status": AlertIncidentStatus.RESOLVED,
            "resolved_at": now,
            "resolved_by_id": user_id,
            "resolution_note": note,
        }
        event_type = "alert.incident.resolved"
    else:
        raise ValueError("Invalid incident transition")
    result = await db.execute(update(AlertIncident).where(
        AlertIncident.id == incident_id,
        AlertIncident.status.in_(allowed),
    ).values(**values))
    if result.rowcount != 1:
        return None, "conflict"
    incident = await get_incident(db, incident_id, organization_id)
    await audit_svc.write(
        db, organization_id=organization_id, user_id=user_id,
        event_type=event_type, entity_type="alert_incident", entity_id=str(incident_id),
        message=f"Alert incident {outcome.lower()}", after_data={
            "incident_id": incident_id, "rule_id": incident.rule_id, "status": outcome,
        },
    )
    return incident, None


async def update_incident(
    db: AsyncSession,
    incident_id: int,
    organization_id: int,
    data: dict[str, Any],
    user_id: int | None = None,
) -> AlertIncident | None:
    status = data.get("status")
    if status not in {"ACKNOWLEDGED", "RESOLVED"} or user_id is None:
        return None
    incident, _ = await transition_incident(
        db, incident_id, organization_id, status, user_id, data.get("note")
    )
    return incident
