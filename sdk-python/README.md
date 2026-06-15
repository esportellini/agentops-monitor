# AgentOps Monitor — Python SDK

Observabilidade para agentes de IA. Instrumente suas aplicações com três linhas de código.

## Instalação

```bash
pip install agentops-monitor
```

## Exemplo mínimo

```python
from agentops_monitor import AgentOps

client = AgentOps(api_key="agom_...", endpoint="http://localhost:8000")

with client.trace(name="minha-tarefa") as trace:
    trace.set_input({"pergunta": "O que é compliance?"})
    resultado = executar_tarefa()
    trace.set_output({"resposta": resultado})

client.flush()
```

## Exemplo completo com spans, tool calls e model calls

```python
from agentops_monitor import AgentOps

client = AgentOps(
    api_key="agom_...",
    endpoint="http://localhost:8000",
    project_id=1,
    sample_rate=1.0,
    capture_inputs=True,
    capture_outputs=True,
    redact_fn=lambda d: {k: "***" if k in ("cpf", "senha") else v for k, v in d.items()} if isinstance(d, dict) else d,
)

with client.trace(name="answer-compliance-question", user_reference="user_hash_abc123") as trace:
    trace.set_input({"pergunta": "Posso comprar PETR4?"})

    with trace.span("buscar-documentos", span_type="RETRIEVAL") as span:
        docs = buscar(query="PETR4 compliance")
        span.set_output({"num_docs": len(docs)})
        span.add_tool_call("vector_search", input={"query": "PETR4"}, output=docs, status="SUCCESS")

    with trace.span("decisao-llm", span_type="LLM") as span:
        resposta = chamar_llm(docs)
        span.add_model_call("openai", "gpt-4o",
            input_tokens=500, output_tokens=120, estimated_cost=0.0044)

    trace.set_output({"decisao": "pre_approval_required"})

client.flush()
```

## Tratamento de erros

O SDK **nunca** derruba a aplicação por falha de observabilidade.

```python
with client.trace("minha-tarefa") as trace:
    resultado = executar_tarefa()  # executa normalmente mesmo com backend fora do ar
```

## Privacidade

```python
def redact(data):
    if isinstance(data, dict):
        return {k: "[REDACTED]" if k in {"cpf", "email", "senha"} else v for k, v in data.items()}
    return data

client = AgentOps(api_key="...", redact_fn=redact, capture_inputs=False)
```

## Testes

```bash
cd sdk-python
pip install -e ".[dev]"
pytest tests/ -v
```
