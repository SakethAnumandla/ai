# schemas.py - Complete with Policy & Claims Support
from pydantic import BaseModel, ConfigDict, Field, validator, root_validator
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

# ==================== Existing Enums ====================

class TransactionType(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"

class ExpenseStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"  # legacy alias for submitted
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"

# Main Categories
class MainCategory(str, Enum):
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

# Sub Categories enums
class TravelSubCategory(str, Enum):
    UBER = "uber"
    RAPIDO = "rapido"
    OLA = "ola"
    METRO = "metro"
    BUS = "bus"
    TRAIN = "train"
    FLIGHT = "flight"
    TAXI = "taxi"
    AUTO = "auto"
    FUEL = "fuel"
    PARKING = "parking"
    TOLL = "toll"
    CAR_RENTAL = "car_rental"
    ACCOMMODATION = "accommodation"
    FOOD_DURING_TRAVEL = "food_during_travel"
    ENTERTAINMENT_DURING_TRAVEL = "entertainment_during_travel"
    OTHERS = "others"
    NONE = "none"

class FoodSubCategory(str, Enum):
    SWIGGY = "swiggy"
    ZOMATO = "zomato"
    DINING = "dining"
    CAFE = "cafe"
    GROCERIES = "groceries"
    RESTAURANT = "restaurant"
    STREET_FOOD = "street_food"
    PARTY = "party"
    OFFICE_LUNCH = "office_lunch"

# ==================== New Policy Enums ====================

class PolicyStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    EXPIRED = "expired"
    DRAFT = "draft"

class ClaimStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REIMBURSED = "reimbursed"

class ApprovalLevel(str, Enum):
    DEPARTMENT_HEAD = "department_head"
    MANAGER = "manager"
    FINANCE = "finance"
    HR = "hr"

class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUESTED_CHANGES = "requested_changes"

class Department(str, Enum):
    SALES = "sales"
    MARKETING = "marketing"
    ENGINEERING = "engineering"
    HR = "hr"
    FINANCE = "finance"
    OPERATIONS = "operations"
    ADMIN = "admin"

# ==================== Category Mapping ====================

CATEGORY_SUBCATEGORY_MAPPING = {
    MainCategory.TRAVEL: [item.value for item in TravelSubCategory],
    MainCategory.FOOD: [item.value for item in FoodSubCategory],
    MainCategory.BILLS: ["electricity", "water", "gas", "internet", "mobile", "dth", "maintenance", "property_tax"],
    MainCategory.INSURANCE: ["health_insurance", "life_insurance", "vehicle_insurance", "home_insurance", "travel_insurance"],
    MainCategory.SHOPPING: ["clothing", "electronics", "groceries", "home_appliances", "furniture", "books", "medicine"],
    MainCategory.ENTERTAINMENT: ["movies", "concert", "netflix", "amazon_prime", "hotstar", "gaming", "sports", "party"],
    MainCategory.HEALTHCARE: ["doctor", "dentist", "medicine", "hospital", "lab_tests", "physiotherapy", "fitness", "gym"],
    MainCategory.EDUCATION: ["school_fees", "college_fees", "books", "courses", "tuition", "exam_fees", "stationery"],
    MainCategory.FUEL: ["petrol", "diesel", "cng", "ev_charging"],
    MainCategory.INVESTMENT: ["stocks", "mutual_funds", "fixed_deposit", "ppf", "nps", "gold", "real_estate"],
}

# Category Hierarchy for Frontend
CATEGORY_HIERARCHY = {
    "travel": {
        "display_name": "Travel & Transport",
        "icon": "🚗",
        "color": "#4CAF50",
        "subcategories": {
            "uber": {"display_name": "Uber", "icon": "🚗", "color": "#000000"},
            "rapido": {"display_name": "Rapido", "icon": "🏍️", "color": "#FF5722"},
            "ola": {"display_name": "Ola", "icon": "🚕", "color": "#FFC107"},
            "metro": {"display_name": "Metro", "icon": "🚇", "color": "#2196F3"},
            "bus": {"display_name": "Bus", "icon": "🚌", "color": "#9E9E9E"},
            "train": {"display_name": "Train", "icon": "🚂", "color": "#795548"},
            "flight": {"display_name": "Flight", "icon": "✈️", "color": "#607D8B"},
            "taxi": {"display_name": "Taxi", "icon": "🚖", "color": "#FF9800"},
            "auto": {"display_name": "Auto Rickshaw", "icon": "🛺", "color": "#FFC107"},
            "fuel": {"display_name": "Fuel", "icon": "⛽", "color": "#F44336"},
            "parking": {"display_name": "Parking", "icon": "🅿️", "color": "#9E9E9E"},
            "toll": {"display_name": "Toll", "icon": "🛣️", "color": "#795548"},
            "car_rental": {"display_name": "Car Rental", "icon": "🚙", "color": "#3F51B5"},
            "accommodation": {"display_name": "Accommodation", "icon": "🏨", "color": "#5C6BC0"},
            "food_during_travel": {"display_name": "Food During Travel", "icon": "🍽️", "color": "#E65100"},
            "entertainment_during_travel": {"display_name": "Food & Entertainment", "icon": "🎭", "color": "#8E24AA"},
            "others": {"display_name": "Others", "icon": "📌", "color": "#9E9E9E"},
            "none": {"display_name": "None", "icon": "—", "color": "#BDBDBD"},
        }
    },
    "food": {
        "display_name": "Food & Dining",
        "icon": "🍔",
        "color": "#FF5722",
        "subcategories": {
            "swiggy": {"display_name": "Swiggy", "icon": "🍕", "color": "#FC8019"},
            "zomato": {"display_name": "Zomato", "icon": "🍜", "color": "#CB202D"},
            "dining": {"display_name": "Dining Out", "icon": "🍽️", "color": "#FFC107"},
            "cafe": {"display_name": "Cafe", "icon": "☕", "color": "#8D6E63"},
            "groceries": {"display_name": "Groceries", "icon": "🛒", "color": "#4CAF50"},
            "restaurant": {"display_name": "Restaurant", "icon": "🍴", "color": "#FF9800"},
            "street_food": {"display_name": "Street Food", "icon": "🍢", "color": "#FF5252"},
            "party": {"display_name": "Party/Friends", "icon": "🎉", "color": "#E91E63"},
            "office_lunch": {"display_name": "Office Lunch", "icon": "💼", "color": "#607D8B"}
        }
    },
    "bills": {
        "display_name": "Bills & Utilities",
        "icon": "📄",
        "color": "#2196F3",
        "subcategories": {
            "electricity": {"display_name": "Electricity", "icon": "⚡", "color": "#FFC107"},
            "water": {"display_name": "Water", "icon": "💧", "color": "#00BCD4"},
            "gas": {"display_name": "Gas", "icon": "🔥", "color": "#FF9800"},
            "internet": {"display_name": "Internet", "icon": "🌐", "color": "#3F51B5"},
            "mobile": {"display_name": "Mobile", "icon": "📱", "color": "#9C27B0"},
        }
    },
    "healthcare": {
        "display_name": "Healthcare",
        "icon": "🏥",
        "color": "#F44336",
        "subcategories": {
            "doctor": {"display_name": "Doctor", "icon": "👨‍⚕️", "color": "#E91E63"},
            "medicine": {"display_name": "Medicine", "icon": "💊", "color": "#FF9800"},
            "hospital": {"display_name": "Hospital", "icon": "🏥", "color": "#F44336"},
            "gym": {"display_name": "Gym", "icon": "💪", "color": "#4CAF50"},
        }
    }
}

# ==================== Tax Schemas ====================

class TaxCalculationType(str, Enum):
    PERCENTAGE = "percentage"
    FIXED_VALUE = "fixed_value"


class ExpenseTaxLineCreate(BaseModel):
    """User-defined tax line: custom label with percentage or fixed amount."""
    tax_label: str = Field(..., min_length=1, max_length=64, description="User label e.g. GST, CGST, Service Tax")
    calculation_type: TaxCalculationType = TaxCalculationType.FIXED_VALUE
    tax_rate: Optional[float] = Field(None, ge=0, le=100, description="Required when calculation_type=percentage")
    tax_amount: float = Field(..., ge=0, description="Tax amount in currency")
    taxable_amount: Optional[float] = Field(None, ge=0, description="Base amount for percentage taxes")
    # Legacy fields kept for OCR import compatibility
    tax_type: Optional[str] = Field(None, description="Deprecated; use tax_label")
    recoverable: bool = True

    @root_validator(skip_on_failure=True)
    def validate_percentage_rate(cls, values):
        calc = values.get("calculation_type")
        rate = values.get("tax_rate")
        if calc == TaxCalculationType.PERCENTAGE and rate is None:
            raise ValueError("tax_rate is required when calculation_type is percentage")
        return values


class ExpenseTaxLineResponse(BaseModel):
    id: int
    expense_id: int
    tax_label: Optional[str] = None
    calculation_type: Optional[str] = "fixed_value"
    tax_type: str
    tax_rate: Optional[float] = None
    taxable_amount: Optional[float] = None
    tax_amount: float
    recoverable: bool
    created_at: datetime
    # Legacy fields (hidden from primary UI)
    country_code: Optional[str] = None
    tax_regime: Optional[str] = None
    cgst: float = 0.0
    sgst: float = 0.0
    igst: float = 0.0
    vat: float = 0.0

    class Config:
        from_attributes = True


class ExpenseTaxSummary(BaseModel):
    line_count: int = 0
    taxable_amount: Optional[float] = None
    subtotal: Optional[float] = None
    total_tax: float = 0.0
    total_recoverable: float = 0.0
    lines: List[ExpenseTaxLineResponse] = []
    # Legacy (deprecated; country selection removed from UI)
    country_code: Optional[str] = None
    regime_code: Optional[str] = None
    regime_label: Optional[str] = None
    currency: Optional[str] = None
    currency_symbol: Optional[str] = None
    total_cgst: float = 0.0
    total_sgst: float = 0.0
    total_igst: float = 0.0
    total_vat: float = 0.0


class ExpenseTaxesReplaceRequest(BaseModel):
    tax_lines: List[ExpenseTaxLineCreate] = Field(
        default_factory=list,
        description="Multiple user-defined taxes with label and % or fixed value",
    )


# ==================== Expense Schemas ====================

class ExpenseBase(BaseModel):
    bill_name: str = Field(..., min_length=1, max_length=200)
    bill_amount: float = Field(..., gt=0)
    bill_date: datetime
    transaction_type: TransactionType
    main_category: MainCategory
    sub_category: Optional[str] = None
    line_item: Optional[str] = None
    financial_year: Optional[str] = None
    amount_excl_gst: Optional[float] = None
    gst_rate_pct: Optional[float] = None
    gst_amount: Optional[float] = None
    itc_eligible: Optional[bool] = False
    currency_code: Optional[str] = "EUR"
    description: Optional[str] = None
    payment_method: Optional[str] = None
    vendor_name: Optional[str] = None
    bill_number: Optional[str] = None
    tax_amount: Optional[float] = 0.0
    discount_amount: Optional[float] = 0.0
    country_code: Optional[str] = "IN"
    subtotal: Optional[float] = None
    hashtags: Optional[List[str]] = None
    submitted_by_name: Optional[str] = None
    submitted_by_role: Optional[str] = None

class ExpenseCreate(ExpenseBase):
    upload_method: str = "manual"
    file_data: Optional[bytes] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    
    @validator('bill_amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Amount must be positive')
        if v > 9999999:
            raise ValueError('Amount exceeds maximum limit')
        return v

    @validator("hashtags", pre=True)
    def normalize_hashtags_field(cls, v):
        if v is None:
            return v
        from app.utils.category_hashtags import normalize_hashtags_list

        return normalize_hashtags_list(v)
    
    @validator('sub_category')
    def validate_sub_category(cls, v, values):
        if v and 'main_category' in values:
            main_cat = values['main_category']
            if main_cat in CATEGORY_SUBCATEGORY_MAPPING:
                valid_sub_categories = CATEGORY_SUBCATEGORY_MAPPING[main_cat]
                if v.lower() not in valid_sub_categories:
                    raise ValueError(f"Invalid sub_category '{v}' for main_category '{main_cat.value}'")
            return v.lower()
        return v

class ExpenseUpdate(BaseModel):
    bill_name: Optional[str] = None
    bill_amount: Optional[float] = None
    bill_date: Optional[datetime] = None
    transaction_type: Optional[TransactionType] = None

    @validator("transaction_type", pre=True)
    def parse_transaction_type_field(cls, v):
        if v is None or v == "":
            return None
        from app.utils.transaction_parser import coerce_transaction_type

        return coerce_transaction_type(v)
    main_category: Optional[MainCategory] = None
    sub_category: Optional[str] = None
    line_item: Optional[str] = None
    financial_year: Optional[str] = None
    amount_excl_gst: Optional[float] = None
    gst_rate_pct: Optional[float] = None
    gst_amount: Optional[float] = None
    itc_eligible: Optional[bool] = None
    currency_code: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ExpenseStatus] = None
    vendor_name: Optional[str] = None
    bill_number: Optional[str] = None
    tax_amount: Optional[float] = None
    discount_amount: Optional[float] = None
    payment_method: Optional[str] = None
    payment_mode: Optional[str] = None
    hashtags: Optional[List[str]] = None
    country_code: Optional[str] = None
    subtotal: Optional[float] = None
    tax_lines: Optional[List[ExpenseTaxLineCreate]] = None
    submitted_by_name: Optional[str] = None
    submitted_by_role: Optional[str] = None

    @validator("hashtags", pre=True)
    def normalize_hashtags_field(cls, v):
        if v is None:
            return v
        from app.utils.category_hashtags import normalize_hashtags_list

        return normalize_hashtags_list(v)

