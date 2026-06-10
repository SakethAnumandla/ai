"""Bulk approval dry-run export — CSV and printable HTML (PDF-ready)."""
import csv
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from app.config import settings
from app.manager.export_signatures import ExportSignatureService
from app.manager.schemas import ApprovalCandidate, BulkApprovalPreview


ExportFormat = Literal["csv", "html", "pdf"]


class BulkDryRunExporter:
    """Write exportable preview files under upload_dir/bulk_previews/."""

    def __init__(self, base_dir: Optional[str] = None):
        root = base_dir or settings.upload_dir
        self._root = Path(root) / "bulk_previews"
        self._root.mkdir(parents=True, exist_ok=True)

    def export_preview(
        self,
        *,
        user_id: int,
        preview: BulkApprovalPreview,
        action: str = "approve",
        export_format: ExportFormat = "csv",
    ) -> dict:
        export_id = str(uuid.uuid4())
        batch_dir = self._root / str(user_id) / export_id
        batch_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "export_id": export_id,
            "user_id": user_id,
            "action": action,
            "count": preview.count,
            "total_amount": preview.total_amount,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": {},
        }

        csv_path = batch_dir / "preview.csv"
        self._write_csv(csv_path, preview.candidates, action=action)
        manifest["files"]["csv"] = str(csv_path)

        html_path = batch_dir / "preview.html"
        self._write_html(html_path, preview, action=action)
        manifest["files"]["html"] = str(html_path)
        manifest["files"]["pdf"] = str(html_path)  # print-to-PDF from HTML

        if export_format == "csv":
            primary = manifest["files"]["csv"]
        else:
            primary = manifest["files"]["html"]

        csv_bytes = csv_path.read_bytes()
        manifest["signature"] = ExportSignatureService().sign_manifest(
            manifest,
            content_bytes=csv_bytes,
            exported_by=user_id,
        )

        manifest_path = batch_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return {
            "export_id": export_id,
            "format": export_format,
            "download_paths": manifest["files"],
            "download_hint": (
                f"GET /manager/bulk-preview/{export_id}/download?format=csv|html"
            ),
            "csv_content": self._csv_string(preview.candidates, action=action)
            if preview.count <= 100
            else None,
            "manifest": manifest,
        }

    def read_export(self, user_id: int, export_id: str, fmt: ExportFormat) -> Optional[tuple]:
        batch_dir = self._root / str(user_id) / export_id
        manifest_path = batch_dir / "manifest.json"
        if not manifest_path.exists():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if fmt == "csv":
            path = Path(manifest["files"]["csv"])
        elif fmt == "pdf":
            path = Path(manifest["files"].get("pdf") or manifest["files"]["html"])
        else:
            path = Path(manifest["files"]["html"])
        if not path.exists():
            return None
        media = "text/csv" if fmt == "csv" else "text/html"
        name = f"bulk_preview_{export_id[:8]}.{fmt if fmt != 'pdf' else 'html'}"
        return path.read_bytes(), media, name

    def _write_csv(self, path: Path, candidates: List[ApprovalCandidate], *, action: str) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "approval_id",
                "claim_id",
                "claim_number",
                "bill_name",
                "amount",
                "vendor",
                "category",
                "department",
                "submitter",
                "risk_score",
                "risk_flags",
                "proposed_action",
            ])
            for c in candidates:
                w.writerow([
                    c.approval_id,
                    c.claim_id,
                    c.claim_number,
                    c.bill_name,
                    c.bill_amount,
                    c.vendor_name or "",
                    c.main_category or "",
                    c.department or "",
                    c.submitter_name or "",
                    c.risk.risk_score,
                    ";".join(c.risk.risk_flags),
                    action,
                ])

    def _csv_string(self, candidates: List[ApprovalCandidate], *, action: str) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "approval_id", "claim_id", "claim_number", "bill_name", "amount",
            "vendor", "category", "risk_score", "risk_flags", "proposed_action",
        ])
        for c in candidates:
            w.writerow([
                c.approval_id, c.claim_id, c.claim_number, c.bill_name,
                c.bill_amount, c.vendor_name or "", c.main_category or "",
                c.risk.risk_score, ";".join(c.risk.risk_flags), action,
            ])
        return buf.getvalue()

    def _write_html(self, path: Path, preview: BulkApprovalPreview, *, action: str) -> None:
        rows = ""
        for c in preview.candidates:
            flags = ", ".join(c.risk.risk_flags) or "—"
            rows += f"""
            <tr>
              <td>{c.approval_id}</td>
              <td>{c.claim_number}</td>
              <td>{c.bill_name}</td>
              <td>₹{c.bill_amount:,.2f}</td>
              <td>{c.vendor_name or '—'}</td>
              <td>{c.main_category or '—'}</td>
              <td>{c.risk.risk_score:.0%}</td>
              <td>{flags}</td>
              <td>{action}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<title>Bulk {action} preview — dry run</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
  h1 {{ font-size: 1.25rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: left; }}
  th {{ background: #f4f4f4; }}
  .meta {{ margin-bottom: 1rem; color: #444; }}
  @media print {{ body {{ margin: 0.5rem; }} }}
</style></head>
<body>
  <h1>Bulk {action.title()} — Dry Run Preview</h1>
  <p class="meta">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} —
  {preview.count} claim(s), total ₹{preview.total_amount:,.2f},
  {preview.flagged_count} flagged, {preview.high_risk_count} high risk.</p>
  <p><strong>Not executed.</strong> For manager review only. Use browser Print → Save as PDF.</p>
  <table>
    <thead><tr>
      <th>Approval ID</th><th>Claim #</th><th>Description</th><th>Amount</th>
      <th>Vendor</th><th>Category</th><th>Risk</th><th>Flags</th><th>Action</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body></html>"""
        path.write_text(html, encoding="utf-8")
