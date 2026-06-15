"""Background jobs for async finance report generation."""
import logging

from app.database import SessionLocal
from app.intelligence.jobs.service import JobService
from app.intelligence.schemas import JobStatus
from app.finance.report_generator import FinanceReportGenerator
from app.models import User

logger = logging.getLogger(__name__)


def run_finance_report_job(job_id: int, user_id: int) -> dict:
    db = SessionLocal()
    try:
        jobs = JobService(db)
        jobs.update_status(job_id, JobStatus.PROCESSING.value, progress="generating_report")

        row = jobs.get(job_id, user_id=user_id)
        if not row:
            return {"error": "job not found"}

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            jobs.update_status(job_id, JobStatus.FAILED.value, error_message="user not found")
            return {"error": "user not found"}

        payload = row.payload or {}
        try:
            from app.config import settings

            manifest = FinanceReportGenerator(db).generate(
                user,
                report_type=payload.get("report_type", "executive_pack"),
                job_id=job_id,
                export_format=payload.get("format", "csv"),
                months=int(payload.get("months", 3)),
                quarters=int(payload.get("quarters", 1)),
                department=payload.get("department"),
                limit=int(payload.get("limit", 50)),
                report_version=payload.get("report_version")
                or settings.finance_report_version_default,
            )
        except ValueError as exc:
            jobs.update_status(job_id, JobStatus.FAILED.value, error_message=str(exc))
            return {"error": str(exc)}

        jobs.update_status(
            job_id,
            JobStatus.COMPLETED.value,
            progress="done",
            result=manifest,
        )
        return manifest
    except Exception as exc:
        logger.exception("finance report job failed: %s", exc)
        try:
            JobService(db).update_status(
                job_id,
                JobStatus.FAILED.value,
                error_message=str(exc),
            )
        except Exception:
            pass
        return {"error": str(exc)}
    finally:
        db.close()