class ExpenseFileResponse(BaseModel):
    id: int
    file_name: str
    file_size: int
    mime_type: str
    is_primary: bool
    file_url: str
    preview_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    can_preview: bool = True
    uploaded_at: datetime

    class Config:
        from_attributes = True

class ExpenseResponse(ExpenseBase):
    id: int
    user_id: int
    status: ExpenseStatus
    upload_method: str
    files: List[ExpenseFileResponse] = []
    hashtags: List[str] = []
    recommended_hashtags: List[str] = []
    manual_category: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    claim_id: Optional[int] = None
    file_url: Optional[str] = None
    preview_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    can_preview: bool = False
    is_duplicate: bool = False
    is_editable: bool = False
    approval_status: Optional[str] = None
    approval_stage_label: Optional[str] = None
    approval_chain: Optional[List[Dict[str, Any]]] = None
    approval_progress: Optional[List[Dict[str, Any]]] = None
    approval_remarks: Optional[List[Dict[str, Any]]] = None
    submitted_by_display: Optional[str] = None
    line_item: Optional[str] = None
    line_item_label: Optional[str] = None
    financial_year: Optional[str] = None
    amount_excl_gst: Optional[float] = None
    gst_rate_pct: Optional[float] = None
    gst_amount: Optional[float] = None
    itc_eligible: Optional[bool] = None
    currency_code: Optional[str] = "EUR"
    subtotal: Optional[float] = None
    tax_summary: Optional[ExpenseTaxSummary] = None
    payment_mode: Optional[str] = None
    # Preferred expense terminology (mirrors bill_* fields)
    expense_name: Optional[str] = None
    expense_amount: Optional[float] = None
    expense_date: Optional[datetime] = None
    expense_number: Optional[str] = None
    # Deprecated: country selection removed from UI
    country_code: Optional[str] = None

    class Config:
        from_attributes = True

    def model_post_init(self, __context) -> None:
        if self.payment_method and not self.payment_mode:
            self.payment_mode = self.payment_method

