# Workflow APIs — production status & 404 troubleshooting

Live checks against **[https://api.bizwy.in](https://api.bizwy.in)** (API root: `{"message":"Expense Tracker API","status":"running"}`).

**Root cause of 404s:** Production is still running an **older build** without `expense_workflow` routes. Code is on GitHub [`Abhinav689/bixwy_expense_backend`](https://github.com/Abhinav689/bixwy_expense_backend) `main` — **redeploy required**.

After deploy, re-run:

```powershell
$paths = @(
  "/expenses/approvers/directory",
  "/expenses/approvals/pending",
  "/wallet/budget-utilisation",
  "/budgets/monthly"
)
foreach ($p in $paths) {
  try {
    $r = Invoke-WebRequest "https://api.bizwy.in$p" -UseBasicParsing
    "200 $p"
  } catch {
    "$($_.Exception.Response.StatusCode.value__) $p"
  }
}
```

Or open `https://api.bizwy.in/openapi.json` and search for `approvers/directory`.

---

## Status matrix (Flutter workflow vs production)

| Status | Method | Production URL | Flutter / app usage |
|--------|--------|----------------|---------------------|
| **404** | GET | https://api.bizwy.in/expenses/approvers/directory | Approver directory |
| **404** | GET | https://api.bizwy.in/expenses/approvals/pending | Expense approval queue |
| **404** | GET | https://api.bizwy.in/expenses/{id}/approval-workflow | Approval tracker screen |
| **404** | POST | https://api.bizwy.in/expenses/approvals/{approval_id}/action | Approve / reject |
| **404** | GET | https://api.bizwy.in/budgets/monthly?financial_year=FY2025-26 | Monthly budget grid |
| **404** | GET | https://api.bizwy.in/wallet/budget-utilisation | Dashboard budget card |
| **404** | GET | https://api.bizwy.in/categories/business/hierarchy | Business taxonomy |
| **404** | GET | https://api.bizwy.in/dashboard/export-by-fy?financial_year=FY2025-26&group_by=month | FY export |

### What works on production today (200)

| Status | Method | Production URL | Notes |
|--------|--------|----------------|-------|
| **200** | GET | https://api.bizwy.in/health | |
| **200** | GET | https://api.bizwy.in/openapi.json | No workflow paths in spec |
| **200** | GET | https://api.bizwy.in/approvals/pending | **Policy claims** — not expense queue |
| **200** | GET | https://api.bizwy.in/dashboard/budget-vs-actual | Different from `/budgets/monthly` |
| **200** | GET | https://api.bizwy.in/dashboard/overview?period=this_month | Dashboard stats |
| **200** | GET | https://api.bizwy.in/wallet/summary | |
| **200** | GET | https://api.bizwy.in/wallet/balance | |

---

## Error response when route is missing (404)

**Request:** any missing route, e.g. `GET /expenses/approvals/pending`

**Response:**

```http
HTTP/1.1 404 Not Found
Content-Type: application/json
```

```json
{
  "detail": "Not Found"
}
```

**Flutter impact:** Dio throws; app may show empty queue or use `expense_approval_fallback.dart` for approvers.

---

## Error responses when route exists (after deploy)

Documented in [EXPENSE_WORKFLOW_APIS.md](./EXPENSE_WORKFLOW_APIS.md). Summary:

| Endpoint | Typical errors |
|----------|----------------|
| `GET .../approval-workflow` | **404** `Expense not found` |
| `POST .../action` | **400** business messages (comments required on approve, unauthorized, wrong order) |
| `GET /budgets/monthly` | **400** invalid `financial_year` |
| `GET /dashboard/export-by-fy` | **422** if `financial_year` omitted |

---

## Legacy vs new — do not confuse

| New (404 on prod) | Legacy (200 on prod) | Same data? |
|-------------------|----------------------|------------|
| `/expenses/approvals/pending` | `/approvals/pending` | **No** — claims/policies vs expenses |
| `/budgets/monthly` | `/dashboard/budget-vs-actual` | **No** — different JSON |
| `/wallet/budget-utilisation` | `/wallet/summary` | **No** |

`ApprovalApiService` uses `/approvals/pending` (policy). Expense screens use `/expenses/approvals/pending`.

---

## Expected status after redeploy

| URL | Expected |
|-----|----------|
| All eight workflow URLs above | **200** (empty arrays/objects OK) |
| `POST .../action` with invalid id | **400** or **404**, not route 404 |

---

## Full API contracts

Input/output JSON schemas, field validation, and examples:

**[EXPENSE_WORKFLOW_APIS.md](./EXPENSE_WORKFLOW_APIS.md)**
