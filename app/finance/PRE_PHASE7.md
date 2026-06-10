# Pre-Phase 7 — Analytics Platform

Improvements before executive intelligence (Phase 7).

## 1. Analytics caching (IMPORTANT)

- **Module:** `app/finance/cache.py`, `app/finance/services.py` (`FinanceAnalyticsFacade`)
- **Redis keys:** `finance:analytics:{tenant}:{report}:{scope}:{hash}`
- **TTLs:** quarterly 1h, vendor/department 30m, default 15m (`config.py`)
- **REST:** all `GET /finance/analytics/*` routes use cache; `POST /finance/cache/invalidate` for admins

## 2. Async report generation (IMPORTANT)

- **Module:** `app/finance/report_generator.py`, `app/finance/tasks/report_tasks.py`
- **Job type:** `finance_report` — poll `GET /intelligence/jobs/{id}`
- **REST:** `POST /finance/reports/async` with `report_type`, `format`, filters
- **Output:** `uploads/finance_reports/{user_id}/{job_id}/` (JSON + CSV manifest)

## 3. Analytics snapshots (IMPORTANT)

- **Table:** `analytics_snapshots`
- **Module:** `app/finance/snapshots.py`
- **REST:**
  - `POST /finance/snapshots/capture`
  - `POST /finance/snapshots/executive-pack`
  - `GET /finance/snapshots`
  - `GET /finance/snapshots/compare?a=&b=`

## 4. KPI alerting (IMPORTANT)

- **Table:** `kpi_alerts`
- **Module:** `app/finance/kpi_alerts.py`
- **Types:** `budget_spike`, `policy_surge`, `sla_breach`
- **REST:** `GET /finance/alerts`, `POST /finance/alerts/evaluate`, `POST /finance/alerts/{id}/acknowledge`
- **Thresholds:** `KPI_ALERT_*` in `.env`

## 5. Forecast explainability (FUTURE — seed implemented)

- **Module:** `app/finance/forecast_explainability.py`
- **Wired into:** `ForecastingSeedService.forecast()` → `explanation` field when `FORECAST_EXPLAINABILITY_ENABLED=true`

---

## Executive hardening (before Phase 7 rollout)

### 6. Snapshot immutability (IMPORTANT)

- **Modules:** `snapshot_immutability.py`, `events.py` (SQLAlchemy guards)
- On capture: SHA-256 `content_hash`, `frozen_at`, `immutable=true`
- Executive pack snapshots: `is_executive=true`
- **Blocks:** UPDATE/DELETE on payload, summary, period, type (409 if tampered)
- **REST:** `GET /finance/snapshots/{id}` returns `integrity_verified`

### 7. Report access audit (IMPORTANT)

- **Table:** `finance_report_access_audits`
- **Module:** `report_audit.py`
- **REST:**
  - `GET /finance/reports/{job_id}/download?format=csv|json` — logs every download
  - `GET /finance/reports/access-audit` — finance admin audit trail

### 8. Alert priority tiers (IMPORTANT)

- **Module:** `alert_priority.py`
- Tiers: `critical` | `high` | `medium` | `low`
- Stored on `kpi_alerts.priority`; list sorted by priority
- Filter: `GET /finance/alerts?priority=critical`

### 9. KPI alert correlation (FUTURE — seed)

- **Module:** `alert_correlation.py`
- Enable: `KPI_ALERT_CORRELATION_ENABLED=true`
- `POST /finance/alerts/evaluate` returns `incidents[]` when multiple KPIs fire together

### 10. Report versioning (FUTURE — seed)

- **Module:** `report_versions.py`
- Default: `executive_pack_v1`
- **REST:** `GET /finance/reports/versions`
- Async job payload + manifest include `report_version`, `schema_version`

## Migrations

```bash
PYTHONPATH=. .venv/bin/python app/migrations/add_pre_phase7_analytics.py
PYTHONPATH=. .venv/bin/python app/migrations/add_pre_phase7_executive_hardening.py
```

## Celery

Include `app.finance.tasks.report_tasks` in worker (already in `celery_app.py` include list).