# ==================== Policy Schemas ====================

class PolicyBase(BaseModel):
    policy_id: str = Field(..., min_length=3, max_length=50)
    policy_name: str = Field(..., min_length=1, max_length=200)
    policy_type: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = None
    maximum_amount: float = Field(..., gt=0)
    minimum_amount: float = Field(0, ge=0)
    coverage_percentage: float = Field(100, ge=0, le=100)
    main_category: MainCategory = MainCategory.POLICY
    sub_category: Optional[str] = Field("all", description="Policy scope: all, travel, food, healthcare, …")
    requires_approval: bool = True
    approval_flow: Optional[List[str]] = None
    terms_and_conditions: Optional[str] = None
    exclusions: Optional[str] = None
    documentation_required: Optional[List[str]] = None
    valid_from: datetime
    valid_to: Optional[datetime] = None
    country_code: str = Field("IN", min_length=2, max_length=2)
    tax_regime: Optional[str] = Field(None, description="e.g. india_gst, uae_vat")
    applicable_tax_types: Optional[List[str]] = Field(
        None, description="cgst, sgst, igst, vat, …"
    )
    tax_inclusive: bool = False
    payment_method: Optional[str] = Field(
        None, description="Default payment mode for claims: cash, upi, credit_card, …"
    )
    allowed_payment_modes: Optional[List[str]] = Field(
        None, description="If set, only these modes allowed on claims"
    )

