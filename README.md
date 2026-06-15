# bizwy_expense_backend_New

## API documentation

| Doc | Description |
|-----|-------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | **Layered backend structure** (routers → services → models) |
| [docs/EXPENSE_WORKFLOW_APIS.md](docs/EXPENSE_WORKFLOW_APIS.md) | Workflow endpoints — **input/output JSON**, validation, examples |
| [docs/WORKFLOW_PRODUCTION_STATUS.md](docs/WORKFLOW_PRODUCTION_STATUS.md) | Production **404 vs 200** on `https://api.bizwy.in` |
| [API_CURL.md](API_CURL.md) | Full cURL reference for all routes |

## AI copilot data (PostgreSQL)

Chat, long-term memory, summaries, audit logs, confirmations, idempotency, policies, and related AI tables are stored in **PostgreSQL** (see `app/ai/models/entities.py`).

**Recreate tables** after they were dropped (one-time):

```bash
docker compose run --rm --no-deps backend python app/migrations/recreate_ai_postgres_tables.py
```

**PostgreSQL** is the sole storage for chat, memory, drafts, workflow state, and related AI tables.

Main AI tables: `ai_conversations`, `ai_memory`, `ai_summaries`, `ai_actions`, `ai_memory_audit_events`, `ai_confirmations`, `ai_idempotency_keys`, `ai_model_config`, `ai_tool_permissions`, `ai_prompt_versions`, `ai_tenant_memory_policies`, `ai_job_dead_letters`, `tenant_ai_usage`.
# backend_new
