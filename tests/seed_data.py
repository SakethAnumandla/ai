"""Seed a complete API test database — one row per resource type."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.security import resolve_tenant_id
from app.config import settings
from app.dependencies import DEV_USER_USERNAME
from app.models import (
    ApprovalLevel,
    ApprovalStatus,
    Claim,
    ClaimApproval,
    ClaimStatus,
    Expense,
    ExpenseApproval,
    ExpenseFile,
    ExpenseStatus,
    ExpenseTax,
    MainCategory,
    OCRBatch,
    OCRBill,
    Policy,
    PolicyStatus,
    ProcessingJob,
    ProcessingJobStatus,
    TransactionType,
    UploadMethod,
    User,
    UserRole,
    Wallet,
)
from app.models import AIChatSession


@dataclass
class SeedIds:
    user_id: int
    expense_draft_id: int
    expense_submitted_id: int
    expense_empty_draft_id: int
    expense_rejected_id: int
    expense_thumb_id: int
    expense_file_id: int
    expense_approval_id: int
    policy_id: int
    policy_deletable_id: int
    claim_id: int
    claim_approval_id: int
    ocr_batch_id: int
    ocr_bill_id: int
    job_id: int
    finance_report_job_id: int
    snapshot_a_id: int
    snapshot_b_id: int
    alert_id: int
    session_id: str
    bulk_export_id: str
    review_token: str


def _valid_test_png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (32, 32), color=(200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue()


def _valid_test_thumbnail() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (32, 32), color=(200, 100, 50)).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


TEST_RECEIPT_PNG = _valid_test_png()
TEST_THUMBNAIL_JPEG = _valid_test_thumbnail()

MINIMAL_PNG = TEST_RECEIPT_PNG

MINIMAL_WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 128


def _register_models() -> None:
    import app.ai.models as _ai  # noqa: F401
    import app.finance.models as _finance  # noqa: F401


MARKER_POLICY_ID = "POL-API-TEST-001"
MARKER_SESSION_ID = "api-test-session01"
MARKER_REVIEW_TOKEN = "api-test-review-token-0001"


def _writable_upload_root() -> Path:
    """Prefer configured upload_dir; fall back when bind-mounts are not writable (e.g. Docker on macOS)."""
    candidates = [
        Path(settings.upload_dir),
        Path("/tmp/bizwy-uploads"),
    ]
    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return root
        except OSError:
            continue
    return Path("/tmp/bizwy-uploads")


def _find_bulk_export_id(user_id: int, upload_root: Path | None = None) -> str:
    bulk_root = (upload_root or _writable_upload_root()) / "bulk_previews" / str(user_id)
    if not bulk_root.is_dir():
        return ""
    for child in sorted(bulk_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if (child / "manifest.json").is_file():
            return child.name
    return ""


def _ensure_bulk_export_artifacts(user_id: int, upload_root: Path | None = None) -> str:
    existing = _find_bulk_export_id(user_id, upload_root)
    if existing:
        return existing
    root = upload_root or _writable_upload_root()
    bulk_export_id = str(uuid.uuid4())
    bulk_dir = root / "bulk_previews" / str(user_id) / bulk_export_id
    bulk_dir.mkdir(parents=True, exist_ok=True)
    csv_path = bulk_dir / "preview.csv"
    csv_path.write_text("approval_id,claim_id\n1,1\n", encoding="utf-8")
    html_path = bulk_dir / "preview.html"
    html_path.write_text("<html><body>preview</body></html>", encoding="utf-8")
    manifest = {
        "export_id": bulk_export_id,
        "user_id": user_id,
        "files": {"csv": str(csv_path), "html": str(html_path), "pdf": str(html_path)},
    }
    (bulk_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return bulk_export_id


def _get_or_create_dev_user(db: Session) -> User:
    user = db.query(User).filter(User.username == DEV_USER_USERNAME).first()
    if user:
        return user
    user = User(
        email="dev@local.test",
        username=DEV_USER_USERNAME,
        hashed_password="not-used",
        full_name="Dev User",
        is_active=True,
        is_admin=True,
        role=UserRole.SUPER_ADMIN,
    )
    db.add(user)
    db.flush()
    db.add(Wallet(user_id=user.id))
    db.flush()
    return user


def _gather_seed_ids(db: Session, user: User) -> SeedIds | None:
    """Load existing fixture IDs when bootstrap markers are already present."""
    policy = db.query(Policy).filter(Policy.policy_id == MARKER_POLICY_ID).first()
    if not policy:
        return None

    expense_draft = (
        db.query(Expense)
        .filter(
            Expense.user_id == user.id,
            Expense.bill_name == "Draft expense",
            Expense.status == ExpenseStatus.DRAFT,
        )
        .order_by(Expense.id.asc())
        .first()
    )
    if not expense_draft:
        return None

    expense_submitted = (
        db.query(Expense)
        .filter(Expense.user_id == user.id, Expense.bill_name == "Submitted expense")
        .order_by(Expense.id.asc())
        .first()
    )
    expense_empty = (
        db.query(Expense)
        .filter(Expense.user_id == user.id, Expense.bill_name == " ")
        .order_by(Expense.id.asc())
        .first()
    )
    expense_rejected = (
        db.query(Expense)
        .filter(Expense.user_id == user.id, Expense.bill_name == "Rejected expense")
        .order_by(Expense.id.asc())
        .first()
    )
    expense_thumb = (
        db.query(Expense)
        .filter(Expense.user_id == user.id, Expense.bill_name == "Thumbnail expense")
        .order_by(Expense.id.asc())
        .first()
    )
    policy_deletable = (
        db.query(Policy).filter(Policy.policy_id == "POL-API-DELETE-001").first()
    )
    claim = db.query(Claim).filter(Claim.claim_number == "CLM-API-TEST-001").first()
    ocr_batch = (
        db.query(OCRBatch)
        .filter(OCRBatch.user_id == user.id, OCRBatch.batch_name == "API test batch")
        .order_by(OCRBatch.id.desc())
        .first()
    )
    ocr_bill = (
        db.query(OCRBill)
        .filter(OCRBill.user_id == user.id, OCRBill.expense_id == expense_draft.id)
        .order_by(OCRBill.id.desc())
        .first()
    )
    expense_approval = (
        db.query(ExpenseApproval)
        .filter(ExpenseApproval.expense_id == (expense_submitted.id if expense_submitted else -1))
        .order_by(ExpenseApproval.id.asc())
        .first()
    )
    claim_approval = (
        db.query(ClaimApproval)
        .filter(ClaimApproval.claim_id == (claim.id if claim else -1))
        .order_by(ClaimApproval.id.asc())
        .first()
    )
    thumb_file = (
        db.query(ExpenseFile)
        .filter(ExpenseFile.expense_id == (expense_thumb.id if expense_thumb else -1))
        .order_by(ExpenseFile.id.asc())
        .first()
    )
    session = (
        db.query(AIChatSession)
        .filter(AIChatSession.session_id == MARKER_SESSION_ID, AIChatSession.user_id == user.id)
        .first()
    )
    job = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.user_id == user.id, ProcessingJob.job_type == "voice_transcribe")
        .order_by(ProcessingJob.id.desc())
        .first()
    )
    finance_job = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.user_id == user.id, ProcessingJob.job_type == "finance_report")
        .order_by(ProcessingJob.id.desc())
        .first()
    )

    from app.finance.models import AnalyticsSnapshot, KPIAlert

    snapshots = (
        db.query(AnalyticsSnapshot)
        .filter(AnalyticsSnapshot.created_by == user.id)
        .order_by(AnalyticsSnapshot.id.asc())
        .limit(2)
        .all()
    )
    tenant_id = resolve_tenant_id(user)
    alert = (
        db.query(KPIAlert)
        .filter(KPIAlert.tenant_id == tenant_id, KPIAlert.title == "Test alert")
        .order_by(KPIAlert.id.desc())
        .first()
    )

    if not all(
        [
            expense_submitted,
            expense_empty,
            expense_rejected,
            expense_thumb,
            policy_deletable,
            claim,
            ocr_batch,
            ocr_bill,
            expense_approval,
            claim_approval,
            thumb_file,
            session,
            job,
            finance_job,
            len(snapshots) >= 2,
            alert,
        ]
    ):
        return None

    bulk_export_id = _ensure_bulk_export_artifacts(user.id)

    return SeedIds(
        user_id=user.id,
        expense_draft_id=expense_draft.id,
        expense_submitted_id=expense_submitted.id,
        expense_empty_draft_id=expense_empty.id,
        expense_rejected_id=expense_rejected.id,
        expense_thumb_id=expense_thumb.id,
        expense_file_id=thumb_file.id,
        expense_approval_id=expense_approval.id,
        policy_id=policy.id,
        policy_deletable_id=policy_deletable.id,
        claim_id=claim.id,
        claim_approval_id=claim_approval.id,
        ocr_batch_id=ocr_batch.id,
        ocr_bill_id=ocr_bill.id,
        job_id=job.id,
        finance_report_job_id=finance_job.id,
        snapshot_a_id=snapshots[0].id,
        snapshot_b_id=snapshots[1].id,
        alert_id=alert.id,
        session_id=MARKER_SESSION_ID,
        bulk_export_id=bulk_export_id,
        review_token=MARKER_REVIEW_TOKEN,
    )


def _delete_marker_fixtures(db: Session, user: User) -> None:
    """Remove incomplete API-test marker rows before re-creating fixtures."""
    for policy in db.query(Policy).filter(Policy.policy_id.in_([MARKER_POLICY_ID, "POL-API-DELETE-001"])).all():
        db.delete(policy)
    for claim in db.query(Claim).filter(Claim.claim_number == "CLM-API-TEST-001").all():
        db.delete(claim)
    marker_names = {
        "Draft expense",
        "Submitted expense",
        " ",
        "Rejected expense",
        "Thumbnail expense",
    }
    for expense in db.query(Expense).filter(
        Expense.user_id == user.id, Expense.bill_name.in_(marker_names)
    ).all():
        db.delete(expense)
    for batch in db.query(OCRBatch).filter(
        OCRBatch.user_id == user.id, OCRBatch.batch_name == "API test batch"
    ).all():
        db.delete(batch)
    db.query(AIChatSession).filter(
        AIChatSession.user_id == user.id, AIChatSession.session_id == MARKER_SESSION_ID
    ).delete()
    db.flush()


def ensure_api_fixtures(db: Session) -> SeedIds:
    """Create API smoke-test rows when missing; never wipes production data."""
    _register_models()
    user = _get_or_create_dev_user(db)
    existing = _gather_seed_ids(db, user)
    if existing:
        db.commit()
        return existing
    policy = db.query(Policy).filter(Policy.policy_id == MARKER_POLICY_ID).first()
    if policy:
        # Partial marker rows block a clean gather — reset only API-test markers.
        _delete_marker_fixtures(db, user)
        db.commit()
    return _create_api_fixtures(db, user)


def reset_and_seed(db: Session) -> SeedIds:
    """Clear all rows and insert fresh data for API smoke tests."""
    _register_models()
    from app.database import Base

    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()

    user = _get_or_create_dev_user(db)
    return _create_api_fixtures(db, user)


def _create_api_fixtures(db: Session, user: User) -> SeedIds:
    now = datetime.now(timezone.utc)
    session_id = MARKER_SESSION_ID
    review_token = MARKER_REVIEW_TOKEN

    if not db.query(Wallet).filter(Wallet.user_id == user.id).first():
        db.add(Wallet(user_id=user.id))
        db.flush()

    expense_draft = Expense(
        user_id=user.id,
        bill_name="Draft expense",
        bill_amount=420.0,
        bill_date=now,
        transaction_type=TransactionType.EXPENSE,
        main_category=MainCategory.MISCELLANEOUS,
        upload_method=UploadMethod.MANUAL,
        status=ExpenseStatus.DRAFT,
        tax_amount=0.0,
        discount_amount=0.0,
    )
    db.add(expense_draft)
    db.flush()

    expense_file = ExpenseFile(
        expense_id=expense_draft.id,
        file_data=TEST_RECEIPT_PNG,
        file_name="receipt.png",
        file_size=len(TEST_RECEIPT_PNG),
        mime_type="image/png",
        is_primary=True,
        thumbnail_data=TEST_THUMBNAIL_JPEG,
    )
    db.add(expense_file)
    db.flush()

    db.add(
        ExpenseTax(
            expense_id=expense_draft.id,
            tax_label="CGST",
            tax_type="cgst",
            calculation_type="fixed_value",
            tax_amount=10.0,
            recoverable=True,
        )
    )

    expense_submitted = Expense(
        user_id=user.id,
        bill_name="Submitted expense",
        bill_amount=1500.0,
        bill_date=now,
        transaction_type=TransactionType.EXPENSE,
        main_category=MainCategory.MEALS_ENTERTAINMENT,
        sub_category="restaurant",
        upload_method=UploadMethod.MANUAL,
        status=ExpenseStatus.SUBMITTED,
        tax_amount=150.0,
        discount_amount=0.0,
    )
    db.add(expense_submitted)
    db.flush()

    expense_empty_draft = Expense(
        user_id=user.id,
        bill_name=" ",
        bill_amount=0.01,
        bill_date=now,
        transaction_type=TransactionType.EXPENSE,
        main_category=MainCategory.MISCELLANEOUS,
        upload_method=UploadMethod.MANUAL,
        status=ExpenseStatus.DRAFT,
        tax_amount=0.0,
        discount_amount=0.0,
    )
    db.add(expense_empty_draft)
    db.flush()

    expense_rejected = Expense(
        user_id=user.id,
        bill_name="Rejected expense",
        bill_amount=800.0,
        bill_date=now,
        transaction_type=TransactionType.EXPENSE,
        main_category=MainCategory.MISCELLANEOUS,
        upload_method=UploadMethod.MANUAL,
        status=ExpenseStatus.REJECTED,
        rejection_reason="Test rejection",
        tax_amount=0.0,
        discount_amount=0.0,
    )
    db.add(expense_rejected)
    db.flush()

    expense_thumb = Expense(
        user_id=user.id,
        bill_name="Thumbnail expense",
        bill_amount=250.0,
        bill_date=now,
        transaction_type=TransactionType.EXPENSE,
        main_category=MainCategory.MISCELLANEOUS,
        upload_method=UploadMethod.MANUAL,
        status=ExpenseStatus.DRAFT,
        thumbnail_data=TEST_THUMBNAIL_JPEG,
        tax_amount=0.0,
        discount_amount=0.0,
    )
    db.add(expense_thumb)
    db.flush()

    thumb_file = ExpenseFile(
        expense_id=expense_thumb.id,
        file_data=TEST_RECEIPT_PNG,
        file_name="receipt.png",
        file_size=len(TEST_RECEIPT_PNG),
        mime_type="image/png",
        is_primary=True,
        thumbnail_data=TEST_THUMBNAIL_JPEG,
    )
    db.add(thumb_file)
    db.flush()

    expense_approval = ExpenseApproval(
        expense_id=expense_submitted.id,
        approval_level="manager",
        sequence_order=1,
        approver_id=user.id,
        approver_name="Dev User",
        approver_role_label="Manager",
        status=ApprovalStatus.PENDING,
    )
    db.add(expense_approval)
    db.flush()

    policy = Policy(
        policy_id="POL-API-TEST-001",
        policy_name="API Test Travel Policy",
        policy_type="travel",
        description="Seeded for API tests",
        maximum_amount=50000.0,
        minimum_amount=0.0,
        coverage_percentage=100.0,
        main_category=MainCategory.POLICY,
        sub_category="all",
        requires_approval=True,
        approval_flow=["department_head"],
        valid_from=now,
        status=PolicyStatus.ACTIVE,
        created_by=user.id,
    )
    db.add(policy)
    db.flush()

    policy_deletable = Policy(
        policy_id="POL-API-DELETE-001",
        policy_name="Deletable Test Policy",
        policy_type="travel",
        description="Seeded for DELETE API test",
        maximum_amount=10000.0,
        minimum_amount=0.0,
        coverage_percentage=100.0,
        main_category=MainCategory.POLICY,
        sub_category="all",
        requires_approval=False,
        approval_flow=[],
        valid_from=now,
        status=PolicyStatus.ACTIVE,
        created_by=user.id,
    )
    db.add(policy_deletable)
    db.flush()

    claim = Claim(
        claim_number="CLM-API-TEST-001",
        policy_id=policy.id,
        user_id=user.id,
        bill_name="Claim bill",
        bill_amount=500.0,
        bill_date=now,
        main_category=MainCategory.POLICY,
        claimed_amount=500.0,
        status=ClaimStatus.PENDING,
    )
    db.add(claim)
    db.flush()

    claim_approval = ClaimApproval(
        claim_id=claim.id,
        approver_id=user.id,
        approval_level=ApprovalLevel.DEPARTMENT_HEAD,
        sequence_order=1,
        status=ApprovalStatus.PENDING,
    )
    db.add(claim_approval)
    db.flush()

    ocr_batch = OCRBatch(
        user_id=user.id,
        total_files=1,
        processed_files=1,
        status="completed",
        batch_name="API test batch",
        completed_at=now,
    )
    db.add(ocr_batch)
    db.flush()

    ocr_bill = OCRBill(
        user_id=user.id,
        batch_id=ocr_batch.id,
        expense_id=expense_draft.id,
        original_file_data=TEST_RECEIPT_PNG,
        original_file_name="receipt.png",
        original_file_size=len(TEST_RECEIPT_PNG),
        original_mime_type="image/png",
        total_amount=420.0,
        vendor_name="Test Vendor",
        detected_main_category=MainCategory.MISCELLANEOUS,
        extracted_fields={"review_token": review_token, "review_status": "pending_review"},
    )
    db.add(ocr_bill)
    db.flush()

    tenant_id = resolve_tenant_id(user)
    db.add(
        AIChatSession(
            tenant_id=tenant_id,
            user_id=user.id,
            session_id=session_id,
            title="API test chat",
            is_active=True,
            message_count=1,
        )
    )

    job = ProcessingJob(
        user_id=user.id,
        tenant_id=tenant_id,
        job_type="voice_transcribe",
        status=ProcessingJobStatus.COMPLETED.value,
        payload={},
        result={"transcript": "test expense fifty rupees"},
        completed_at=now,
    )
    db.add(job)
    db.flush()

    upload_root = _writable_upload_root()
    report_dir = upload_root / "finance_reports" / str(user.id)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_csv = report_dir / "api_test_report.csv"
    report_csv.write_text("category,amount\nfood,100\n", encoding="utf-8")

    finance_job = ProcessingJob(
        user_id=user.id,
        tenant_id=tenant_id,
        job_type="finance_report",
        status=ProcessingJobStatus.COMPLETED.value,
        payload={"report_type": "spend_summary"},
        result={
            "report_type": "spend_summary",
            "report_version": "v1",
            "files": {"csv": str(report_csv), "json": str(report_csv)},
        },
        completed_at=now,
    )
    db.add(finance_job)
    db.flush()

    from app.finance.models import AnalyticsSnapshot, KPIAlert

    snap_a = AnalyticsSnapshot(
        tenant_id=tenant_id,
        created_by=user.id,
        snapshot_type="spend_trends",
        period_label="FY2025-26",
        payload={"total": 1000},
    )
    snap_b = AnalyticsSnapshot(
        tenant_id=tenant_id,
        created_by=user.id,
        snapshot_type="spend_trends",
        period_label="FY2025-26",
        payload={"total": 1100},
    )
    db.add(snap_a)
    db.add(snap_b)
    db.flush()

    alert = KPIAlert(
        tenant_id=tenant_id,
        alert_type="budget_spike",
        severity="medium",
        title="Test alert",
        message="Seeded alert for API tests",
        status="open",
    )
    db.add(alert)
    db.flush()

    bulk_export_id = _ensure_bulk_export_artifacts(user.id, upload_root)

    db.commit()

    return SeedIds(
        user_id=user.id,
        expense_draft_id=expense_draft.id,
        expense_submitted_id=expense_submitted.id,
        expense_empty_draft_id=expense_empty_draft.id,
        expense_rejected_id=expense_rejected.id,
        expense_thumb_id=expense_thumb.id,
        expense_file_id=thumb_file.id,
        expense_approval_id=expense_approval.id,
        policy_id=policy.id,
        policy_deletable_id=policy_deletable.id,
        claim_id=claim.id,
        claim_approval_id=claim_approval.id,
        ocr_batch_id=ocr_batch.id,
        ocr_bill_id=ocr_bill.id,
        job_id=job.id,
        finance_report_job_id=finance_job.id,
        snapshot_a_id=snap_a.id,
        snapshot_b_id=snap_b.id,
        alert_id=alert.id,
        session_id=session_id,
        bulk_export_id=bulk_export_id,
        review_token=review_token,
    )
