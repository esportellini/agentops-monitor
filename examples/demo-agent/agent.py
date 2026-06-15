"""
AgentOps Monitor — Demo Agent

Simulates a compliance copilot:
  1. RAG document search
  2. Risk assessment tool
  3. LLM call with retry
  4. Error scenario

Run:
    AGENTOPS_API_KEY=agom_... python agent.py
"""
from __future__ import annotations

import logging
import os
import random
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

from agentops_monitor import AgentOps

# ── Configuration ─────────────────────────────────────────────────────────────

API_KEY = os.getenv("AGENTOPS_API_KEY", "agom_demo_replace_with_real_key")
ENDPOINT = os.getenv("AGENTOPS_ENDPOINT", "http://localhost:8000")
PROJECT_ID = int(os.getenv("AGENTOPS_PROJECT_ID", "1"))


def _redact(data: object) -> object:
    """Remove user-identifying fields before sending to AgentOps."""
    if isinstance(data, dict):
        return {
            k: "***REDACTED***" if k in ("user_id", "cpf", "email", "account_number") else _redact(v)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_redact(i) for i in data]
    return data


client = AgentOps(
    api_key=API_KEY,
    endpoint=ENDPOINT,
    project_id=PROJECT_ID,
    sample_rate=1.0,
    capture_inputs=True,
    capture_outputs=True,
    redact_fn=_redact,
)

# ── Simulated tools ───────────────────────────────────────────────────────────

def search_documents(query: str) -> list[dict]:
    """Simulate a vector-store RAG search."""
    time.sleep(0.05)
    return [
        {"doc_id": "CVM-001", "title": "Instrução CVM 358", "score": 0.92,
         "snippet": "...negociação por insider..."},
        {"doc_id": "BACEN-042", "title": "Circular BACEN 3461", "score": 0.88,
         "snippet": "...compliance ativo..."},
    ]


def assess_risk(asset_ticker: str, docs: list[dict]) -> dict:
    """Simulate a rule-based risk assessment tool."""
    time.sleep(0.02)
    risk_map = {"PETR4": "HIGH", "VALE3": "MEDIUM", "BBDC4": "LOW"}
    level = risk_map.get(asset_ticker.upper(), "MEDIUM")
    return {
        "asset": asset_ticker,
        "risk_level": level,
        "blocking_rules": ["insider_trading_period"] if level == "HIGH" else [],
        "docs_checked": len(docs),
    }


def call_llm(prompt: str, *, max_retries: int = 2) -> dict:
    """Simulate an LLM call with retry on transient failure."""
    for attempt in range(max_retries + 1):
        try:
            if attempt == 0 and random.random() < 0.4:
                raise ConnectionError("LLM API timeout (simulated)")
            time.sleep(0.1)
            return {
                "text": (
                    "Based on the compliance documents reviewed, purchasing PETR4 during "
                    "the current quiet period requires prior approval from the compliance "
                    "officer. Please submit a pre-approval request via the compliance portal."
                ),
                "input_tokens": int(len(prompt.split()) * 1.3),
                "output_tokens": 85,
                "model": "gpt-4o-2024-11-20",
            }
        except ConnectionError as e:
            if attempt == max_retries:
                raise
            logging.warning("LLM attempt %d failed: %s — retrying...", attempt + 1, e)
            time.sleep(0.2 * (attempt + 1))
    raise RuntimeError("unreachable")


def parse_decision(text: str) -> str:
    t = text.lower()
    if "prior approval" in t or "pre-approval" in t:
        return "pre_approval_required"
    if "not permitted" in t or "prohibited" in t:
        return "blocked"
    return "permitted"


# ── Main agent ────────────────────────────────────────────────────────────────

def run_compliance_check(question: str, asset: str, user_ref: str) -> dict:
    with client.trace(
        name="answer-compliance-question",
        user_reference=user_ref,
        metadata={"asset": asset, "pipeline_version": "1.2.0"},
    ) as trace:

        trace.set_input({"question": question, "asset": asset})

        # Step 1: RAG search
        with trace.span("search-documents", span_type="RETRIEVAL") as span:
            docs = search_documents(question)
            span.set_input({"query": question})
            span.set_output({"num_docs": len(docs), "top_score": docs[0]["score"]})
            span.add_tool_call(
                "vector_search",
                input={"query": question, "top_k": 5},
                output={"results": len(docs)},
                status="SUCCESS",
                duration_ms=50,
            )

        # Step 2: Risk assessment
        with trace.span("assess-risk", span_type="TOOL") as span:
            risk = assess_risk(asset, docs)
            span.set_input({"asset": asset})
            span.set_output(risk)
            span.add_tool_call(
                "risk_assessment_engine",
                input={"asset": asset},
                output=risk,
                status="SUCCESS",
            )
            if risk["risk_level"] == "HIGH":
                trace.set_risk("HIGH")
                trace.event(
                    "high_risk_detected",
                    f"Asset {asset} flagged HIGH risk during quiet period",
                    severity="HIGH",
                    metadata={"blocking_rules": risk["blocking_rules"]},
                )

        # Step 3: LLM call with retry
        prompt = (
            f"Question: {question}\nAsset: {asset}\n"
            f"Risk: {risk['risk_level']}\n"
            f"Regulations: {[d['title'] for d in docs]}\n"
            "Provide a compliance decision."
        )
        with trace.span("llm-decision", span_type="LLM") as span:
            llm = call_llm(prompt)
            span.add_model_call(
                provider="openai",
                model=llm["model"],
                input_tokens=llm["input_tokens"],
                output_tokens=llm["output_tokens"],
                estimated_cost=llm["input_tokens"] * 0.000005 + llm["output_tokens"] * 0.000015,
                latency_ms=100,
            )
            span.set_output({"text_length": len(llm["text"])})

        decision = parse_decision(llm["text"])
        trace.set_output({"decision": decision, "risk_level": risk["risk_level"]})
        return {"decision": decision, "risk_level": risk["risk_level"]}


def run_error_scenario() -> None:
    print("\n--- Error scenario ---")
    try:
        with client.trace(name="error-demo") as trace:
            trace.set_input({"scenario": "intentional error"})
            with trace.span("failing-step") as span:
                span.set_input({"about_to": "fail"})
                raise ValueError("Something went wrong in the pipeline")
    except ValueError as e:
        print(f"App caught error: {e} (trace recorded as ERROR)")


if __name__ == "__main__":
    print("AgentOps Monitor — Compliance Copilot Demo")
    print(f"Backend  : {ENDPOINT}")
    print(f"API key  : {API_KEY[:12]}...")
    print()

    print("--- Compliance check ---")
    result = run_compliance_check(
        question="Posso comprar ações da PETR4 agora?",
        asset="PETR4",
        user_ref="user_hash_abc123",
    )
    print(f"Decision : {result['decision']}")
    print(f"Risk     : {result['risk_level']}")

    run_error_scenario()

    client.flush()
    client.close()
    print("\nDone. Check your AgentOps dashboard at http://localhost:3000")
