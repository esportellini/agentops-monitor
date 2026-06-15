# LinkedIn Post

---

Nos últimos meses, construí do zero uma plataforma de observabilidade para agentes de IA — o AgentOps Monitor.

A motivação foi simples: agentes que chamam ferramentas, fazem múltiplas chamadas de modelo e processam dados sensíveis precisam de visibilidade operacional. Logs convencionais não são suficientes.

**O que o sistema faz:**

Cada execução de agente gera um trace completo com spans hierárquicos, tool calls, model calls com contagem de tokens e custo, e o input/output em cada etapa. Tudo isso fica disponível para análise em tempo real.

A plataforma inclui:
- SDK Python para instrumentar qualquer agente com 3 linhas de código
- Pipeline de ingestão via API key, separado da API administrativa
- Cálculo de custos configurável por provider/modelo com janela de vigência
- Scanner de segurança baseado em regras (regex, Luhn, validação de CPF) — sem depender exclusivamente de IA para detectar dados sensíveis
- Sistema de políticas por agente: ferramentas permitidas, limites de custo, domínios bloqueados, redação de PII
- Alertas configuráveis via condições estruturadas (sem eval())
- Sistema de avaliações offline com avaliadores determinísticos para comparar versões de agentes
- Auditoria imutável de todos os eventos relevantes
- Suporte a LGPD: mapa de dados, retenção configurável, anonimização, exportação de dados do titular
- Multi-tenancy com RBAC em 5 níveis

**Stack:** FastAPI, SQLAlchemy async, PostgreSQL, Redis, Next.js 14, TypeScript, Docker.

**O que aprendi:**

O desafio mais interessante foi equilibrar observabilidade com privacidade. Você quer ver o que o agente está fazendo, mas não quer que dados sensíveis dos usuários fiquem expostos em logs. A solução foi um scanner de redação que roda antes do armazenamento, políticas configuráveis por agente, e user_references sempre anonimizados.

Outra decisão importante: avaliadores determinísticos em vez de só usar LLM como juiz. Correspondência exata, presença de palavras, estrutura JSON, ferramentas esperadas, limites de custo e latência — tudo avaliável sem chamada de API.

O projeto ainda tem limitações (providers reais nas avaliações, notificações externas, SSO) que estão no roadmap.

Se você desenvolve ou opera sistemas com agentes de IA em produção, observabilidade estruturada faz diferença para depuração, controle de custos e auditoria.

Código disponível no repositório. Feedbacks são bem-vindos.

#AI #MLOps #Python #Observability #FastAPI #NextJS

---
