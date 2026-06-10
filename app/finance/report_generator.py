"""Large finance report generation — CSV/JSON exports for async jobs."""
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai.security import resolve_tenant_id
from app.config import settings
from app.finance.report_versions import resolve_report_spec
from app.finance.services import FinanceAnalyticsFacade
from app.models import User

logger = logging.getLogger(__name__)


class FinanceReportGenerator:
    """Build downloadable finance exports under upload_dir/finance_reports/."""

    def __init__(self, db: Session, base_dir: Optional[str] = None):
        self._db = db
        self._facade = FinanceAnalyticsFacade(db)
        root = base_dir or settings.upload_dir
        self._root = Path(root) / "finance_reports"
        self._root.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        user: User,
        *,
        report_type: str,
        job_id: int,
        export_format: str = "csv",
        months: int = 3,
        quarters: int = 1,
        department: Optional[str] = None,
        limit: int = 50,
        report_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        tenant_id = resolve_tenant_id(user)
        spec = resolve_report_spec(report_type=report_type, report_version=report_version)
        report_type = spec["report_type"]
        batch_dir = self._root / str(user.id) / str(job_id)
        batch_dir.mkdir(parents=True, exist_ok=True)

        data = self._fetch_report_data(
            user,
            tenant_id,
            report_type,
            months=months,
            quarters=quarters,
            department=department,
            limit=limit,
        )

        json_path = batch_dir / "report.json"
        json_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

        files = {"json": str(json_path)}
        if export_format in ("csv", "both"):
            csv_path = batch_dir / "report.csv"
            self._write_csv(csv_path, report_type, data)
            files["csv"] = str(csv_path)

        manifest = {
            "job_id": job_id,
            "report_type": report_type,
            "report_version": spec["report_version"],
            "schema_version": spec["schema_version"],
            "sections": spec.get("sections", []),
            "export_format": export_format,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
            "row_count": self._row_count(report_type, data),
        }
        manifest_path = batch_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        manifest["manifest_path"] = str(manifest_path)
        return manifest

    def _fetch_report_data(
        self,
        user: User,
        tenant_id: int,
        report_type: str,
        *,
        months: int,
        quarters: int,
        department: Optional[str],
        limit: int,
    ) -> Dict[str, Any]:
        if report_type == "spend_trends":
            return self._facade.spend_trends(
                user, tenant_id, quarters=quarters, department=department
            )
        if report_type == "vendor_breakdown":
            return self._facade.top_vendors(
                user, tenant_id, limit=limit, months=months
            )
        if report_type == "department_analysis":
            return self._facade.department_analysis(user, tenant_id, months=months)
        if report_type == "executive_pack":
            return {
                "spend_trends": self._facade.spend_trends(
                    user, tenant_id, quarters=quarters, department=department
                ),
                "vendors": self._facade.top_vendors(
                    user, tenant_id, limit=15, months=months
                ),
                "departments": self._facade.department_analysis(
                    user, tenant_id, months=months
                ),
                "policy": self._facade.policy_violations(user, tenant_id, months=months),
                "approval_health": self._facade.approval_health(user, tenant_id),
            }
        raise ValueError(f"Unknown report type: {report_type}")

    def _write_csv(self, path: Path, report_type: str, data: Dict[str, Any]) -> None:
        rows = self._tabular_rows(report_type, data)
        if not rows:
            path.write_text("section,key,value\nsummary,empty,true\n", encoding="utf-8")
            return
        fieldnames = list(rows[0].keys())
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _tabular_rows(self, report_type: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if report_type == "vendor_breakdown":
            return [
                {
                    "vendor": v.get("vendor"),
                    "total": v.get("total"),
                    "count": v.get("count"),
                    "share_pct": v.get("share_pct"),
                }
                for v in data.get("vendors", [])
            ]
        if report_type == "department_analysis":
            return data.get("departments", [])
        if report_type == "spend_trends":
            return data.get("mom_changes", [])
        if report_type == "executive_pack":
            rows = []
            for section, block in data.items():
                if isinstance(block, dict) and "total_spend" in block:
                    rows.append({
                        "section": section,
                        "metric": "total_spend",
                        "value": block.get("total_spend"),
                    })
            return rows
        return []

    def _row_count(self, report_type: str, data: Dict[str, Any]) -> int:
        rows = self._tabular_rows(report_type, data)
        if rows:
            return len(rows)
        if report_type == "executive_pack":
            return sum(
                len(b.get("vendors", b.get("departments", b.get("mom_changes", []))))
                if isinstance(b, dict)
                else 0
                for b in data.values()
            )
        return 1
