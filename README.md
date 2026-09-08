# AgentOps Monitor

**Observabilidade e controle para agentes de IA em produção.**

---

## O problema

Agentes de IA fazem chamadas a modelos, ferramentas, APIs externas e processam dados potencialmente sensíveis dos usuários. Quando algo dá errado — custo fora de controle, resposta inadequada, dado sensível exposto, ferramenta não autorizada chamada — você precisa saber o que aconteceu, quando, e por quê.

Logs convencionais não foram projetados para isso.

## A solução

AgentOps Monitor é uma plataforma B2B multi-tenant que coleta traces hierárquicos de execuções de agentes via SDK Python, processa, analisa e exibe em um dashboard com contexto completo: spans, tool calls, model calls, tokens, custos, segurança e avaliações.

---

## Funcionalidades

### Observabilidade
- **Traces e Spans** hierárquicos com input/output, latência, status, custo
- **Tool calls** com status de aprovação e detalhes de entrada/saída
- **Model calls** com tokens, custo por provider/modelo e latência
- **Eventos** customizados com severidade no contexto de cada trace

### Custos
- Precificação autoritativa no backend por provider + modelo + janela de vigência
- Defaults globais com overrides isolados por organização
- Snapshot histórico das tarifas usadas em cada model call
- Modelos sem preço continuam observáveis e são marcados como `UNPRICED`
- Custo por trace, agente, projeto, ambiente, modelo, período
- Projeção mensal com base na média diária
- Top traces mais caros

### Segurança
- Scanner automático de dados sensíveis no ingest (regex + Luhn + checksum CPF)
- Redação estrutural antes da persistência e criação automática de findings
- Detecção de prompt injection e SQL perigoso com agregação de risco da trace
- Políticas ativas por agente para ferramentas, domínios, captura, ações de segurança e limites por trace
- Preflight autenticado para bloquear ou exigir aprovação antes da execução de uma ferramenta
- Aprovação humana por tentativa, com revalidação e consumo único
- Detecção post-hoc de violações sem reescrever o status informado pela aplicação

### Semântica das políticas

O endpoint `POST /ingest/policy/check-tool` recebe o ID externo da trace, o nome da
ferramenta e, opcionalmente, a URL alvo. O agente e a organização vêm da trace e da
chave de ingestão; o cliente não pode escolher outra política. A decisão segue a
precedência: bloqueio explícito, allowlist, domínio, limites excedidos, aprovação e
permissão. Os limites usam apenas model calls já persistidas. O limite é excedido
quando o uso é maior que o valor configurado; igualdade ainda é permitida. Quando
há model calls sem preço e o custo conhecido não excedeu o limite, o estado do
orçamento é `UNKNOWN`.

As ações `detect`, `redact`, `alert` e `block` são registradas no finding. Nesta
fase, `alert` não cria incidentes. `REQUIRE_APPROVAL` cria uma solicitação humana
por tentativa, decidida por membros com role `ANALYST` ou superior. `block`
substitui o conteúdo correspondente antes da
persistência. Mesmo com captura de entradas ou saídas desativada, o backend faz a
varredura em memória e guarda somente os findings seguros.

### Avaliações
- Datasets de casos de teste offline
- 7 avaliadores determinísticos: exact match, word presence, JSON structure, expected tools, cost limit, latency limit, required source
- Comparação de runs: A vs B com delta de pass rate, score, custo, latência
- Human review por resultado

### Privacidade / LGPD
- Mapa de dados com finalidade e sensibilidade por categoria
- Política de retenção configurável por organização
- Anonimização de user_references
- Solicitações de titular (exportar, anonimizar, deletar, acessar)
- Registro de execução de políticas

### Auditoria
- Log imutável de todos os eventos relevantes
- Filtros por tipo, severidade, usuário, entidade, período
- Exportação CSV
- Before/after data em alterações

---

## Stack