class PolicyCreate(PolicyBase):
    pass

class PolicyUpdate(BaseModel):
    policy_name: Optional[str] = None
    policy_type: Optional[str] = None
    description: Optional[str] = None
    maximum_amount: Optional[float] = None
    minimum_amount: Optional[float] = None
    coverage_percentage: Optional[float] = None
    main_category: Optional[MainCategory] = None
    sub_category: Optional[str] = None
    requires_approval: Optional[bool] = None
    approval_flow: Optional[List[str]] = None
    status: Optional[PolicyStatus] = None
    terms_and_conditions: Optional[str] = None
    exclusions: Optional[str] = None
    valid_to: Optional[datetime] = None
    country_code: Optional[str] = None
    tax_regime: Optional[str] = None
    applicable_tax_types: Optional[List[str]] = None
    tax_inclusive: Optional[bool] = None
    payment_method: Optional[str] = None
    allowed_payment_modes: Optional[List[str]] = None

class PolicyTaxContext(BaseModel):
    country_code: str
    tax_regime: str
    applicable_tax_types: List[str] = []
    tax_inclusive: bool = False
    regime_label: Optional[str] = None
    currency_symbol: Optional[str] = None


class PolicyResponse(PolicyBase):
    id: int
    status: PolicyStatus
    is_ocr_created: bool = False
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    tax_context: Optional[PolicyTaxContext] = None
    payment_mode: Optional[str] = None

    class Config:
        from_attributes = True

    def model_post_init(self, __context) -> None:
        if self.payment_method and not self.payment_mode:
            self.payment_mode = self.payment_method

