# models.py - Complete with Policy & Claims Support
from sqlalchemy import Column, Integer, String, Float, DateTime, Enum, ForeignKey, Text, JSON, Boolean, LargeBinary, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, validates
from app.database import Base
import enum

# ==================== Enums ====================

class TransactionType(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"

class ExpenseStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"  # legacy; use SUBMITTED for new expenses
    SUBMITTED = "submitted"  # locked, awaiting approval
    APPROVED = "approved"
    REJECTED = "rejected"

# Main Categories (Parent Categories)
class MainCategory(str, enum.Enum):
    TRAVEL = "travel"
    FOOD = "food"
    BILLS = "bills"
    SHOPPING = "shopping"
    ENTERTAINMENT = "entertainment"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    FUEL = "fuel"
    INSURANCE = "insurance"
    INVESTMENT = "investment"
    SALARY = "salary"
    RENT = "rent"
    UTILITIES = "utilities"
    GROCERIES = "groceries"
    PERSONAL_CARE = "personal_care"
    SUBSCRIPTIONS = "subscriptions"
    MISCELLANEOUS = "miscellaneous"
    POLICY = "policy"
    # Business taxonomy (spreadsheet)
    PEOPLE_HR = "people_hr"
    OFFICE_FACILITIES = "office_facilities"
    TECHNOLOGY_IT = "technology_it"
    TRAVEL_TRANSPORTATION = "travel_transportation"
    MEALS_ENTERTAINMENT = "meals_entertainment"
    SALES_MARKETING = "sales_marketing"
    PROFESSIONAL_LEGAL = "professional_legal"
    FINANCE_BANKING = "finance_banking"
    OPERATIONS_SUPPLY = "operations_supply"
    TAXES_GOVT = "taxes_govt"

# Sub Categories Constants
class SubCategoryConstants:
    # Travel subcategories
    UBER = "uber"
    RAPIDO = "rapido"
    OLA = "ola"
    METRO = "metro"
    BUS = "bus"
    TRAIN = "train"
    FLIGHT = "flight"
    TAXI = "taxi"
    AUTO = "auto"
    FUEL_TRAVEL = "fuel_travel"
    PARKING = "parking"
    TOLL = "toll"
    CAR_RENTAL = "car_rental"
    
    # Food subcategories
    SWIGGY = "swiggy"
    ZOMATO = "zomato"
    DINING = "dining"
    CAFE = "cafe"
    RESTAURANT = "restaurant"
    STREET_FOOD = "street_food"
    PARTY_FOOD = "party_food"
    OFFICE_LUNCH = "office_lunch"
    
    # Bills subcategories
    ELECTRICITY = "electricity"
    WATER = "water"
    GAS = "gas"
    INTERNET = "internet"
    MOBILE = "mobile"
    DTH = "dth"
    MAINTENANCE = "maintenance"
    PROPERTY_TAX = "property_tax"
    
    # Shopping subcategories
    CLOTHING = "clothing"
    ELECTRONICS = "electronics"
    GROCERIES_SHOPPING = "groceries_shopping"
    HOME_APPLIANCES = "home_appliances"
    FURNITURE = "furniture"
    BOOKS = "books"
    MEDICINE_SHOPPING = "medicine_shopping"
    
    # Entertainment subcategories
    MOVIES = "movies"
    CONCERT = "concert"
    NETFLIX = "netflix"
    AMAZON_PRIME = "amazon_prime"
    HOTSTAR = "hotstar"
    GAMING = "gaming"
    SPORTS = "sports"
    PARTY_ENTERTAINMENT = "party_entertainment"
    
    # Healthcare subcategories
    DOCTOR = "doctor"
    DENTIST = "dentist"
    MEDICINE = "medicine"
    HOSPITAL = "hospital"
    LAB_TESTS = "lab_tests"
    PHYSIOTHERAPY = "physiotherapy"
    FITNESS = "fitness"
    GYM = "gym"
    
    # Education subcategories
    SCHOOL_FEES = "school_fees"
    COLLEGE_FEES = "college_fees"
    BOOKS_EDUCATION = "books_education"
    COURSES = "courses"
    TUITION = "tuition"
    EXAM_FEES = "exam_fees"
    STATIONERY = "stationery"
    
    # Fuel subcategories
    PETROL = "petrol"
    DIESEL = "diesel"
    CNG = "cng"
    EV_CHARGING = "ev_charging"
    
    # Insurance subcategories
    HEALTH_INSURANCE = "health_insurance"
    LIFE_INSURANCE = "life_insurance"
    VEHICLE_INSURANCE = "vehicle_insurance"
    HOME_INSURANCE = "home_insurance"
    TRAVEL_INSURANCE = "travel_insurance"
    
    # Investment subcategories
    STOCKS = "stocks"
    MUTUAL_FUNDS = "mutual_funds"
    FIXED_DEPOSIT = "fixed_deposit"
    PPF = "ppf"
    NPS = "nps"
    GOLD = "gold"
    REAL_ESTATE = "real_estate"
    
    # Income subcategories
    SALARY_INCOME = "salary_income"
    BONUS = "bonus"
    FREELANCE = "freelance"
    BUSINESS = "business"
    RENTAL_INCOME = "rental_income"
    INVESTMENT_RETURNS = "investment_returns"
    REFUND = "refund"
    GIFTS = "gifts"
    REIMBURSEMENT = "reimbursement"

class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    UPI = "upi"
    NET_BANKING = "net_banking"
    WALLET = "wallet"
    CRYPTO = "crypto"

class UploadMethod(str, enum.Enum):
    MANUAL = "manual"
    OCR = "ocr"
    VOICE = "voice"


class ProcessingJobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingJobType(str, enum.Enum):
    VOICE_TRANSCRIBE = "voice_transcribe"
    VOICE_CHAT = "voice_chat"
    RECEIPT_OCR = "receipt_ocr"
    FINANCE_REPORT = "finance_report"

# ==================== Policy & Claims Enums ====================

class PolicyStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    EXPIRED = "expired"
    DRAFT = "draft"

class ClaimStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REIMBURSED = "reimbursed"

class ApprovalLevel(str, enum.Enum):
    DEPARTMENT_HEAD = "department_head"
    MANAGER = "manager"
    FINANCE = "finance"
    HR = "hr"

class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUESTED_CHANGES = "requested_changes"

class Department(str, enum.Enum):
    SALES = "sales"
    MARKETING = "marketing"
    ENGINEERING = "engineering"
    HR = "hr"
    FINANCE = "finance"
    OPERATIONS = "operations"
    ADMIN = "admin"

class UserRole(str, enum.Enum):
    EMPLOYEE = "employee"
    DEPARTMENT_HEAD = "department_head"
    MANAGER = "manager"
    FINANCE_ADMIN = "finance_admin"
    SUPER_ADMIN = "super_admin"

# ==================== User Model (Updated) ====================

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    phone_number = Column(String)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    
    # New fields for policy workflow
    role = Column(
        Enum(UserRole, values_callable=lambda obj: [e.value for e in obj], native_enum=False),
        default=UserRole.EMPLOYEE,
    )
    department = Column(
        Enum(Department, values_callable=lambda obj: [e.value for e in obj], native_enum=False),
        nullable=True,
    )
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    department_head_for = Column(
        Enum(Department, values_callable=lambda obj: [e.value for e in obj], native_enum=False),
        nullable=True,
    )
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    expenses = relationship(
        "Expense",
        back_populates="user",
        foreign_keys="Expense.user_id",
        cascade="all, delete-orphan",
    )
    wallet = relationship("Wallet", back_populates="user", uselist=False, cascade="all, delete-orphan")
    ocr_bills = relationship("OCRBill", back_populates="user", cascade="all, delete-orphan")
    ocr_batches = relationship("OCRBatch", back_populates="user", cascade="all, delete-orphan")
    
    # Policy relationships
    policies_created = relationship("Policy", foreign_keys="Policy.created_by", cascade="all, delete-orphan")
    claims = relationship("Claim", foreign_keys="Claim.user_id", cascade="all, delete-orphan")
    approvals = relationship("ClaimApproval", foreign_keys="ClaimApproval.approver_id", cascade="all, delete-orphan")
    
    # Manager relationship
    manager = relationship("User", remote_side=[id], foreign_keys=[manager_id])
    subordinates = relationship("User", foreign_keys=[manager_id], overlaps="manager")

# ==================== Policy Models ====================

class Policy(Base):
    """Company Policy Model"""
    __tablename__ = "policies"
    
    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(String, unique=True, index=True, nullable=False)  # e.g., POL-2024-001
    policy_name = Column(String, nullable=False)
    policy_type = Column(String, nullable=False)  # medical, travel, food, education, etc.
    
    # Policy Details
    description = Column(Text)
    maximum_amount = Column(Float, nullable=False)  # Maximum claim limit
    minimum_amount = Column(Float, default=0.0)  # Minimum amount for claim
    coverage_percentage = Column(Float, default=100.0)  # What % is covered
    
    # Category Mapping
    main_category = Column(
        Enum(MainCategory, values_callable=lambda obj: [e.value for e in obj], native_enum=False),
        nullable=False,
    )
    sub_category = Column(String, nullable=True)  # Specific sub-category or "all"
    
    # Policy Rules
    requires_approval = Column(Boolean, default=True)
    approval_flow = Column(JSON)  # List of approval levels required
    
    # Terms & Conditions
    terms_and_conditions = Column(Text)
    exclusions = Column(Text)  # What's not covered
    documentation_required = Column(JSON)  # List of required docs

    # Tax regime for claims under this policy (CGST/VAT/etc.)
    country_code = Column(String(2), default="IN", nullable=False)
    tax_regime = Column(String(32), default="india_gst", nullable=False)
    applicable_tax_types = Column(JSON, nullable=True)  # e.g. ["cgst", "sgst"]
    tax_inclusive = Column(Boolean, default=False)

    # Payment (default / allowed modes for claims under this policy)
    payment_method = Column(
        Enum(PaymentMethod, values_callable=lambda obj: [e.value for e in obj], native_enum=False),
        nullable=True,
    )
    allowed_payment_modes = Column(JSON, nullable=True)
    
    # Validity
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    
    # Status
    status = Column(
        Enum(PolicyStatus, values_callable=lambda obj: [e.value for e in obj], native_enum=False),
        default=PolicyStatus.ACTIVE,
    )
    
    # For OCR Scanned Policies
    is_ocr_created = Column(Boolean, default=False)
    original_file_data = Column(LargeBinary, nullable=True)
    original_file_name = Column(String, nullable=True)
    
    # Metadata
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by], overlaps="policies_created")
    claims = relationship("Claim", back_populates="policy", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_policies_type_status', 'policy_type', 'status'),
        Index('ix_policies_validity', 'valid_from', 'valid_to'),
        Index('ix_policies_category', 'main_category'),
    )

