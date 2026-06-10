# AI Module Architecture

## Phase 2 runtime (`AIOrchestrator`)

```
POST /ai/chat
  → detect_intent
  → load_memory
  → select_prompt (role-aware + filtered tools)
  → OpenAI chat_with_tools (strict registry only)
  → plan_tools (single pass, max 5)
  → execute_tool × N (permissions → safety → confirmation → executor → ERP service)
  → build_response
  → store_memory + audit
```

Handlers live in `app/ai/tools/handlers/` and call `ExpenseService`, `ApprovalService`, `AnalyticsService` only.

## Phase 3 employee copilot + deep memory

- **ReferenceResolver** (`resolution/`): temporal/entity aliases (`same as yesterday`, `that expense`) → structured fields.
- **ConversationStateMachine** (`conversation/`): multi-turn slot filling without extra GPT calls.
- **WorkflowContinuityService** (`workflow/continuity.py`): resume drafts via Redis + ERP `DRAFT` rows.
- **UserPreferenceService** (`preferences/`): vendors, payment methods, categories in Redis long-term memory with importance scores.
- **WorkflowEntityGraph** (`graph/`): lightweight expense↔vendor↔payment↔category links in Redis long-term memory.
- **MemoryDecayService** (`memory/decay_service.py`): expire stale intents, purge expired rows, workflow TTL hygiene.
- **ContextScopeFilter** (`memory/context_scope.py`): expense vs approval vs reimbursement context isolation.
- **CopilotPreflight** (`copilot/preflight.py`): orchestrates decay → continuity → slots → enriched partitions.
- **Enterprise tone** (`prompts/personality.py` + post-processor): professional responses, no emoji/hype.

## Phase 3 memory intelligence

- **Conflict resolution** (`memory/conflict_resolver.py`): confidence decay + preference evolution when signals conflict (e.g. UPI vs credit card).
- **Noise suppression** (`memory/noise_suppression.py`): weighted observations, draft down-weighting, min evidence before prompts.
- **Memory explanations** (`memory/explanations.py`): transparent rationale in prompts and `[MEMORY RATIONALE]` context.
- **Soft forgetting** (`memory/soft_forgetting.py` + `decay_service.py`): importance half-life decay; hard expire only ephemeral types.
- **Workflow recovery** (`workflow/recovery.py`): safe prompts for stale slot-filling, interrupted submit, expired confirmations.

## Memory governance APIs (`/ai/memory/*`)

| Endpoint | Purpose |
|----------|---------|
| `GET /ai/memory/explanations` | Why suggestions exist (trust/debug) |
| `GET /ai/memory/confidence` | Confidence scores + candidate breakdown |
| `GET /ai/memory/audit` | Preference change history with evidence |
| `GET/PUT /ai/memory/policy` | Tenant sandbox (admin) |
| `GET /ai/memory/anomalies` | Payment/vendor/submission anomaly signals |

Migration: `app/migrations/add_ai_memory_governance.py`

## Phase 4 — Voice + Receipt Intelligence

### Voice pipeline
- `POST /intelligence/voice/transcribe` — async Whisper (OpenAI)
- `POST /intelligence/voice/chat` — transcribe → `AIOrchestrator`
- `voice_transcription_audits` table for audit logs
- Language hint via form field `language` (ISO-639-1)

### Receipt pipeline
- `POST /intelligence/receipt/scan` — async OCR + fraud + autofill
- `POST /intelligence/receipt/scan-sync` — dev synchronous path
- `POST /intelligence/receipt/{expense_id}/confirm-review` — human OCR confirmation
- **OCR providers** (`BaseOCRProvider`): `paddleocr` (default), `tesseract` (legacy alias), `gpt4o_vision`, `textract`, `google_vision` via `OCR_PROVIDER` env
- **Multi-page PDF**: `PdfReceiptAggregator` stitches page totals before entity scoring
- **Duplicate detection**: exact file hash + semantic similarity (invoice ID, amount, vendor, date)
- **Human review**: low confidence / fraud / clarify fields → `requires_human_review` + `review_token` (no silent auto-use)
- `ReceiptFraudChecker`: semantic duplicate, future date, invoice ID dup, amount consistency
- `ReceiptAutofillService`: memory preferences + vendor matching

### Voice safety (pre–Phase 5)
- `AudioUploadValidator`: size, MIME, magic bytes, duration cap, blocked payloads
- `VoiceSessionFlags` (Redis): marks voice-originated sessions
- `VoiceCommandSafety`: financial tools never auto-execute on voice; explicit confirmation required
- Config: `VOICE_MAX_DURATION_SECONDS`, `VOICE_ALLOWED_MIME_TYPES`, `OCR_HUMAN_REVIEW_THRESHOLD`

### Async jobs
- `processing_jobs` table + Celery worker (`docker-compose` service `celery_worker`)
- `GET /intelligence/jobs/{id}` — poll status
- Inline fallback if Celery broker unavailable

Migration: `app/migrations/add_phase4_intelligence.py`

## Phase 5 — Manager Copilot

Manager/department-head/finance roles get approval intelligence via `POST /ai/chat` and tools in `app/manager/`.