# ==================== Claim Schemas ====================

class ClaimBase(BaseModel):
    policy_id: int
    bill_name: str = Field(..., min_length=1, max_length=200)
    bill_amount: float = Field(..., gt=0)
    bill_date: datetime
    bill_number: Optional[str] = None
    vendor_name: Optional[str] = None
    description: Optional[str] = None
    main_category: MainCategory
    sub_category: Optional[str] = None
    payment_method: Optional[str] = None

class ClaimCreate(ClaimBase):
    pass

class ClaimApprovalResponse(BaseModel):
    id: int
    claim_id: int
    approver_id: int
    approval_level: ApprovalLevel
    status: ApprovalStatus
    comments: Optional[str] = None
    approved_amount: Optional[float] = None
    assigned_at: datetime
    actioned_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class ClaimResponse(ClaimBase):
    id: int
    claim_number: str
    claimed_amount: float
    approved_amount: float
    reimbursed_amount: float
    status: ClaimStatus
    is_reimbursable: bool = True
    rejection_reason: Optional[str] = None
    deduction_reason: Optional[str] = None
    submitted_at: datetime
    approved_at: Optional[datetime] = None
    reimbursed_at: Optional[datetime] = None
    policy: Optional[PolicyResponse] = None
    approvals: List[ClaimApprovalResponse] = []
    file_url: Optional[str] = None
    expense_id: Optional[int] = None
    payment_method: Optional[str] = None
    payment_mode: Optional[str] = None

    class Config:
        from_attributes = True

    def model_post_init(self, __context) -> None:
        if self.payment_method and not self.payment_mode:
            self.payment_mode = self.payment_method


