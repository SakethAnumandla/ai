# Backend architecture

This project follows a **layered (clean) architecture**. HTTP routes stay thin; business rules live in services; shared helpers stay in `utils/` and `data/`.

## Layer diagram

```
Client (Flutter / curl)
        │
        ▼
┌───────────────────┐
│  routers/         │  HTTP: params, auth Depends(), status codes, response_model
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  services/        │  Business logic, orchestration, DB queries, transactions
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  models.py        │  SQLAlchemy ORM entities
│  data/            │  Static taxonomy, constants
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  utils/           │  Pure helpers (dates, mappers, query builders)
│  domain/          │  Small domain schemas (avoid bloating schemas.py)
└───────────────────┘
```

## Folder roles

| Path | Responsibility |
|------|----------------|
| `app/routers/` | One file per API area. **No SQLAlchemy queries** except trivial wiring. |
| `app/services/` | `SomeService(db)` classes or module functions with business rules. |
| `app/utils/` | Reusable, stateless helpers (`dashboard_queries`, `expense_helpers`, `fiscal_year`). |
| `app/data/` | Business taxonomy, approver directory, budget constants. |
| `app/domain/` | Domain-specific Pydantic types (e.g. workflow request bodies). |
| `app/schemas.py` | Legacy shared request/response DTOs (split over time into `domain/`). |
| `app/dependencies.py` | FastAPI DI: auth, pagination, time-period filters. |
| `app/models.py` | ORM models (split by domain when refactored). |

## Refactor status

| Router | Status |
|--------|--------|
| `expense_workflow.py` | Done — services |
| `dashboard.py` | Done — `DashboardService`, `ExportService` |
| `wallet.py` | Done — `WalletReadService` |
| `expenses.py` | Done — `ManualExpenseService`, `ExpenseFileService`, `ExpenseAccessService` |
| `ocr.py` | Done — `OcrApiService` |
| `claims.py` | Done — `ClaimService` list/view helpers, `claim_response_service` |
| `approvals.py` | Thin already; optional: move pending query into `ClaimService` |

## Service map (expense module)

| Service | Used by | Purpose |
|---------|---------|---------|
| `ExpenseService` | `routers/expenses.py` | Expense CRUD, list, submit |
| `ManualExpenseService` | `routers/expenses.py` | Manual create + OCR prefill scan |
| `ExpenseFileService` | `routers/expenses.py` | File upload/download/delete |
| `ExpenseAccessService` | expenses, files | Viewer access + OCR bill lookup |
| `expense_approval_service` | workflow, expenses | L1→L3 approval workflow |
| `OcrApiService` | `routers/ocr.py` | OCR scan, batch reload, bill preview |
| `budget_service` | wallet, workflow | Budget utilisation + FY grid |
| `ExportService` | dashboard, workflow | FY export + period CSV/JSON |
| `DashboardService` | `routers/dashboard.py` | Dashboard analytics |
| `WalletService` | wallet mutations | Ledger update on approve |
| `WalletReadService` | `routers/wallet.py` | Transactions + period summary |
| `ClaimService` | claims, approvals | Policy claims + approvals |
| `claim_response_service` | `routers/claims.py` | Submit response builder |

## Running tests

```bash
cd expense_backend/expense_backend
python scripts/test_chat_and_workflow_apis.py
python scripts/test_all_apis.py
```

## Related docs

- [docs/EXPENSE_WORKFLOW_APIS.md](docs/EXPENSE_WORKFLOW_APIS.md) — API contracts
- [API_CURL.md](API_CURL.md) — Full endpoint cURL list