```
Backend     FastAPI 0.115 + Python 3.12 + SQLAlchemy 2.0 async
Database    PostgreSQL 15 (Alembic migrations)
Cache/Auth  Redis 7 (JWT refresh tokens)
Frontend    Next.js 14.2 + TypeScript + Tailwind CSS + TanStack Query
SDK         Python (agentops-monitor package)
Container   Docker + Docker Compose
```

---

## Instalação

### Pré-requisitos
- Docker Desktop com Compose v2
- Portas livres: 3000 (frontend), 8000 (backend), 5432 (postgres), 6379 (redis)

### 1. Clone ou extraia o projeto

```bash
cd agentops-monitor
```

### 2. Build e inicialização

```bash
docker compose down -v           # limpa volumes anteriores
docker compose build --no-cache  # build completo
docker compose up -d             # inicia em background
docker exec agentops-monitor-backend-1 python seed.py  # seed com dados demo
```

### 3. Acesso

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- Swagger: http://localhost:8000/docs

---

## Usuários demo

| Email | Senha | Role |
|---|---|---|
| owner@demo.agentops.dev | demo-owner-2024 | OWNER |
| admin@demo.agentops.dev | demo-admin-2024 | ADMIN |
| dev@demo.agentops.dev | demo-dev-2024 | DEVELOPER |
| analyst@demo.agentops.dev | demo-analyst-2024 | ANALYST |
| viewer@demo.agentops.dev | demo-viewer-2024 | VIEWER |

**Organização demo:** Acme AI (slug: `acme-ai`)

---

## SDK Python

### Instalação

```bash
pip install agentops-monitor
# ou em desenvolvimento:
pip install -e ./sdk-python
```

### Uso básico

```python
from agentops_monitor import AgentOps

client = AgentOps(
    api_key="agom_sua_chave",
    endpoint="http://localhost:8000",
)

with client.trace(name="responder-pergunta") as trace:
    trace.set_input({"pergunta": "Posso comprar PETR4?"})

    with trace.span("buscar-docs", span_type="RETRIEVAL") as span:
        docs = buscar_documentos()
        span.set_output({"num_docs": len(docs)})
        span.add_tool_call("vector_search", input={"q": "PETR4"}, output=docs)

    with trace.span("chamar-llm", span_type="LLM") as span:
        resposta = chamar_llm(docs)
        span.add_model_call("openai", "gpt-4o",
            input_tokens=500, output_tokens=120)

    trace.set_output({"decisao": "pre_approval_required"})

client.flush()
```

Para aguardar uma decisão humana, mantendo uma solicitação por tentativa:

```python
resultado = span.run_tool(
    "send_email",
    send_email,
    wait_for_approval=True,
    approval_timeout=120,
    approval_context={
        "recipient_group": "finance",
        "operation": "send-monthly-report",
    },
)
```

Cada chamada gera um `external_request_id` opaco. Retries da mesma tentativa
reutilizam a solicitação; uma chamada nova gera outra. Após aprovação, o backend
revalida tools, domínio e limites. A aprovação é consumida pela primeira ToolCall
executada. Rejeição lança `ApprovalRejectedError`; timeout lança
`ApprovalTimeoutError` e mantém a solicitação pendente. Depois de uma resposta
`REQUIRE_APPROVAL`, indisponibilidade nunca usa fail-open.

Para impedir a execução antes de chamar uma ferramenta:

```python
from agentops_monitor import AgentOps, ApprovalRequiredError, PolicyBlockedError

client = AgentOps(
    api_key="agom_sua_chave",
    endpoint="http://localhost:8000",
    agent_id=42,
    policy_fail_mode="closed",  # "open" executa se o serviço estiver indisponível
)

with client.trace("executar-busca") as trace:
    with trace.span("buscar", span_type="TOOL") as span:
        try:
            resultado = span.run_tool(
                "web_search", buscar, "agent policies",
                target_url="https://search.example.com",
            )
        except (PolicyBlockedError, ApprovalRequiredError):
            resultado = None
```