class ClaimSubmitResponse(BaseModel):
    claim: ClaimResponse
    outcome: str
    message: str
    linked_expense_id: Optional[int] = None
    transaction_type: Optional[str] = None
    policy_tax_context: Optional[PolicyTaxContext] = None
    tax_summary: Optional[ExpenseTaxSummary] = None


class ReimbursementRequest(BaseModel):
    claim_id: int
    bank_account_number: str = Field(..., min_length=9, max_length=18)
    ifsc_code: str = Field(..., min_length=11, max_length=11)
    account_holder_name: str = Field(..., min_length=1, max_length=100)

class ClaimSummary(BaseModel):
    total_claims: int
    pending_claims: int
    approved_claims: int
    rejected_claims: int
    reimbursed_claims: int
    total_claimed_amount: float
    total_approved_amount: float
    total_reimbursed_amount: float
    eligible_for_reimbursement: int = 0
    rejected_over_limit: int = 0

# ==================== Approval Schemas ====================

class ClaimApprovalUpdate(BaseModel):
    status: ApprovalStatus
    comments: Optional[str] = None
    approved_amount: Optional[float] = None

class ApprovalWorkflowResponse(BaseModel):
    claim_id: int
    total_approvals: int
    completed_approvals: int
    pending_approvals: int
    approval_details: List[ClaimApprovalResponse]

# ==================== OCR & Batch Schemas ====================

class OCRBillDetailResponse(BaseModel):
    id: int
    bill_number: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_gst: Optional[str] = None
    subtotal: Optional[float] = None
    total_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    tax_breakdown: Optional[Dict[str, Any]] = None
    payment_method: Optional[str] = None
    ride_distance: Optional[float] = None
    ride_duration: Optional[int] = None
    ride_type: Optional[str] = None
    pickup_location: Optional[str] = None
    dropoff_location: Optional[str] = None
    restaurant_name: Optional[str] = None
    items_list: Optional[List[Dict[str, Any]]] = None
    customer_name: Optional[str] = None
    confidence_score: Optional[float] = None

    class Config:
        from_attributes = True

class ExpenseDetailResponse(ExpenseResponse):
    ocr_details: Optional[OCRBillDetailResponse] = None

class BillPrefillData(BaseModel):
    """OCR/manual prefill payload for expense entry form."""
    bill_name: str
    bill_amount: float
    bill_date: datetime
    transaction_type: str = "expense"
    main_category: str
    manual_category: Optional[str] = None
    sub_category: Optional[str] = None
    line_item: Optional[str] = None
    line_item_label: Optional[str] = None
    financial_year: Optional[str] = None
    amount_excl_gst: Optional[float] = None
    gst_rate_pct: Optional[float] = None
    gst_amount: Optional[float] = None
    itc_eligible: Optional[bool] = None
    vendor_name: Optional[str] = None
    restaurant_name: Optional[str] = None
    description: Optional[str] = None
    file_name: str
    amount_needs_review: bool = False
    category_needs_review: bool = False
    scan_quality: Optional[str] = None
    retake_recommended: bool = False
    classification_confidence: Optional[float] = None
    bill_number: Optional[str] = None
    payment_method: Optional[str] = None
    payment_mode: Optional[str] = None
    subtotal: Optional[float] = None
    grand_total: Optional[float] = None
    tax_amount: Optional[float] = None
    hashtags: List[str] = []
    recommended_hashtags: List[str] = []
    tax_summary: Optional[ExpenseTaxSummary] = None
    tax_lines: List[ExpenseTaxLineCreate] = []
    # Expense terminology aliases for frontend
    expense_name: Optional[str] = None
    expense_amount: Optional[float] = None
    expense_date: Optional[datetime] = None
    expense_number: Optional[str] = None

    def model_post_init(self, __context) -> None:
        if not self.expense_name:
            self.expense_name = self.bill_name
        if self.expense_amount is None:
            self.expense_amount = self.bill_amount
        if not self.expense_date:
            self.expense_date = self.bill_date
        if not self.expense_number:
            self.expense_number = self.bill_number

