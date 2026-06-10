"""Finance report access audit — who downloaded executive exports."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.finance.models import FinanceReportAccessAudit
from app.models import User


class ReportAccessAuditService:
    def __init__(self, db: Session):
        self._db = db

    def log_download(
        self,
        *,
        tenant_id: int,
        user: User,
        job_id: int,
        report_type: str,
        file_format: str,
        file_path: str,
        report_version: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> FinanceReportAccessAudit:
        row = FinanceReportAccessAudit(
            tenant_id=tenant_id,
            user_id=user.id,
            job_id=job_id,
            report_type=report_type,
            report_version=report_version,
            file_format=file_format,
            file_path=file_path,
            ip_address=ip_address,
            user_agent=user_agent,
            accessed_at=datetime.now(timezone.utc),
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def list_access(
        self,
        tenant_id: int,
        *,
        job_id: Optional[int] = None,
        user_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[FinanceReportAccessAudit]:
        q = self._db.query(FinanceReportAccessAudit).filter(
            FinanceReportAccessAudit.tenant_id == tenant_id
        )
        if job_id is not None:
            q = q.filter(FinanceReportAccessAudit.job_id == job_id)
        if user_id is not None:
            q = q.filter(FinanceReportAccessAudit.user_id == user_id)
        return q.order_by(FinanceReportAccessAudit.accessed_at.desc()).limit(limit).all()

    def to_dict(self, row: FinanceReportAccessAudit) -> Dict[str, Any]:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "job_id": row.job_id,
            "report_type": row.report_type,
            "report_version": row.report_version,
            "file_format": row.file_format,
            "ip_address": row.ip_address,
            "accessed_at": row.accessed_at,
        }
