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
- Precificação configurável por provider + modelo + janela de vigência
- Custo por trace, agente, projeto, ambiente, modelo, período
- Projeção mensal com base na média diária
- Top traces mais caros

### Segurança
- Scanner de dados sensíveis baseado em regras (regex + Luhn + checksum CPF)
- Detecção de prompt injection (10 padrões)
- Políticas por agente: ferramentas permitidas/bloqueadas, limites de custo/token, domínios
- Aprovação humana de tool calls sensíveis
- Alertas configuráveis com condições estruturadas

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
            input_tokens=500, output_tokens=120, estimated_cost=0.0044)

    trace.set_output({"decisao": "pre_approval_required"})

client.flush()
```

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
Agent → SDK → POST /ingest/traces/start       (create trace)
            → POST /ingest/traces/{id}/spans  (add spans)
            → POST /ingest/spans/{id}/model-calls
            → POST /ingest/traces/{id}/finish (aggregate cost + status)
                    │
                    ├── Security scanner
                    │     ├── PII detection (email, CPF, phone, card)
                    │     ├── Secret detection (API keys, tokens)
                    │     ├── Prompt injection (10 patterns)
                    │     └── SQL injection
                    │
                    ├── Cost calculation
                    │     └── model_pricing lookup by provider+model+date
                    │
                    └── Alert evaluation
                          └── Structural conditions (no eval())
```

---

## Limitações

- Providers reais (OpenAI, Anthropic) nas avaliações requerem integração adicional
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