class BillDraftItem(BaseModel):
    bill_index: int
    label: str
    expense_id: int
    is_duplicate: bool = False
    prefill: BillPrefillData
    files: List[ExpenseFileResponse] = []
    preview_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    can_preview: bool = False

class MultiBillDraftResponse(BaseModel):
    batch_id: int
    bills: List[BillDraftItem] = []
    failed: List[Dict[str, Any]] = []
    skipped_duplicates: List[Dict[str, Any]] = []
    message: Optional[str] = None

class OCRBillResponse(BaseModel):
    id: int
    user_id: int
    expense_id: Optional[int] = None
    batch_id: Optional[int] = None
    bill_number: Optional[str] = None
    bill_date: Optional[datetime] = None
    vendor_name: Optional[str] = None
    total_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    confidence_score: Optional[float] = None
    detected_main_category: Optional[MainCategory] = None
    detected_sub_category: Optional[str] = None
    original_file_name: Optional[str] = None

    class Config:
        from_attributes = True


class OCRBatchStatusResponse(BaseModel):
    batch_id: int
    status: str
    total_files: int
    processed_files: int
    batch_name: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    expenses: List[ExpenseResponse] = []
    failed_files: List[Dict[str, Any]] = []
    skipped_duplicates: List[Dict[str, Any]] = []

class BatchUploadResponse(BaseModel):
    batch_id: int
    total_files: int
    processed_files: int
    status: str
    expenses: List[ExpenseResponse] = []
    failed_files: List[Dict[str, Any]] = []
    message: Optional[str] = None
    status_url: Optional[str] = None

# ==================== Wallet Schemas ====================

class WalletResponse(BaseModel):
    id: int
    user_id: int
    balance: float
    total_income: float
    total_expense: float
    created_at: datetime
    updated_at: Optional[datetime] = None

class WalletTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: float
    transaction_type: TransactionType
    transaction_date: datetime
    description: Optional[str]
    expense_id: int

# ==================== Dashboard Schemas ====================

class DateRangeInfo(BaseModel):
    """Applied time filter metadata (returned with dashboard/wallet responses)."""
    period: str
    start_date: Optional[datetime] = None
    end_date: datetime
    label: str
    is_all_time: bool = False
    filter_type: str = "preset"  # preset | single_date | date_range


class DashboardStats(BaseModel):
    total_balance: float
    total_income: float
    total_expense: float
    pending_approvals: int
    draft_expenses: int


class DashboardStatsResponse(BaseModel):
    date_range: DateRangeInfo
    stats: DashboardStats


class CategoryWiseExpense(BaseModel):
    category: str
    total_amount: float
    percentage: float
    count: int


class DashboardOverviewResponse(BaseModel):
    """Single payload for mobile home screen with one time filter applied."""
    date_range: DateRangeInfo
    stats: DashboardStats
    category_breakdown: List[CategoryWiseExpense]
    recent_transactions: List[Dict[str, Any]]
    top_categories: List[Dict[str, Any]]


class WalletPeriodSummary(BaseModel):
    date_range: DateRangeInfo
    current_balance: float
    period_income: float
    period_expense: float
    period_net: float
    transaction_count: int


class WalletTransactionsPage(BaseModel):
    date_range: DateRangeInfo
    transactions: List["WalletTransactionResponse"]
    total: int
    skip: int
    limit: int


class MonthlySummary(BaseModel):
    month: str
    income: float
    expense: float
    net: float

# ==================== Approval Schema ====================

class ExpenseApproval(BaseModel):
    status: ExpenseStatus
    rejection_reason: Optional[str] = None
    comments: Optional[str] = None