# ==================== Claim Models ====================

class Claim(Base):
    """Employee Claim/Bill against a Policy"""
    __tablename__ = "claims"
    
    id = Column(Integer, primary_key=True, index=True)
    claim_number = Column(String, unique=True, index=True, nullable=False)  # CLM-2024-001
    policy_id = Column(Integer, ForeignKey("policies.id", ondelete="RESTRICT"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Claim Details
    bill_name = Column(String, nullable=False)
    bill_amount = Column(Float, nullable=False)
    bill_date = Column(DateTime(timezone=True), nullable=False)
    bill_number = Column(String)
    vendor_name = Column(String)
    description = Column(Text)
    payment_method = Column(
        Enum(PaymentMethod, values_callable=lambda obj: [e.value for e in obj], native_enum=False),
        nullable=True,
    )
    
    # Category
    main_category = Column(
        Enum(MainCategory, values_callable=lambda obj: [e.value for e in obj], native_enum=False),
        nullable=False,
    )
    sub_category = Column(String, nullable=True)
    
    # Financial
    claimed_amount = Column(Float, nullable=False)
    approved_amount = Column(Float, default=0.0)
    reimbursed_amount = Column(Float, default=0.0)
    deduction_reason = Column(Text, nullable=True)
    
    # Status
    status = Column(
        Enum(ClaimStatus, values_callable=lambda obj: [e.value for e in obj], native_enum=False),
        default=ClaimStatus.PENDING,
    )
    rejection_reason = Column(Text, nullable=True)
    is_reimbursable = Column(Boolean, default=True)
    
    # File Attachments
    file_data = Column(LargeBinary, nullable=True)
    file_name = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    
    # OCR Data (if scanned)
    ocr_data = Column(JSON, nullable=True)
    is_ocr_created = Column(Boolean, default=False)
    
    # Bank Details for Reimbursement
    bank_account_number = Column(String, nullable=True)
    bank_ifsc_code = Column(String, nullable=True)
    bank_account_holder = Column(String, nullable=True)
    
    # Timestamps
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    approved_at = Column(DateTime(timezone=True), nullable=True)
    reimbursed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    policy = relationship("Policy", back_populates="claims")
    user = relationship("User", foreign_keys=[user_id], overlaps="claims")
    approvals = relationship("ClaimApproval", back_populates="claim", cascade="all, delete-orphan")
    expense = relationship("Expense", back_populates="claim", uselist=False)

    @property
    def expense_id(self):
        return self.expense.id if self.expense else None
    
    __table_args__ = (
        Index('ix_claims_user_status', 'user_id', 'status'),
        Index('ix_claims_policy_status', 'policy_id', 'status'),
        Index('ix_claims_submitted_date', 'submitted_at'),
    )

# ==================== Approval Models ====================

class ClaimApproval(Base):
    """Approval workflow for Claims"""
    __tablename__ = "claim_approvals"
    
    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    approver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    approval_level = Column(
        Enum(ApprovalLevel, values_callable=lambda obj: [e.value for e in obj], native_enum=False),
        nullable=False,
    )
    sequence_order = Column(Integer, default=1, nullable=False)
    
    # Approval Details
    status = Column(
        Enum(ApprovalStatus, values_callable=lambda obj: [e.value for e in obj], native_enum=False),
        default=ApprovalStatus.PENDING,
    )
    comments = Column(Text, nullable=True)
    approved_amount = Column(Float, nullable=True)  # If partial approval
    
    # Timestamps
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    actioned_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    claim = relationship("Claim", back_populates="approvals")
    approver = relationship("User", foreign_keys=[approver_id], overlaps="approvals")
    
    __table_args__ = (
        Index('ix_claim_approvals_claim_status', 'claim_id', 'status'),
        Index('ix_claim_approvals_approver', 'approver_id', 'status'),
    )

# ==================== Expense Model (Updated with Claim Link) ====================

class Expense(Base):
    __tablename__ = "expenses"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(Integer, nullable=False, default=1, index=True)

    # Basic fields
    bill_name = Column(String, nullable=False)
    bill_amount = Column(Float, nullable=False)
    bill_date = Column(DateTime(timezone=True), nullable=False)
    transaction_type = Column(Enum(TransactionType), nullable=False)
    
    # Hierarchical Categories (main → sub → line item)
    main_category = Column(Enum(MainCategory), nullable=False)
    sub_category = Column(String, nullable=True)
    line_item = Column(String, nullable=True)
    financial_year = Column(String(16), nullable=True, index=True)
    amount_excl_gst = Column(Float, nullable=True)
    gst_rate_pct = Column(Float, nullable=True)
    gst_amount = Column(Float, nullable=True)
    itc_eligible = Column(Boolean, default=False)
    currency_code = Column(String(3), default="EUR", nullable=False)
    
    # Additional fields
    description = Column(Text)
    payment_method = Column(Enum(PaymentMethod))
    vendor_name = Column(String)
    bill_number = Column(String)
    tax_amount = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    country_code = Column(String(2), default="IN", nullable=False)
    subtotal = Column(Float, nullable=True)
    
    # Legacy single-file columns (deprecated; use expense_files)
    file_data = Column(LargeBinary, nullable=True)
    file_name = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    file_hash = Column(String(64), nullable=True)
    thumbnail_data = Column(LargeBinary, nullable=True)
    
    # Status tracking
    status = Column(Enum(ExpenseStatus), default=ExpenseStatus.PENDING)
    upload_method = Column(Enum(UploadMethod), nullable=False)
    rejection_reason = Column(Text)
    submitted_by_name = Column(String(128), nullable=True)
    submitted_by_role = Column(String(128), nullable=True)
    hashtags = Column(JSON, nullable=True, default=list)

    @validates("hashtags")
    def _normalize_hashtags(self, _key: str, value):
        from app.utils.category_hashtags import normalize_hashtags_list

        if value is None:
            return []
        if isinstance(value, list):
            return normalize_hashtags_list(value)
        return normalize_hashtags_list([str(value)])

    # Policy Claim Link
    claim_id = Column(Integer, ForeignKey("claims.id", ondelete="SET NULL"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    approved_at = Column(DateTime(timezone=True))
    approved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="expenses", foreign_keys=[user_id])
    files = relationship("ExpenseFile", back_populates="expense", cascade="all, delete-orphan")
    tax_lines = relationship(
        "ExpenseTax", back_populates="expense", cascade="all, delete-orphan"
    )
    wallet_transaction = relationship("WalletTransaction", back_populates="expense", uselist=False, cascade="all, delete-orphan")
    ocr_bills = relationship("OCRBill", back_populates="expense", cascade="all, delete-orphan")
    approver = relationship("User", foreign_keys=[approved_by])
    claim = relationship("Claim", back_populates="expense")
    approval_steps = relationship(
        "ExpenseApproval",
        back_populates="expense",
        cascade="all, delete-orphan",
        order_by="ExpenseApproval.sequence_order",
    )
    
    # Indexes for better performance
    __table_args__ = (
        Index('idx_expenses_owner', 'company_id', 'user_id'),
        Index('ix_expenses_user_status', 'user_id', 'status'),
        Index('ix_expenses_user_date', 'user_id', 'bill_date'),
        Index('ix_expenses_user_category', 'user_id', 'main_category'),
        Index('ix_expenses_file_hash', 'file_hash'),
        Index('ix_expenses_bill_date', 'bill_date'),
        Index('ix_expenses_claim_id', 'claim_id'),
    )

# ==================== Expense multi-level approval ====================

class ExpenseApproval(Base):
    """Per-expense approval chain (draft → submitted → L1/L2/L3 → approved/rejected)."""
    __tablename__ = "expense_approvals"

    id = Column(Integer, primary_key=True, index=True)
    expense_id = Column(Integer, ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False)
    approval_level = Column(String(32), nullable=False)  # manager, hod, hr, director, finance, …
    sequence_order = Column(Integer, nullable=False, default=1)
    approver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approver_name = Column(String(128), nullable=True)
    approver_role_label = Column(String(64), nullable=True)
    status = Column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING)
    comments = Column(Text, nullable=True)
    acted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    expense = relationship("Expense", back_populates="approval_steps")
    approver = relationship("User", foreign_keys=[approver_id])

    __table_args__ = (
        Index("ix_expense_approvals_expense_seq", "expense_id", "sequence_order"),
        Index("ix_expense_approvals_approver_status", "approver_id", "status"),
    )


# ==================== AI chat session metadata ====================

class AIChatSession(Base):
    """Persisted chat session list (messages live in ai_conversations).

    ``tenant_id`` stores the Bizwy ``company_id`` for multi-tenant isolation.
    """
    __tablename__ = "ai_chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(64), nullable=False, index=True)
    title = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("ix_ai_chat_sessions_user_session", "tenant_id", "user_id", "session_id", unique=True),
    )


# ==================== Expense Tax Lines ====================

class ExpenseTax(Base):
    """Structured tax line per expense (CGST, SGST, IGST, VAT, etc.)."""
    __tablename__ = "expense_taxes"

    id = Column(Integer, primary_key=True, index=True)
    expense_id = Column(
        Integer, ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False
    )
    country_code = Column(String(2), nullable=False, default="IN")
    tax_regime = Column(String(32), nullable=False, default="india_gst")
    tax_type = Column(String(32), nullable=False)
    tax_label = Column(String(64), nullable=True)
    calculation_type = Column(String(16), nullable=True, default="fixed_value")
    tax_rate = Column(Float, nullable=True)
    taxable_amount = Column(Float, nullable=True)
    cgst = Column(Float, default=0.0)
    sgst = Column(Float, default=0.0)
    igst = Column(Float, default=0.0)
    vat = Column(Float, default=0.0)
    tax_amount = Column(Float, nullable=False, default=0.0)
    recoverable = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    expense = relationship("Expense", back_populates="tax_lines")

    __table_args__ = (
        Index("ix_expense_taxes_expense_id", "expense_id"),
        Index("ix_expense_taxes_tax_type", "tax_type"),
    )


# ==================== Expense File Model ====================

class ExpenseFile(Base):
    """Multiple files attached to one expense."""
    __tablename__ = "expense_files"

    id = Column(Integer, primary_key=True, index=True)
    expense_id = Column(Integer, ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False)

    file_data = Column(LargeBinary, nullable=False)
    file_name = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String, nullable=False)
    file_hash = Column(String(64), nullable=True)
    thumbnail_data = Column(LargeBinary, nullable=True)

    is_primary = Column(Boolean, default=False)
    page_number = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    expense = relationship("Expense", back_populates="files")

    __table_args__ = (
        Index("ix_expense_files_expense_id", "expense_id"),
        Index("ix_expense_files_hash", "file_hash"),
    )

