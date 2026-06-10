"""ExecutiveNarrativeService — board-ready KPI and insight narratives."""
from typing import Any, Dict, List, Optional


class ExecutiveNarrativeService:
    """Turn structured metrics into executive prose (grounded in tool data only)."""

    def financial_health_opening(self, data: Dict[str, Any]) -> str:
        qtr = data.get("quarter_change_pct")
        if qtr is None:
            return data.get("spend_narrative", "Financial health summary is available.")
        direction = "increased" if qtr > 0 else "decreased"
        if abs(qtr) < 2:
            lead = "Overall spend is relatively flat this quarter."
        else:
            lead = f"Overall spend {direction} {abs(qtr):.0f}% this quarter."
        drivers = data.get("top_drivers") or []
        if drivers:
            lead += f" Primary drivers: {', '.join(drivers[:3])}."
        return lead

    def sla_performance_line(self, sla: Dict[str, Any]) -> Optional[str]:
        health = sla.get("queue_health", "")
        overdue = sla.get("overdue_pct", 0)
        if health == "healthy":
            return "Approval SLA performance is within healthy thresholds."
        if health == "critical":
            return (
                f"Approval SLA performance is critical — {overdue:.0f}% of the queue is overdue."
            )
        at_risk = sla.get("sla_at_risk", {})
        count = at_risk.get("at_risk_count", 0) if isinstance(at_risk, dict) else 0
        if count:
            return f"{count} approval(s) are at risk of SLA breach within 24 hours."
        return f"Approval queue is degraded with {overdue:.0f}% overdue."

    def policy_trend_line(self, policy: Dict[str, Any]) -> Optional[str]:
        by_month = policy.get("by_month") or {}
        if len(by_month) < 2:
            return None
        months = sorted(by_month.keys())
        latest, prior = by_month[months[-1]], by_month[months[-2]]
        if prior <= 0:
            return None
        pct = round((latest - prior) / prior * 100, 1)
        if abs(pct) < 1:
            return "Policy violations are stable month-over-month."
        direction = "increased" if pct > 0 else "decreased"
        return f"Policy violations {direction} {abs(pct):.0f}% month-over-month."

    def operational_risk_bullets(self, risks: List[Dict[str, Any]]) -> List[str]:
        return [r.get("narrative") or r.get("title", "") for r in risks if r.get("narrative") or r.get("title")]

    def vendor_growth_lines(self, growth: List[Dict[str, Any]], top_volume: Optional[str] = None) -> List[str]:
        lines = []
        for v in growth[:3]:
            name = v.get("vendor", "Vendor")
            pct = v.get("growth_pct", 0)
            if pct > 0:
                lines.append(f"{name} spend increased {pct:.0f}% in the recent period.")
            elif pct < 0:
                lines.append(f"{name} spend decreased {abs(pct):.0f}% in the recent period.")
        if top_volume and not any(top_volume in ln for ln in lines):
            lines.append(f"{top_volume} remains the highest-volume vendor.")
        return lines

    def efficiency_summary(self, data: Dict[str, Any]) -> str:
        score = data.get("efficiency_score", 0)
        bottlenecks = data.get("top_bottlenecks") or []
        if not bottlenecks:
            return f"Organization efficiency score: {score}/100 — no major bottlenecks detected."
        names = ", ".join(b["department"] for b in bottlenecks[:2])
        return (
            f"Organization efficiency score: {score}/100. "
            f"Primary inefficiencies: approval and reimbursement friction in {names}."
        )

    def compose_executive_summary(self, sections: Dict[str, str]) -> str:
        parts = [v for v in sections.values() if v]
        return "\n\n".join(parts)

    def kpi_summary_paragraph(self, kpis: List[Dict[str, Any]]) -> str:
        if not kpis:
            return "No elevated KPI alerts at this time."
        lines = [f"• {k['label']}: {k['value']}" for k in kpis[:6]]
        return "Key performance indicators:\n" + "\n".join(lines)