class ExpenseSubmit(BaseModel):
    bill_name: str = Field(..., min_length=1, description="Expense name (required)")
    bill_amount: float = Field(..., gt=0, description="Expense amount (required)")
    bill_date: datetime
    main_category: MainCategory = Field(..., description="Category (required)")
    transaction_type: TransactionType = TransactionType.EXPENSE

    @validator("transaction_type", pre=True)
    def parse_transaction_type_field(cls, v):
        from app.utils.transaction_parser import coerce_transaction_type

        return coerce_transaction_type(v) or TransactionType.EXPENSE
    sub_category: Optional[str] = None
    line_item: Optional[str] = None
    description: Optional[str] = None
    payment_method: Optional[str] = None
    vendor_name: Optional[str] = None
    bill_number: Optional[str] = None
    tax_amount: Optional[float] = 0.0
    discount_amount: Optional[float] = 0.0
    hashtags: Optional[List[str]] = None
    subtotal: Optional[float] = None
    amount_excl_gst: Optional[float] = None
    gst_rate_pct: Optional[float] = None
    gst_amount: Optional[float] = None
    itc_eligible: Optional[bool] = None
    currency_code: Optional[str] = "EUR"
    tax_lines: Optional[List[ExpenseTaxLineCreate]] = None
    payment_mode: Optional[str] = None
    submitted_by_name: Optional[str] = None
    submitted_by_role: Optional[str] = None
    confirm_submit: bool = Field(
        False,
        description="Must be true to lock expense and submit for approval (no further edits)",
    )
    save_as_draft: bool = Field(
        False,
        description="If true, save changes but keep as draft (editable)",
    )
    auto_approve: bool = False

    @validator("hashtags", pre=True)
    def normalize_hashtags_field(cls, v):
        if v is None:
            return v
        from app.utils.category_hashtags import normalize_hashtags_list

        return normalize_hashtags_list(v)

    @root_validator(skip_on_failure=True)
    def validate_submit_confirmation(cls, values):
        if values.get("auto_approve"):
            return values
        if not values.get("save_as_draft") and not values.get("confirm_submit"):
            raise ValueError(
                "confirm_submit must be true to submit the expense for approval"
            )
        return values

# ==================== Helper Functions ====================

def get_category_hierarchy():
    """Get category hierarchy for frontend (business taxonomy)."""
    from app.data.business_taxonomy import get_taxonomy_hierarchy

    return get_taxonomy_hierarchy()


def get_category_hierarchy_legacy():
    """Legacy consumer category hierarchy."""
    main_categories = []
    for cat_value, cat_data in CATEGORY_HIERARCHY.items():
        main_categories.append({
            "value": cat_value,
            "display_name": cat_data["display_name"],
            "icon": cat_data["icon"],
            "color": cat_data["color"]
        })
    
    return {
        "main_categories": main_categories,
        "subcategories": CATEGORY_HIERARCHY
    }

def get_all_categories():
    """Get all categories for dropdowns"""
    main_cats = [{"value": cat.value, "label": cat.value.capitalize()} for cat in MainCategory]
    
    sub_cats = {}
    for main_cat in MainCategory:
        if main_cat in CATEGORY_SUBCATEGORY_MAPPING:
            sub_cats[main_cat.value] = [
                {"value": sub, "label": sub.replace('_', ' ').capitalize()}
                for sub in CATEGORY_SUBCATEGORY_MAPPING[main_cat]
            ]
    
    return {
        "main_categories": main_cats,
        "subcategories": sub_cats
    }

def get_policy_types() -> List[Dict[str, str]]:
    """Get available policy types"""
    return [
        {"value": "medical", "label": "Medical Insurance"},
        {"value": "travel", "label": "Travel Insurance"},
        {"value": "food", "label": "Food Allowance"},
        {"value": "education", "label": "Education Reimbursement"},
        {"value": "fuel", "label": "Fuel Reimbursement"},
        {"value": "general", "label": "General Policy"},
    ]

def get_approval_levels() -> List[Dict[str, str]]:
    """Get approval levels"""
    return [
        {"value": "department_head", "label": "Department Head"},
        {"value": "manager", "label": "Manager"},
        {"value": "finance", "label": "Finance Team"},
        {"value": "hr", "label": "HR"},
    ]