| Service | Path | Role |
|---------|------|------|
| `ApprovalInsightService` | `approval_insight.py` | Queue summaries, grouped claims, flagged list |
| `BulkApprovalPlanner` | `bulk_planner.py` | Schema-bound filters → preview → confirmed batch |
| `PolicyExplanationService` | `policy_explanation.py` | Grounded "why flagged" from policy + risk |
| `ApprovalRiskEngine` | `risk_engine.py` | `risk_score` + `risk_flags` per claim |
| `ManagerAnalyticsService` | `analytics.py` | Team spend, delays, vendors, dept risk |
| `EscalationService` | `escalation.py` | manager → finance escalation chain |
| `ManagerMemoryService` | `memory.py` | Approval behavior in Redis long-term memory |
| `ManagerExecutionSafety` | `safety.py` | No auto-approve; bulk requires confirm |

### Manager tools

`approval.pending.v1`, `approval.flagged.v1`, `approval.explain.v1`, `approval.bulk_approve.v1`, `approval.bulk_reject.v1`, `analytics.team_spend.v1`, `analytics.department_risk.v1`, `analytics.approval_delays.v1`, `analytics.vendor_patterns.v1`, `escalation.create.v1`, `escalation.list.v1`

Bulk flow: `preview_only=true` → user confirms → `preview_only=false` + `approval_ids` + `idempotency_key` (orchestrator confirmation gate).

### Phase 5 improvements

| Feature | Module | API |
|---------|--------|-----|
| Dry-run export (CSV/HTML/PDF-print) | `dry_run_export.py` | `approval.bulk_export.v1`, `POST /manager/bulk-preview/export`, `GET /manager/bulk-preview/{id}/download` |
| Approval simulation | `simulation.py` | `approval.simulate.v1`, `POST /manager/approvals/simulate` |
| Risk explainability | `risk_explainability.py` | `approval.risk_explain.v1`, embedded in `approval.explain` |
| Queue prioritization | `prioritization.py` | Urgent-first on `approval.pending.v1` |
| Manager workload (Phase 6) | `workload_analytics.py` | `GET /manager/analytics/workload-delays` (finance) |

Migration: `app/migrations/add_phase5_manager_copilot.py` (`approval_escalations` table).

## Phase 6 — Finance Analytics (implemented)

Package: `app/finance/`

| Service | Module |
|---------|--------|
| `FinanceAnalyticsService` | `finance_analytics.py` — trends, categories, departments, quarters |
| `VendorIntelligenceService` | `vendor_intelligence.py` — top vendors, concentration, growth, spikes |
| `PolicyViolationAnalyticsService` | `policy_violations.py` — violations by dept/policy |
| `ReimbursementAgeingService` | `reimbursement_ageing.py` — pending, blocked, SLA risk |
| `ApprovalDelayAnalyticsService` | `approval_delays.py` — bottlenecks, queue health |
| `ForecastingSeedService` | `forecasting_seed.py` — moving avg, MoM, seasonal (no ML) |

### Finance AI tools

`analytics.monthly_spend.v1`, `analytics.department_trends.v1`, `analytics.category_breakdown.v1`, `analytics.vendor_breakdown.v1`, `analytics.policy_violations.v1`, `analytics.approval_delays.v1`, `analytics.reimbursements.v1`, `analytics.forecast_seed.v1`

REST: `GET /finance/analytics/*` — see `app/routers/finance.py`

## Pre-Phase 7 — Analytics platform (implemented)

See [`app/finance/PRE_PHASE7.md`](../finance/PRE_PHASE7.md).

| Capability | Module |
|------------|--------|
| Redis analytics cache | `cache.py`, `services.py` (`FinanceAnalyticsFacade`) |
| Async finance exports | `report_generator.py`, `tasks/report_tasks.py` |
| Historical snapshots | `snapshots.py`, `models.py` → `analytics_snapshots` |
| KPI alerting | `kpi_alerts.py` → `kpi_alerts` |
| Forecast explainability (seed) | `forecast_explainability.py` |

Migration: `app/migrations/add_pre_phase7_analytics.py`

### Executive hardening (pre–Phase 7 rollout)

| Capability | Module |
|------------|--------|
| Immutable snapshots + content hash | `snapshot_immutability.py`, `events.py` |
| Report download audit | `report_audit.py` |
| Alert priority tiers | `alert_priority.py` |
| Alert correlation (seed) | `alert_correlation.py` |
| Report versions (`executive_pack_v1`) | `report_versions.py` |

Migration: `app/migrations/add_pre_phase7_executive_hardening.py`

## Phase 7 — Executive AI Insights (implemented)

Package: `app/executive/` — see [`PHASE7.md`](../executive/PHASE7.md)

| Service | Purpose |
|---------|---------|
| `FinancialHealthService` | Quarter spend, drivers, SLA, policy trends |
| `OperationalRiskSummaryService` | Reimbursement, SLA, policy, KPI risks |
| `ExecutiveDashboardService` | Board KPI panel |
| `OrganizationEfficiencyService` | Efficiency score + bottlenecks |
| `StrategicRecommendationService` | Rule-based strategic actions |
| `ExecutiveInsightService` | Full executive pack |
| `ExecutiveNarrativeService` | Grounded executive prose |