`span.check_tool()` retorna `ALLOW`, `BLOCK`, `REQUIRE_APPROVAL` ou o estado local
`UNAVAILABLE`. `span.run_tool()` nunca confunde indisponibilidade com permissão: no
modo `open` ele executa e registra `POLICY_UNAVAILABLE`; no modo `closed` ele lança
`PolicyUnavailableError` sem executar a função.

### Demo agent

```bash
cd examples/demo-agent
pip install -r requirements.txt
AGENTOPS_API_KEY=agom_... python agent.py
```

---

## Migrations

```bash
# Rodar no container:
docker exec agentops-monitor-backend-1 alembic upgrade head

# Ver histórico:
docker exec agentops-monitor-backend-1 alembic history
```

Migrations (ordem):
1. `0001_baseline` — schema base vazio
2. `0002_full_schema` — todas as tabelas
3. `0003_auth_columns` — brute-force fields
4. `0004_agent_fields` — campos de budget/status
5. `0005_model_pricing` — tabela de preços + seed
6. `0006_security` — agent_policies, tool_approvals, security findings
7. `0007_evaluations` — expand evaluation tables
8. `0008_authoritative_pricing` — pricing por organização, status e provenance de custo
9. `0009_tool_approval_runtime` — approval idempotente, consumo único e provenance

---

## Testes

```bash
# Backend
docker exec agentops-monitor-backend-1 pytest app/tests/ -v

# SDK
cd sdk-python
pip install -e ".[dev]"
pytest tests/ -v
```

---

## Arquitetura de ingestão

```
Agent → SDK → /ingest
                │
                ├── validação de organização/projeto/agente/ambiente
                ├── scan estrutural de payloads
                ├── redação de PII, tokens e secrets antes do storage
                ├── persistência do trace/span/tool/event sanitizado
                ├── criação de SecurityFinding com evidência segura
                └── agregação monotônica de Trace.risk_level
```

### Fluxo de custos

```text
ModelCall (provider + model + tokens + occurred_at)
  → resolução de pricing versionado (override da organização ou default global)
  → cálculo Decimal no backend
  → ModelCall.estimated_cost (nome legado, valor autoritativo)
  → CostRecord com snapshot das tarifas e da vigência
  → totais da trace e analytics por modelo, projeto e agente
```

O `estimated_cost` enviado por clientes antigos continua aceito, mas é ignorado
no cálculo e na persistência do custo. Se não houver preço aplicável, a chamada
e seus tokens são preservados com status `UNPRICED`; um preço configurado como
zero produz status `PRICED` e custo zero. Assim, ausência de configuração não é
apresentada como uso gratuito.

As linhas incluídas pela migration de seed são entradas de demonstração/default.
Elas não formam um catálogo atualizado automaticamente e não são garantia dos
preços atuais dos providers. Pricing é versionado e configurável por vigência.

---

## Limitações

- Providers reais (OpenAI, Anthropic) nas avaliações requerem integração adicional
- Alertas não são criados automaticamente pelo enforcement de políticas
- Notificações externas (Slack, email) estão preparadas na estrutura mas não implementadas
- SSO (SAML/OIDC) não implementado nesta versão
- Streaming de ingestão não suportado (batches recomendados para alto volume)
- Encryption at rest é responsabilidade da camada de infraestrutura

---

## Documentação

| Arquivo | Conteúdo |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Stack, topologia, data flow |
| [PYTHON_SDK.md](docs/PYTHON_SDK.md) | SDK installation, usage, resilience |
| [SECURITY.md](docs/SECURITY.md) | Scanner, policies, multi-tenancy |
| [EVALUATIONS.md](docs/EVALUATIONS.md) | Datasets, evaluators, comparison |
| [LGPD_AND_PRIVACY.md](docs/LGPD_AND_PRIVACY.md) | Data map, retention, subject rights |
| [ROADMAP.md](docs/ROADMAP.md) | v0.2 → v1.0 planned features |

---

## Licença

MIT
