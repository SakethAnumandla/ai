# Expense workflow APIs — contract reference

Documentation for **Flutter expense workflow** endpoints. These routes are registered in `app/routers/expense_workflow.py` and `app/routers/wallet.py` (`/wallet/budget-utilisation`).

| Environment | Base URL |
|-------------|----------|
| **Production** | `https://api.bizwy.in` |
| **Local** | `http://127.0.0.1:8000` |

**Production deploy note:** Until the backend from [bixwy_expense_backend](https://github.com/Abhinav689/bixwy_expense_backend) is redeployed, these paths return **HTTP 404** on production. Legacy substitutes that return **200** today are listed in [WORKFLOW_PRODUCTION_STATUS.md](./WORKFLOW_PRODUCTION_STATUS.md).

**Auth (current):** Routes using `get_current_user` resolve to the dev user `devuser` when no JWT is sent. Production may add real auth later; send the same headers your gateway expects.

---

## Quick index

| Method | Path | Section |
|--------|------|---------|
| GET | `/categories/business/hierarchy` | [1](#1-get-categoriesbusinesshierarchy) |
| GET | `/expenses/approvers/directory` | [2](#2-get-expensesapproversdirectory) |
| GET | `/expenses/approvals/pending` | [3](#3-get-expensesapprovalspending) |
| GET | `/expenses/{expense_id}/approval-workflow` | [4](#4-get-expensesexpense_idapproval-workflow) |
| POST | `/expenses/approvals/{approval_id}/action` | [5](#5-post-expensesapprovalsapproval_idaction) |
| GET | `/budgets/monthly` | [6](#6-get-budgetsmonthly) |
| GET | `/wallet/budget-utilisation` | [7](#7-get-walletbudget-utilisation) |
| GET | `/dashboard/export-by-fy` | [8](#8-get-dashboardexport-by-fy) |

---

## Common error responses

| HTTP | When | Body shape |
|------|------|------------|
| **404** | Route not deployed, or expense not found / not visible | `{"detail": "Not Found"}` or `{"detail": "Expense not found"}` |
| **400** | Validation / business rule (`ValueError`) | `{"detail": "<message>"}` |
| **422** | Invalid query/body (FastAPI/Pydantic) | `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` |
| **405** | Wrong HTTP method | `{"detail": "Method Not Allowed"}` |

---

## 1. GET `/categories/business/hierarchy`

**Full URL:** `https://api.bizwy.in/categories/business/hierarchy`

### Input

| Type | Name | Required | Validation |
|------|------|----------|------------|
| — | — | — | No query or body |

### Output `200` — JSON

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `currency` | string | yes | Default `"EUR"` |
| `monthly_budget_target` | number | yes | `1000000.0` (€1M / month) |
| `financial_years` | string[] | yes | e.g. `["FY2025-26", "FY2026-27"]` |
| `main_categories` | array | yes | Business taxonomy tree |

Each `main_categories[]` item:

| Field | Type | Required |
|-------|------|----------|
| `value` | string | yes | e.g. `people_hr` |
| `label` | string | yes |
| `icon` | string | no |
| `color` | string | no | Hex color |
| `subcategories` | array | yes |

Each `subcategories[]` item:

| Field | Type | Required |
|-------|------|----------|
| `value` | string | yes |
| `label` | string | yes |
| `line_items` | array | yes |

Each `line_items[]` item:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `value` | string | yes | |
| `label` | string | yes | |
| `gst_pct` | string \| null | no | e.g. `"18%"`, `"No"` |
| `itc_eligible` | string | no | `"Yes"` / `"No"` |
| `approval_roles` | string[] | no | e.g. `["Manager", "HOD"]` |
| `notes` | string \| null | no | |

### Example response

```json
{
  "currency": "EUR",
  "monthly_budget_target": 1000000.0,
  "financial_years": ["FY2025-26", "FY2026-27"],
  "main_categories": [
    {
      "value": "people_hr",
      "label": "People & HR Costs",
      "icon": "👥",
      "color": "#1565C0",
      "subcategories": [
        {
          "value": "salaries_wages",
          "label": "Salaries & Wages",
          "line_items": [
            {
              "value": "regular_salaries",
              "label": "Regular Salaries",
              "gst_pct": "No",
              "itc_eligible": "No",
              "approval_roles": ["Manager", "HOD", "HR"]
            }
          ]
        }
      ]
    }
  ]
}
```

**Flutter:** Used for manual bill category picker (same shape as hierarchy helpers in `api_service.dart`).

---

## 2. GET `/expenses/approvers/directory`

**Full URL:** `https://api.bizwy.in/expenses/approvers/directory`

### Input

None.

### Output `200` — JSON

| Field | Type | Required |
|-------|------|----------|
| `approvers` | array | yes |

Each `approvers[]` item:

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `id` | integer | yes | Directory ID (may not match DB user id in dev) |
| `role` | string | yes | `manager`, `hod`, `hr`, `director`, `finance`, `admin`, `it`, `ceo` |
| `name` | string | yes | |
| `title` | string | yes | Display title |
| `department` | string | no | |
| `approval_level` | string | no | `L1`, `L2`, `L3` |

### Example response

```json
{
  "approvers": [
    {
      "id": 101,
      "role": "manager",
      "name": "Priya S",
      "title": "Manager",
      "department": "Engineering",
      "approval_level": "L1"
    },
    {
      "id": 301,
      "role": "ceo",
      "name": "CEO Office",
      "title": "CEO",
      "department": "Executive",
      "approval_level": "L3"
    }
  ]
}
```

**Flutter:** `ApiService.getApproverDirectory()` — expects `data['approvers']` as a list.

---

## 3. GET `/expenses/approvals/pending`

**Full URL:** `https://api.bizwy.in/expenses/approvals/pending`

Returns expenses where the **current user** can act on the **next** pending step (sequential L1 → L2 → L3).

### Input

| Type | Name | Required | Validation |
|------|------|----------|------------|
| Header | (auth) | dev: optional | Uses `get_current_user` |

### Output `200` — JSON

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pending` | array | yes | Flat list of actionable items (one row per actionable step) |
| `count` | integer | yes | `len(pending)` |
| `groups` | array | yes | Full grouped queue for UI |
| `approvers` | array | yes | Same as approver directory |

#### `pending[]` item (flat)

| Field | Type | Required |
|-------|------|----------|
| `approval_id` | integer | yes | Use for POST action |
| `expense_id` | integer | yes |
| `expense_id_label` | string | yes | e.g. `EXP-0042` |
| `description` | string | yes | Bill name |
| `main_category` | string \| null | no |
| `sub_category` | string \| null | no |
| `line_item` | string \| null | no |
| `amount` | number | yes |
| `currency_code` | string | yes | Default `EUR` |
| `bill_date` | string \| null | no | ISO 8601 |
| `status` | string | yes | Step status, usually `pending` |
| `approval_level` | string \| null | no | Role key |
| `sequence_order` | integer | yes | 1, 2, or 3 |
| `approver_name` | string \| null | no |
| `approver_role_label` | string \| null | no |
| `submitted_by` | string | no |
| `submitted_by_name` | string \| null | no |
| `submitted_by_role` | string \| null | no |
| `stage_label` | string \| null | no | Human-readable stage |

#### `groups[]` item

| Field | Type | Required |
|-------|------|----------|
| `expense_id` | integer | yes |
| `expense_id_label` | string | yes |
| `description` | string | yes |
| `main_category` | string \| null | no |
| `sub_category` | string \| null | no |
| `line_item` | string \| null | no |
| `amount` | number | yes |
| `currency_code` | string | yes |
| `bill_date` | string \| null | no |
| `submitted_by` | string | no |
| `submitted_by_name` | string \| null | no |
| `submitted_by_role` | string \| null | no |
| `stage_label` | string \| null | no |
| `progress` | array | yes | Workflow progress nodes |
| `actionable_approval_id` | integer | yes |
| `steps` | array | yes | All steps with `is_actionable` flag |

#### `progress[]` item

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `key` | string | yes | `L1`, `L2`, `L3`, `final` |
| `label` | string | yes | |
| `approver` | string \| null | no | |
| `state` | string | yes | `done`, `active`, `pending`, `rejected` |
| `comments` | string \| null | no | |
| `acted_at` | string \| null | no | ISO datetime |

Final node has only `key`, `label`, `state` (no `approver`).

### Example response (abbreviated)

```json
{
  "pending": [
    {
      "approval_id": 15,
      "expense_id": 42,
      "expense_id_label": "EXP-0042",
      "description": "Team lunch",
      "main_category": "people_hr",
      "sub_category": "staff_welfare",
      "line_item": "team_meals",
      "amount": 2500.0,
      "currency_code": "EUR",
      "bill_date": "2026-06-01T00:00:00",
      "status": "pending",
      "approval_level": "manager",
      "sequence_order": 1,
      "approver_name": "Priya S",
      "approver_role_label": "Manager",
      "submitted_by": "Dev User",
      "stage_label": "Pending L1 (Manager) approval"
    }
  ],
  "count": 1,
  "groups": [],
  "approvers": []
}
```

**Flutter:** `getExpenseApprovalQueue()` — reads `pending`, `count`, `groups`, `approvers`.

**Not the same as** `GET /approvals/pending` (policy/claim approvals).

---

## 4. GET `/expenses/{expense_id}/approval-workflow`

**Full URL:** `https://api.bizwy.in/expenses/{expense_id}/approval-workflow`

### Input

| Type | Name | Required | Validation |
|------|------|----------|------------|
| Path | `expense_id` | yes | Positive integer |

User must be submitter, current approver, or a past approver on the expense.

### Output `200` — JSON

| Field | Type | Required |
|-------|------|----------|
| `expense_id` | integer | yes |
| `status` | string | yes | `draft`, `submitted`, `pending`, `approved`, `rejected` |
| `stage_label` | string \| null | no |
| `progress` | array | yes | Same structure as pending `progress` |
| `steps` | array | yes |

#### `steps[]` item

| Field | Type | Required |
|-------|------|----------|
| `id` | integer | yes | Approval step id (= `approval_id` for POST) |
| `level` | integer | yes | Sequence 1–3 |
| `sequence` | integer | yes | Same as `level` |
| `approver_name` | string \| null | no |
| `approver_role` | string \| null | no |
| `status` | string | yes | `pending`, `approved`, `rejected` |
| `comments` | string \| null | no |
| `acted_at` | string \| null | no | ISO datetime |

### Example response

```json
{
  "expense_id": 42,
  "status": "pending",
  "stage_label": "Pending L1 (Manager) approval",
  "progress": [
    { "key": "L1", "label": "Manager", "approver": "Priya S", "state": "active" },
    { "key": "L2", "label": "Head of Department", "state": "pending" },
    { "key": "final", "label": "Approved", "state": "pending" }
  ],
  "steps": [
    {
      "id": 15,
      "level": 1,
      "sequence": 1,
      "approver_name": "Priya S",
      "approver_role": "Manager",
      "status": "pending",
      "comments": null,
      "acted_at": null
    }
  ]
}
```

### Errors

| HTTP | `detail` |
|------|----------|
| 404 | `Expense not found` (missing or no access) |

**Flutter:** `getExpenseApprovalWorkflow(expenseId)`.

---

## 5. POST `/expenses/approvals/{approval_id}/action`

**Full URL:** `https://api.bizwy.in/expenses/approvals/{approval_id}/action`

### Input

| Type | Name | Required | Validation |
|------|------|----------|------------|
| Path | `approval_id` | yes | Integer — `ExpenseApproval.id` from pending/workflow |
| Body | `action` | yes | Regex: `approve` or `reject` only |
| Body | `comments` | conditional | **Required non-empty string when `action` is `approve`**; optional for `reject` |

**Content-Type:** `application/json`

### Request body schema

```json
{
  "action": "approve",
  "comments": "Verified against policy POL-001"
}
```

| Field | Type | Rules |
|-------|------|-------|
| `action` | string | Exactly `approve` or `reject` |
| `comments` | string \| null | Approve: required, trimmed non-empty. Reject: optional |

### Business validation (→ `400`)

| Message | Cause |
|---------|--------|
| `Approval step not found` | Invalid `approval_id` |
| `Expense not found` | Orphan step |
| `Expense is not awaiting approval` | Status not `submitted` / `pending` |
| `Earlier approval steps must be completed first` | Out-of-order action |
| `You are not authorized to act on this approval step` | Wrong user |
| `Approval comments are required` | `approve` without comments |
| `action must be approve or reject` | Invalid action |

### Output `200` — JSON

Returns full **`ExpenseResponse`** (same as `GET /expenses/{id}`) after commit.

Key fields clients should validate:

| Field | Type | Notes |
|-------|------|-------|
| `id` | integer | |
| `status` | string | `approved` or `rejected` after action |
| `approval_stage_label` | string \| null | |
| `approval_progress` | array | Updated chain |
| `approval_chain` | array | |
| `rejection_reason` | string \| null | Set on reject |
| `approved_at` | datetime \| null | Set when fully approved |
| `bill_amount`, `bill_name`, `bill_date` | | Unchanged unless reject updates status |

### Example response (truncated)

```json
{
  "id": 42,
  "user_id": 1,
  "bill_name": "Team lunch",
  "bill_amount": 2500.0,
  "status": "pending",
  "approval_stage_label": "L1 approved — waiting for L2 (Head of Department) approval",
  "approval_progress": [],
  "approved_at": null
}
```

**Flutter:** `expenseApprovalAction(approvalId, action: 'approve', comments: '...')`.

---

## 6. GET `/budgets/monthly`

**Full URL:** `https://api.bizwy.in/budgets/monthly?financial_year=FY2025-26`

### Input

| Type | Name | Required | Validation |
|------|------|----------|------------|
| Query | `financial_year` | no | Default `FY2025-26`. Pattern: `FY{start}-{end2}` e.g. `FY2025-26`, `FY2026-27`. Invalid → **400** |

### Output `200` — JSON

| Field | Type | Required |
|-------|------|----------|
| `financial_year` | string | yes |
| `months` | array | yes | 12 months (Apr–Mar FY) |
| `grand_total_actual` | number | yes | Sum of approved spend in FY |
| `grand_total_budget` | number | yes | `1000000 * 12` |
| `grand_utilisation_pct` | number | yes | |

#### `months[]` item

| Field | Type | Required |
|-------|------|----------|
| `month_label` | string | yes | e.g. `Apr 2025` |
| `year` | integer | yes |
| `month` | integer | yes | 1–12 |
| `budget_target` | number | yes | `1000000.0` per month |
| `actual` | number | yes | Approved expenses in month |
| `utilisation_pct` | number | yes | `(actual / target) * 100`, 1 decimal |
| `currency` | string | yes | `EUR` |

Spend filter: `status = approved`, `bill_date` in month, `user_id = current user`.

### Example response

```json
{
  "financial_year": "FY2025-26",
  "months": [
    {
      "month_label": "Apr 2025",
      "year": 2025,
      "month": 4,
      "budget_target": 1000000.0,
      "actual": 0.0,
      "utilisation_pct": 0.0,
      "currency": "EUR"
    }
  ],
  "grand_total_actual": 5000.0,
  "grand_total_budget": 12000000.0,
  "grand_utilisation_pct": 0.0
}
```

### Errors

| HTTP | `detail` example |
|------|------------------|
| 400 | `Invalid financial year label: FY1999` |

**Flutter:** `getMonthlyBudget(fy: 'FY2025-26')`.

**Legacy substitute (prod today):** `GET /dashboard/budget-vs-actual` — different JSON shape.

---

## 7. GET `/wallet/budget-utilisation`

**Full URL:** `https://api.bizwy.in/wallet/budget-utilisation`

### Input

None. Uses current UTC month for the authenticated user’s approved spend.

### Output `200` — JSON (always)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `currency` | string | yes | `EUR` |
| `budget_target` | number | yes | `1000000.0` |
| `month_label` | string | yes | e.g. `June 2026` |
| `current_month_actual` | number | yes | Approved spend this month |
| `current_utilisation_pct` | number | yes | |
| `show_previous_month_comparison` | boolean | yes | `false` in **April** (FY start) |

When `show_previous_month_comparison` is **true**, these fields are also present:

| Field | Type |
|-------|------|
| `previous_month_label` | string |
| `previous_month_actual` | number |
| `previous_utilisation_pct` | number |
| `utilisation_change_pct` | number | Current util % minus previous |
| `expenditure_change_pct` | number | Month-over-month spend % change |

### Example (non-April)

```json
{
  "currency": "EUR",
  "budget_target": 1000000.0,
  "month_label": "June 2026",
  "current_month_actual": 5000.0,
  "current_utilisation_pct": 0.5,
  "show_previous_month_comparison": true,
  "previous_month_label": "May 2026",
  "previous_month_actual": 12000.0,
  "previous_utilisation_pct": 1.2,
  "utilisation_change_pct": -0.7,
  "expenditure_change_pct": -58.3
}
```

### Example (April — no prior month block)

```json
{
  "currency": "EUR",
  "budget_target": 1000000.0,
  "month_label": "April 2026",
  "current_month_actual": 0.0,
  "current_utilisation_pct": 0.0,
  "show_previous_month_comparison": false
}
```

**Flutter:** `getBudgetUtilisation()` in `api_service.dart`.

---

## 8. GET `/dashboard/export-by-fy`

**Full URL:** `https://api.bizwy.in/dashboard/export-by-fy?financial_year=FY2025-26&group_by=month`

### Input

| Type | Name | Required | Validation |
|------|------|----------|------------|
| Query | `financial_year` | **yes** | `FY2025-26` or `FY2026-27` |
| Query | `group_by` | no | Default `month`. Must be `month` or `category` |

### Output `200` — JSON

| Field | Type | Required |
|-------|------|----------|
| `financial_year` | string | yes |
| `group_by` | string | yes | `month` or `category` |
| `groups` | object | yes | Keys = `YYYY-MM` or main category value; values = row arrays |

#### Export row (`groups` values[])

| Field | Type |
|-------|------|
| `expense_id` | string | `EXP-0042` |
| `bill_name` | string |
| `bill_date` | string \| null | ISO |
| `financial_year` | string |
| `main_category` | string \| null |
| `sub_category` | string \| null |
| `line_item` | string \| null |
| `vendor_name` | string \| null |
| `amount_excl_gst` | number \| null |
| `gst_rate_pct` | number \| null |
| `gst_amount` | number \| null |
| `total_amount` | number |
| `currency_code` | string |
| `itc_eligible` | boolean \| null |
| `payment_method` | string \| null |
| `hashtags` | string[] |
| `status` | string |
| `approved_at` | string \| null |

Only **approved** expenses in the FY window for the current user.

### Example

```json
{
  "financial_year": "FY2025-26",
  "group_by": "month",
  "groups": {
    "2026-06": [
      {
        "expense_id": "EXP-0042",
        "bill_name": "Travel",
        "bill_date": "2026-06-01T00:00:00",
        "total_amount": 5000.0,
        "currency_code": "EUR",
        "status": "approved"
      }
    ]
  }
}
```

---

## cURL smoke tests

```bash
BASE="https://api.bizwy.in"

curl -s "$BASE/health"
curl -s "$BASE/expenses/approvers/directory"
curl -s "$BASE/expenses/approvals/pending"
curl -s "$BASE/budgets/monthly?financial_year=FY2025-26"
curl -s "$BASE/wallet/budget-utilisation"
curl -s "$BASE/expenses/1/approval-workflow"

curl -s -X POST "$BASE/expenses/approvals/1/action" \
  -H "Content-Type: application/json" \
  -d '{"action":"approve","comments":"OK for June travel"}'
```

Local: replace `BASE` with `http://127.0.0.1:8000`.

Automated script: `scripts/test_chat_and_workflow_apis.py`.

---

## Related files

| File | Role |
|------|------|
| `app/routers/expense_workflow.py` | Route handlers |
| `app/services/expense_approval_service.py` | Approval logic |
| `app/services/budget_service.py` | Wallet budget utilisation |
| `app/data/business_taxonomy.py` | Directory + hierarchy constants |
| `bizwy_frontend_business/.../api_service.dart` | Flutter client paths |

See also: [WORKFLOW_PRODUCTION_STATUS.md](./WORKFLOW_PRODUCTION_STATUS.md).