# ==================== OCR Models ====================

class OCRBatch(Base):
    """Groups multiple OCR scans processed together."""
    __tablename__ = "ocr_batches"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(Integer, nullable=False, default=1, index=True)
    batch_name = Column(String, nullable=True)
    total_files = Column(Integer, default=0)
    processed_files = Column(Integer, default=0)
    status = Column(String, default="processing")  # processing, completed, failed
    result_summary = Column(JSON, nullable=True)  # failed_files, skipped_duplicates, etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="ocr_batches")
    ocr_bills = relationship("OCRBill", back_populates="batch")


class OCRBill(Base):
    __tablename__ = "ocr_bills"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(Integer, nullable=False, default=1, index=True)
    expense_id = Column(Integer, ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True)
    batch_id = Column(Integer, ForeignKey("ocr_batches.id", ondelete="SET NULL"), nullable=True)

    # Original file data
    original_file_data = Column(LargeBinary)
    original_file_name = Column(String)
    original_file_size = Column(Integer)
    original_mime_type = Column(String)
    
    # Extracted data - Comprehensive fields for all types of bills
    # Basic info
    bill_number = Column(String)
    bill_date = Column(DateTime(timezone=True))
    due_date = Column(DateTime(timezone=True))
    vendor_name = Column(String)
    vendor_gst = Column(String)
    vendor_address = Column(Text)
    customer_name = Column(String)
    customer_gst = Column(String)
    
    # Financial details
    subtotal = Column(Float)
    total_amount = Column(Float)
    tax_amount = Column(Float)
    discount_amount = Column(Float)
    shipping_charges = Column(Float)
    convenience_fee = Column(Float)
    tip_amount = Column(Float)
    round_off = Column(Float)
    
    # Tax breakdown (JSON for flexibility)
    tax_breakdown = Column(JSON)
    
    # Ride-specific fields (Uber, Rapido, Ola)
    ride_distance = Column(Float)
    ride_duration = Column(Integer)
    pickup_location = Column(String)
    dropoff_location = Column(String)
    ride_type = Column(String)
    driver_name = Column(String)
    vehicle_number = Column(String)
    
    # Food delivery specific (Swiggy, Zomato)
    restaurant_name = Column(String)
    restaurant_address = Column(Text)
    order_number = Column(String)
    items_list = Column(JSON)
    delivery_charge = Column(Float)
    packaging_charge = Column(Float)
    platform_fee = Column(Float)
    gst_on_platform_fee = Column(Float)
    
    # Payment details
    payment_method = Column(String)
    payment_status = Column(String)
    payment_transaction_id = Column(String)
    card_last_four = Column(String)
    
    # Raw extracted data
    raw_text = Column(Text)
    confidence_score = Column(Float)
    extracted_fields = Column(JSON)
    
    # Detected category hierarchy
    detected_main_category = Column(Enum(MainCategory), nullable=True)
    detected_sub_category = Column(String, nullable=True)
    
    # Processing metadata
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_by = Column(String)
    
    # Relationships
    user = relationship("User", back_populates="ocr_bills")
    expense = relationship("Expense", back_populates="ocr_bills")
    batch = relationship("OCRBatch", back_populates="ocr_bills")

    __table_args__ = (
        Index('ix_ocr_bills_user_id', 'user_id'),
        Index('ix_ocr_bills_expense_id', 'expense_id'),
        Index('ix_ocr_bills_batch_id', 'batch_id'),
        Index('ix_ocr_bills_processed_at', 'processed_at'),
    )


