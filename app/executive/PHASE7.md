# Phase 7 — Executive AI Insights

Strategic organizational intelligence (not infrastructure).

## Services (`app/executive/`)

| Service | Module | Purpose |
|---------|--------|---------|
| `ExecutiveInsightService` | `insights.py` | Board pack orchestration |
| `FinancialHealthService` | `financial_health.py` | Quarter health, drivers, SLA/policy |
| `OperationalRiskSummaryService` | `operational_risk.py` | Reimbursement, SLA, policy, KPI risks |
| `ExecutiveNarrativeService` | `narratives.py` | Executive prose from metrics |
| `ExecutiveDashboardService` | `dashboard.py` | KPI dashboard |
| `StrategicRecommendationService` | `strategic_recommendations.py` | Prioritized actions |
| `OrganizationEfficiencyService` | `efficiency.py` | Efficiency score + bottlenecks |

Built on Phase 6 `FinanceAnalyticsFacade` (cached analytics).

## AI tools

| Tool | Handler |
|------|---------|
| `executive.financial_health.v1` | Quarter financial health |
| `executive.operational_risk.v1` | Operational risks |
| `executive.kpi_summary.v1` | KPI dashboard |
| `executive.vendor_growth.v1` | Vendor growth + volume leader |
| `executive.department_efficiency.v1` | Dept efficiency (managers too) |
| `executive.forecast_summary.v1` | Predictive outlook |
| `executive.executive_pack.v1` | Full board pack |
| `executive.strategic_recommendations.v1` | Strategic recommendations |

## Roles

- **Finance admin / Super admin:** all executive tools + `executive_prompt_v1`
- **Manager / Department head:** `executive.department_efficiency.v1` only

## REST API (`/executive`)

- `GET /executive/financial-health`
- `GET /executive/operational-risks`
- `GET /executive/kpi-summary`
- `GET /executive/vendor-growth`
- `GET /executive/efficiency`
- `GET /executive/forecast-summary`
- `GET /executive/strategic-recommendations`
- `GET /executive/dashboard`
- `GET /executive/pack`

## Example prompts

- "Give me this quarter's financial health summary" → `executive.financial_health`
- "What are the biggest operational risks?" → `executive.operational_risk`
- "Which vendors are growing fastest?" → `executive.vendor_growth`
- "Where are we losing operational efficiency?" → `executive.department_efficiency`