### Executive AI tools

`executive.financial_health.v1`, `executive.operational_risk.v1`, `executive.kpi_summary.v1`, `executive.vendor_growth.v1`, `executive.department_efficiency.v1`, `executive.forecast_summary.v1`, `executive.executive_pack.v1`, `executive.strategic_recommendations.v1`

REST: `GET /executive/*` — `app/routers/executive.py`

Finance admin / super admin use `executive_prompt_v1`.

### Phase 6+ roadmap (stubs)

See [`app/manager/FUTURE_ROADMAP.md`](../manager/FUTURE_ROADMAP.md): forecasting, policy impact analytics, manager behavioral risk, export signatures, SLA breach prediction.

| Stub | Path |
|------|------|
| Spend forecasting | `forecasting.py` |
| Policy impact | `policy_impact.py` |
| Manager behavioral risk | `behavioral_risk.py` |
| Export signatures | `export_signatures.py` (wired into bulk export manifest when enabled) |
| SLA breach prediction | `sla_prediction.py` |

## Future intelligence roadmap

See [`app/intelligence/FUTURE_ROADMAP.md`](../intelligence/FUTURE_ROADMAP.md) for planned work:

| Item | Priority | Extension point |
|------|----------|-----------------|
| Receipt embedding fingerprints (visual similarity) | 🟠 Future | `receipt/fingerprint.py` |
| OCR explainability (why confidence is low) | 🟡 Future | `receipt/explainability.py` — rule-based phase 1 wired |
| Voice biometric safety | 🔵 Future advanced | `voice/biometric.py` — disabled |
| Multi-language OCR normalization | 🟠 Future | `receipt/locale_normalizer.py` |
| Human review queues (finance dashboard) | 🟠 Future | `receipt/review_queue.py` |

## Phase 3 conversational intelligence (pre-production)

- **Argument repair** (`argument_repair.py`): `two thousand` → `2000`, enum fixes, type coercion — no GPT retry.
- **Memory ranking** (`memory_ranker.py`): recency + semantic + workflow + unresolved scoring.
- **Context partitions** (`context_partition.py`): `[SYSTEM]`, `[SESSION SUMMARY]`, `[ACTIVE WORKFLOW]`, messages, `[TOOL OUTPUTS]`.
- **Response post-processor** (`postprocessing/`): currency formatting, ungrounded ID stripping, tool mention checks.
- **Dead letter queue** (`dead_letter/`, `GET /ai/dead-letter`): failed financial jobs with retry visibility.

## Data flow (mandatory)

```
User → API → AIOrchestrator → ToolExecutionPolicy → Tool handler
                                              → Service layer → AIRepository → Redis
OpenAI ← AIOrchestrator (read-only context; conversation/memory persisted via Redis)
```

**Never:** `AI → SQL` or `OpenAI client → Repository`

## Compliance

- All prompts/responses are sanitized via `sanitize_prompt()` / `sanitize_response()` before Redis or audit storage.
- Audit payloads strip secrets and PII patterns (email, phone, GSTIN, card, bank account).

## Resilience

- **Redis unavailable:** AI chat and memory use PostgreSQL; optional Redis cache is skipped when `REDIS_ENABLED=false` or Redis is down.
- **Primary model down:** `OpenAIService` falls back to `OPENAI_FALLBACK_MODEL`.

## Human confirmation (CRITICAL)

Financial tools never execute without confirmation:

```json
{
  "requires_confirmation": true,
  "confirmation_token": "uuid"
}
```

Flow: `propose_tool` → user sees summary → user says "Yes" or `confirm_tool_execution(token)` → tool runs.

## Tool execution safety

- **Timeout:** every tool runs inside `asyncio.wait_for()` — default `MAX_TOOL_EXECUTION_SECONDS=15`.
- **Circuit breaker:** repeated failures open the circuit; tool returns `circuit_open` until recovery window passes.
- **Idempotency:** `expense.submit.v1`, `approval.submit.v1`, `reimbursement.submit.v1` require `idempotency_key` (stored in `ai_idempotency_keys`).
- **Versioning:** tools use `{domain}.{action}.v{N}` (e.g. `expense.create.v1`).

## Response classification

Every assistant reply is post-processed with `ResponseClassifier` → `SAFE` | `NEEDS_CLARIFICATION` | `BLOCKED` | `ACTIONABLE`. `BLOCKED` responses are replaced with a safe message before returning to the client.

## Tool results (Phase 2+)

All tools must return `app.ai.schemas.tool_result.ToolResult`:

```json
{
  "success": true,
  "message": "...",
  "data": {},
  "error": null,
  "audit_id": "123"
}
```

## Observability

Every orchestrator run sets `request_id` and `trace_id` (see `app.ai.observability`) on logs and Redis `ai:actions:*` entries.

## Session safety

`SessionLockManager` prevents concurrent conflicting operations per `tenant:user:session`.