class ProcessingJob(Base):
    """Async voice / receipt intelligence jobs (background thread, pollable)."""

    __tablename__ = "processing_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, nullable=False, index=True)
    job_type = Column(String(64), nullable=False, index=True)
    status = Column(String(32), default=ProcessingJobStatus.PENDING.value, index=True)
    celery_task_id = Column(String(128), nullable=True, index=True)
    payload = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    error_message = Column(Text, nullable=True)
    progress = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class VoiceTranscriptionAudit(Base):
    """Audit log for Whisper transcriptions."""

    __tablename__ = "voice_transcription_audits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("processing_jobs.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(String(64), nullable=True)
    file_name = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    language = Column(String(16), nullable=True)
    model = Column(String(64), nullable=True)
    transcript_preview = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    latency_ms = Column(Integer, default=0)
    status = Column(String(32), default="success")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# ==================== Wallet Models ====================

class Wallet(Base):
    __tablename__ = "wallets"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(Integer, nullable=False, default=1, index=True)
    balance = Column(Float, default=0.0)
    total_income = Column(Float, default=0.0)
    total_expense = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="wallet")
    transactions = relationship("WalletTransaction", back_populates="wallet", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_wallet_owner", "company_id", "user_id", unique=True),
    )


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False)
    expense_id = Column(Integer, ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False)
    
    amount = Column(Float, nullable=False)
    transaction_type = Column(Enum(TransactionType), nullable=False)
    transaction_date = Column(DateTime(timezone=True), server_default=func.now())
    description = Column(Text)
    
    # Category info at time of transaction
    main_category = Column(Enum(MainCategory), nullable=True)
    sub_category = Column(String, nullable=True)
    
    # Relationships
    wallet = relationship("Wallet", back_populates="transactions")
    expense = relationship("Expense", back_populates="wallet_transaction")
    
    __table_args__ = (
        Index('ix_wallet_transactions_wallet_id', 'wallet_id'),
        Index('ix_wallet_transactions_date', 'transaction_date'),
    )

