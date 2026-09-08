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
            input_tokens=500, output_tokens=120)

    trace.set_output({"decisao": "pre_approval_required"})

client.flush()
```

## Enforcement de ferramentas

```python
from agentops_monitor import AgentOps, PolicyBlockedError

client = AgentOps(
    api_key="agom_...",
    endpoint="http://localhost:8000",
    agent_id=1,
    policy_fail_mode="closed",
)

with client.trace("pesquisa") as trace:
    with trace.span("web", span_type="TOOL") as span:
        decision = span.check_tool("web_search", target_url="https://docs.example.com")
        print(decision.decision, decision.reason_code, decision.limits)
        result = span.run_tool(
            "web_search", search, "AgentOps",
            target_url="https://docs.example.com",
        )
```

`run_tool` executa somente decisões `ALLOW`. `BLOCK` lança
`PolicyBlockedError`; `REQUIRE_APPROVAL` lança `ApprovalRequiredError`. Falhas de
rede produzem `UNAVAILABLE`: `policy_fail_mode="open"` executa a função e registra
o fallback, enquanto `"closed"` lança `PolicyUnavailableError`. O preflight envia
somente trace, nome da ferramenta e URL opcional, nunca os argumentos da função.

Por padrão, approvals são não bloqueantes. `ApprovalRequiredError` expõe
`approval_id`, `external_request_id`, `reason_code` e `status`.

```python
result = span.run_tool(
    "send_email",
    send_email,
    wait_for_approval=True,
    approval_timeout=120,
    approval_poll_interval=1,
    approval_context={"recipient_group": "finance"},
)
```

No modo de espera, o SDK consulta o status sem busy loop. Após `approved`, repete
o preflight com o mesmo request ID e executa somente se a policy atual retornar
`ALLOW`. Rejeição lança `ApprovalRejectedError`; timeout lança
`ApprovalTimeoutError` e deixa o approval pendente. Indisponibilidade após uma
decisão `REQUIRE_APPROVAL` lança `PolicyUnavailableError` mesmo em fail-open.

O SDK envia automaticamente o instante UTC da model call. O backend combina
`provider`, `model`, contagens de tokens e a tabela de preços versionada para
calcular o custo. O argumento `estimated_cost` ainda é aceito para compatibilidade,
mas é apenas informativo e não controla o custo persistido.

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
