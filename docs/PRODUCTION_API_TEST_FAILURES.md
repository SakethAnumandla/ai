# Production API Test Failures

**Base URL:** `https://api.bizwy.in`  
**Test date:** 2026-06-10  
**Tool:** Postman collection run via Newman (CLI)  
**Collection:** `postman/Bizwy_Expense_API.postman_collection.json`

## Summary

| Metric | Result |
|--------|--------|
| Total requests | 143 |
| Passed (2xx) | 103 |
| Failed | 42 |
| Pass rate | 72% |

**Health check:** [`GET /health`](https://api.bizwy.in/health) — `200 OK` (database OK, OpenAI configured)

---

## Failed APIs (42)

### 400 Bad Request (5)

| # | Method | Endpoint | Notes |
|---|--------|----------|-------|
| 1 | POST | `/expenses/approvals/1/action` | Approval ID 1 invalid or wrong state |
| 2 | POST | `/approvals/1/action` | Same as above |
| 3 | POST | `/intelligence/voice/chat` | Missing audio file fixture |
| 4 | POST | `/intelligence/voice/transcribe` | Missing audio file fixture |
| 5 | POST | `/intelligence/voice/transcribe-sync` | Missing audio file fixture |

### 404 Not Found (28)

| # | Method | Endpoint | Notes |
|---|--------|----------|-------|
| 6 | DELETE | `/expenses/1` | Hardcoded seed ID not in production DB |
| 7 | GET | `/expenses/1` | Hardcoded seed ID |
| 8 | PATCH | `/expenses/1` | Hardcoded seed ID |
| 9 | GET | `/expenses/2/approval-workflow` | Hardcoded seed ID |
| 10 | POST | `/expenses/2/approve` | Hardcoded seed ID |
| 11 | GET | `/expenses/1/details` | Hardcoded seed ID |
| 12 | POST | `/expenses/3/discard` | Hardcoded seed ID |
| 13 | GET | `/expenses/1/file` | Hardcoded seed ID |
| 14 | GET | `/expenses/5/files` | Hardcoded seed ID |
| 15 | POST | `/expenses/5/files` | Hardcoded seed ID |
| 16 | DELETE | `/expenses/5/files/1` | Hardcoded seed ID |
| 17 | GET | `/expenses/5/files/1` | Hardcoded seed ID |
| 18 | GET | `/expenses/5/files/1/thumbnail` | Hardcoded seed ID |
| 19 | POST | `/expenses/4/resubmit` | Hardcoded seed ID |
| 20 | POST | `/expenses/1/submit` | Hardcoded seed ID |
| 21 | GET | `/expenses/1/taxes` | Hardcoded seed ID |
| 22 | PUT | `/expenses/1/taxes` | Hardcoded seed ID |
| 23 | GET | `/expenses/5/thumbnail` | Hardcoded seed ID |
| 24 | GET | `/ocr/batch/1/drafts` | Batch ID 1 not found |
| 25 | GET | `/ocr/batch/1/status` | Batch ID 1 not found |
| 26 | GET | `/ocr/bills/1` | Bill ID 1 not found |
| 27 | GET | `/ocr/bills/1/file` | Bill ID 1 not found |
| 28 | GET | `/ocr/bills/1/preview` | Bill ID 1 not found |
| 29 | GET | `/claims/1` | Claim ID 1 not found |
| 30 | GET | `/approvals/claim/1/workflow` | Claim ID 1 not found |
| 31 | GET | `/manager/bulk-preview/00000000-0000-0000-0000-000000000001/download` | Export ID not found |
| 32 | GET | `/finance/snapshots/compare?a=1&b=2` | Snapshot IDs not found |
| 33 | GET | `/finance/snapshots/1` | Snapshot ID 1 not found |

### 409 Conflict (1)

| # | Method | Endpoint | Notes |
|---|--------|----------|-------|
| 34 | GET | `/finance/reports/2/download` | Report job not ready or conflict |

### 422 Unprocessable Entity (1)

| # | Method | Endpoint | Notes |
|---|--------|----------|-------|
| 35 | POST | `/ai/chat/upload` | Request validation error |

### 500 Internal Server Error (3)

| # | Method | Endpoint | Notes |
|---|--------|----------|-------|
| 36 | POST | `/ocr/scan` | Server error (~54s) — **production bug** |
| 37 | POST | `/ocr/scan-drafts` | Server error (~26s) — **production bug** |
| 38 | POST | `/intelligence/receipt/scan` | Server error (~37s) — **production bug** |

### Timeout — ESOCKETTIMEDOUT (2)

| # | Method | Endpoint | Notes |
|---|--------|----------|-------|
| 39 | POST | `/intelligence/receipt/scan-sync` | Exceeded 120s timeout |
| 40 | POST | `/intelligence/receipt/1/confirm-review` | Exceeded 120s timeout |

---

## Failure breakdown by cause

| Cause | Count | Affected APIs |
|-------|-------|---------------|
| Wrong/missing IDs in Postman environment | 28 | Expense, OCR, claims, snapshots, bulk-export |
| Real server bugs (OCR pipeline) | 3 | `/ocr/scan`, `/ocr/scan-drafts`, `/intelligence/receipt/scan` |
| Request timeouts (heavy OCR) | 2 | `scan-sync`, `confirm-review` |
| Missing audio test files | 3 | Voice endpoints |
| Invalid approval/action state | 2 | Approval action endpoints |
| Validation error | 1 | `/ai/chat/upload` |
| Report not ready | 1 | `/finance/reports/2/download` |

---

## Recommended fixes

1. **OCR pipeline (priority)** — Investigate and fix 500 errors on `/ocr/scan`, `/ocr/scan-drafts`, and `/intelligence/receipt/scan`.
2. **Postman environment** — Set `base_url` to `https://api.bizwy.in` and refresh IDs from live API responses instead of local seed values (`1`, `2`, `3`, etc.).
3. **Voice/upload fixtures** — Add audio files for voice endpoint tests; fix `/ai/chat/upload` payload validation.
4. **Heavy OCR endpoints** — Review performance/timeouts for `scan-sync` and `confirm-review` (may need longer timeout or optimization).

---

## Passed APIs (103)

All other endpoints in the collection returned `200`, `201`, or `204`, including:

- General & health (`/`, `/health`)
- Categories, tax, filters, payment modes
- Expense lists and creation (`GET /expenses`, `POST /expenses/manual`, etc.)
- Wallet (balance, summary, transactions)
- Dashboard (all 13 endpoints)
- Policies (CRUD, scan-ocr, types)
- Claims (list, submit, scan-ocr, summary)
- AI chat (except upload)
- Manager analytics
- Finance (alerts, analytics, report generation)
- Executive endpoints