# ==================== Budget Model ====================

class Budget(Base):
    __tablename__ = "budgets"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(Integer, nullable=False, default=1, index=True)
    main_category = Column(Enum(MainCategory), nullable=False)
    sub_category = Column(String, nullable=True)
    month = Column(Integer, nullable=False)  # 1-12
    year = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    alert_threshold = Column(Float, default=80.0)  # Alert at 80% of budget
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User")
    
    __table_args__ = (
        Index('ix_budgets_user_category_month', 'user_id', 'main_category', 'month', 'year', unique=True),
    )

# ==================== Category Mapping Helper ====================

class CategoryMapping:
    """Helper class for category mappings"""
    
    # Map subcategories to main categories
    SUBCATEGORY_TO_MAIN = {
        # Travel
        SubCategoryConstants.UBER: MainCategory.TRAVEL,
        SubCategoryConstants.RAPIDO: MainCategory.TRAVEL,
        SubCategoryConstants.OLA: MainCategory.TRAVEL,
        SubCategoryConstants.METRO: MainCategory.TRAVEL,
        SubCategoryConstants.BUS: MainCategory.TRAVEL,
        SubCategoryConstants.TRAIN: MainCategory.TRAVEL,
        SubCategoryConstants.FLIGHT: MainCategory.TRAVEL,
        SubCategoryConstants.TAXI: MainCategory.TRAVEL,
        SubCategoryConstants.AUTO: MainCategory.TRAVEL,
        SubCategoryConstants.FUEL_TRAVEL: MainCategory.TRAVEL,
        SubCategoryConstants.PARKING: MainCategory.TRAVEL,
        SubCategoryConstants.TOLL: MainCategory.TRAVEL,
        SubCategoryConstants.CAR_RENTAL: MainCategory.TRAVEL,
        
        # Food
        SubCategoryConstants.SWIGGY: MainCategory.FOOD,
        SubCategoryConstants.ZOMATO: MainCategory.FOOD,
        SubCategoryConstants.DINING: MainCategory.FOOD,
        SubCategoryConstants.CAFE: MainCategory.FOOD,
        SubCategoryConstants.RESTAURANT: MainCategory.FOOD,
        SubCategoryConstants.STREET_FOOD: MainCategory.FOOD,
        SubCategoryConstants.PARTY_FOOD: MainCategory.FOOD,
        SubCategoryConstants.OFFICE_LUNCH: MainCategory.FOOD,
        
        # Bills
        SubCategoryConstants.ELECTRICITY: MainCategory.BILLS,
        SubCategoryConstants.WATER: MainCategory.BILLS,
        SubCategoryConstants.GAS: MainCategory.BILLS,
        SubCategoryConstants.INTERNET: MainCategory.BILLS,
        SubCategoryConstants.MOBILE: MainCategory.BILLS,
        SubCategoryConstants.DTH: MainCategory.BILLS,
        SubCategoryConstants.MAINTENANCE: MainCategory.BILLS,
        SubCategoryConstants.PROPERTY_TAX: MainCategory.BILLS,
        
        # Shopping
        SubCategoryConstants.CLOTHING: MainCategory.SHOPPING,
        SubCategoryConstants.ELECTRONICS: MainCategory.SHOPPING,
        SubCategoryConstants.GROCERIES_SHOPPING: MainCategory.SHOPPING,
        SubCategoryConstants.HOME_APPLIANCES: MainCategory.SHOPPING,
        SubCategoryConstants.FURNITURE: MainCategory.SHOPPING,
        SubCategoryConstants.BOOKS: MainCategory.SHOPPING,
        
        # Entertainment
        SubCategoryConstants.MOVIES: MainCategory.ENTERTAINMENT,
        SubCategoryConstants.CONCERT: MainCategory.ENTERTAINMENT,
        SubCategoryConstants.NETFLIX: MainCategory.ENTERTAINMENT,
        SubCategoryConstants.AMAZON_PRIME: MainCategory.ENTERTAINMENT,
        SubCategoryConstants.HOTSTAR: MainCategory.ENTERTAINMENT,
        SubCategoryConstants.GAMING: MainCategory.ENTERTAINMENT,
        SubCategoryConstants.SPORTS: MainCategory.ENTERTAINMENT,
        SubCategoryConstants.PARTY_ENTERTAINMENT: MainCategory.ENTERTAINMENT,
        
        # Healthcare
        SubCategoryConstants.DOCTOR: MainCategory.HEALTHCARE,
        SubCategoryConstants.DENTIST: MainCategory.HEALTHCARE,
        SubCategoryConstants.MEDICINE: MainCategory.HEALTHCARE,
        SubCategoryConstants.HOSPITAL: MainCategory.HEALTHCARE,
        SubCategoryConstants.LAB_TESTS: MainCategory.HEALTHCARE,
        SubCategoryConstants.PHYSIOTHERAPY: MainCategory.HEALTHCARE,
        SubCategoryConstants.FITNESS: MainCategory.HEALTHCARE,
        SubCategoryConstants.GYM: MainCategory.HEALTHCARE,
        
        # Education
        SubCategoryConstants.SCHOOL_FEES: MainCategory.EDUCATION,
        SubCategoryConstants.COLLEGE_FEES: MainCategory.EDUCATION,
        SubCategoryConstants.BOOKS_EDUCATION: MainCategory.EDUCATION,
        SubCategoryConstants.COURSES: MainCategory.EDUCATION,
        SubCategoryConstants.TUITION: MainCategory.EDUCATION,
        SubCategoryConstants.EXAM_FEES: MainCategory.EDUCATION,
        SubCategoryConstants.STATIONERY: MainCategory.EDUCATION,
        
        # Fuel
        SubCategoryConstants.PETROL: MainCategory.FUEL,
        SubCategoryConstants.DIESEL: MainCategory.FUEL,
        SubCategoryConstants.CNG: MainCategory.FUEL,
        SubCategoryConstants.EV_CHARGING: MainCategory.FUEL,
        
        # Insurance
        SubCategoryConstants.HEALTH_INSURANCE: MainCategory.INSURANCE,
        SubCategoryConstants.LIFE_INSURANCE: MainCategory.INSURANCE,
        SubCategoryConstants.VEHICLE_INSURANCE: MainCategory.INSURANCE,
        SubCategoryConstants.HOME_INSURANCE: MainCategory.INSURANCE,
        SubCategoryConstants.TRAVEL_INSURANCE: MainCategory.INSURANCE,
        
        # Investment
        SubCategoryConstants.STOCKS: MainCategory.INVESTMENT,
        SubCategoryConstants.MUTUAL_FUNDS: MainCategory.INVESTMENT,
        SubCategoryConstants.FIXED_DEPOSIT: MainCategory.INVESTMENT,
        SubCategoryConstants.PPF: MainCategory.INVESTMENT,
        SubCategoryConstants.NPS: MainCategory.INVESTMENT,
        SubCategoryConstants.GOLD: MainCategory.INVESTMENT,
        SubCategoryConstants.REAL_ESTATE: MainCategory.INVESTMENT,
    }
    
    @classmethod
    def get_main_category(cls, sub_category: str) -> MainCategory:
        """Get main category for a subcategory"""
        if not sub_category:
            return MainCategory.MISCELLANEOUS
        return cls.SUBCATEGORY_TO_MAIN.get(sub_category.lower(), MainCategory.MISCELLANEOUS)
    
    @classmethod
    def get_all_subcategories(cls, main_category: MainCategory) -> list:
        """Get all subcategories for a main category"""
        return [key for key, value in cls.SUBCATEGORY_TO_MAIN.items() if value == main_category]