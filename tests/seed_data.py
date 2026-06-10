"""Seed a complete API test database — one row per resource type."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

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


def reset_and_seed(db: Session) -> SeedIds:
    """Clear all rows and insert fresh data for API smoke tests."""
    _register_models()
    from app.database import Base

    for table in reversed(Base.metadata.sorted_tables):
        db.execute(table.delete())
    db.commit()

    now = datetime.now(timezone.utc)
    session_id = "api-test-session01"
    review_token = "api-test-review-token-0001"

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

    db.add(
        AIChatSession(
            tenant_id=1,
            user_id=user.id,
            session_id=session_id,
            title="API test chat",
            is_active=True,
            message_count=1,
        )
    )

    job = ProcessingJob(
        user_id=user.id,
        tenant_id=1,
        job_type="voice_transcribe",
        status=ProcessingJobStatus.COMPLETED.value,
        payload={},
        result={"transcript": "test expense fifty rupees"},
        completed_at=now,
    )
    db.add(job)
    db.flush()

    report_dir = Path(settings.upload_dir) / "finance_reports" / str(user.id)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_csv = report_dir / "api_test_report.csv"
    report_csv.write_text("category,amount\nfood,100\n", encoding="utf-8")

    finance_job = ProcessingJob(
        user_id=user.id,
        tenant_id=1,
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
        tenant_id=1,
        created_by=user.id,
        snapshot_type="spend_trends",
        period_label="FY2025-26",
        payload={"total": 1000},
    )
    snap_b = AnalyticsSnapshot(
        tenant_id=1,
        created_by=user.id,
        snapshot_type="spend_trends",
        period_label="FY2025-26",
        payload={"total": 1100},
    )
    db.add(snap_a)
    db.add(snap_b)
    db.flush()

    alert = KPIAlert(
        tenant_id=1,
        alert_type="budget_spike",
        severity="medium",
        title="Test alert",
        message="Seeded alert for API tests",
        status="open",
    )
    db.add(alert)
    db.flush()

    bulk_export_id = str(uuid.uuid4())
    bulk_dir = Path(settings.upload_dir) / "bulk_previews" / str(user.id) / bulk_export_id
    bulk_dir.mkdir(parents=True, exist_ok=True)
    csv_path = bulk_dir / "preview.csv"
    csv_path.write_text("approval_id,claim_id\n1,1\n", encoding="utf-8")
    html_path = bulk_dir / "preview.html"
    html_path.write_text("<html><body>preview</body></html>", encoding="utf-8")
    manifest = {
        "export_id": bulk_export_id,
        "user_id": user.id,
        "files": {"csv": str(csv_path), "html": str(html_path), "pdf": str(html_path)},
    }
    (bulk_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

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
