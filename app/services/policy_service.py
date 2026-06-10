"""Policy CRUD and validation."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

from sqlalchemy.orm import Session

from app.models import MainCategory, PaymentMethod, Policy, PolicyStatus
from app.utils.payment_modes import normalize_payment_mode
from app.utils.tax_regimes import resolve_policy_tax_settings

POLICY_SUB_CATEGORIES = [
    "all",
    "travel",
    "food",
    "healthcare",
    "bills",
    "shopping",
    "entertainment",
    "education",
    "fuel",
    "insurance",
    "utilities",
    "groceries",
    "miscellaneous",
]

POLICY_TYPE_TO_SUB = {
    "medical": "healthcare",
    "healthcare": "healthcare",
    "travel": "travel",
    "food": "food",
    "education": "education",
    "fuel": "fuel",
    "general": "all",
}

POLICY_SUB_TO_EXPENSE_MAIN = {
    "all": MainCategory.MISCELLANEOUS,
    "travel": MainCategory.TRAVEL,
    "food": MainCategory.FOOD,
    "healthcare": MainCategory.HEALTHCARE,
    "bills": MainCategory.BILLS,
    "shopping": MainCategory.SHOPPING,
    "entertainment": MainCategory.ENTERTAINMENT,
    "education": MainCategory.EDUCATION,
    "fuel": MainCategory.FUEL,
    "insurance": MainCategory.INSURANCE,
    "utilities": MainCategory.UTILITIES,
    "groceries": MainCategory.GROCERIES,
    "miscellaneous": MainCategory.MISCELLANEOUS,
}


class PolicyService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def normalize_sub_category(policy_type: str, sub_category: Optional[str]) -> str:
        sub = (sub_category or POLICY_TYPE_TO_SUB.get(policy_type, "all")).lower()
        if sub not in POLICY_SUB_CATEGORIES:
            sub = POLICY_TYPE_TO_SUB.get(policy_type, "all")
        return sub

    @staticmethod
    def expense_category_for_policy(policy: Policy) -> MainCategory:
        sub = (policy.sub_category or "all").lower()
        if policy.policy_type in POLICY_TYPE_TO_SUB:
            sub = POLICY_TYPE_TO_SUB[policy.policy_type]
        return POLICY_SUB_TO_EXPENSE_MAIN.get(sub, MainCategory.MISCELLANEOUS)

    def list_policies(
        self,
        *,
        status: Optional[PolicyStatus] = None,
        policy_type: Optional[str] = None,
        main_category: Optional[MainCategory] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Policy]:
        query = self.db.query(Policy)
        if status:
            query = query.filter(Policy.status == status)
        if policy_type:
            query = query.filter(Policy.policy_type == policy_type)
        if main_category:
            query = query.filter(Policy.main_category == main_category)
        return query.order_by(Policy.created_at.desc()).offset(skip).limit(limit).all()

    def get_policy(self, policy_id: int) -> Optional[Policy]:
        return self.db.query(Policy).filter(Policy.id == policy_id).first()

    def get_policy_by_code(self, policy_code: str) -> Optional[Policy]:
        return self.db.query(Policy).filter(Policy.policy_id == policy_code).first()

    @staticmethod
    def apply_tax_fields(data: Dict[str, Any], policy_type: str) -> Dict[str, Any]:
        tax = resolve_policy_tax_settings(
            policy_type,
            country_code=data.get("country_code"),
            tax_regime=data.get("tax_regime"),
            applicable_tax_types=data.get("applicable_tax_types"),
            document_text=data.get("raw_text") or data.get("description"),
        )
        return {
            "country_code": tax["country_code"],
            "tax_regime": tax["tax_regime"],
            "applicable_tax_types": tax["applicable_tax_types"],
        }

    def create_policy(self, data: Dict[str, Any], created_by: int) -> Policy:
        sub = self.normalize_sub_category(data.get("policy_type", "general"), data.get("sub_category"))
        tax_fields = self.apply_tax_fields(data, data.get("policy_type", "general"))
        policy = Policy(
            policy_id=data["policy_id"],
            policy_name=data["policy_name"],
            policy_type=data["policy_type"],
            description=data.get("description"),
            maximum_amount=data["maximum_amount"],
            minimum_amount=data.get("minimum_amount", 0.0),
            coverage_percentage=data.get("coverage_percentage", 100.0),
            main_category=data.get("main_category") or MainCategory.POLICY,
            sub_category=sub,
            requires_approval=data.get("requires_approval", True),
            approval_flow=data.get("approval_flow") or ["department_head", "manager"],
            terms_and_conditions=data.get("terms_and_conditions"),
            exclusions=data.get("exclusions"),
            documentation_required=data.get("documentation_required"),
            valid_from=data["valid_from"],
            valid_to=data.get("valid_to"),
            status=PolicyStatus.ACTIVE,
            created_by=created_by,
            is_ocr_created=data.get("is_ocr_created", False),
            original_file_data=data.get("original_file_data"),
            original_file_name=data.get("original_file_name"),
            country_code=tax_fields["country_code"],
            tax_regime=tax_fields["tax_regime"],
            applicable_tax_types=tax_fields["applicable_tax_types"],
            tax_inclusive=bool(data.get("tax_inclusive", False)),
            payment_method=(
                PaymentMethod(pm)
                if (pm := normalize_payment_mode(data.get("payment_method")))
                else None
            ),
            allowed_payment_modes=data.get("allowed_payment_modes"),
        )
        self.db.add(policy)
        self.db.flush()
        return policy

    def update_policy(self, policy: Policy, updates: Dict[str, Any]) -> Policy:
        for field, value in updates.items():
            if value is not None and hasattr(policy, field):
                setattr(policy, field, value)
        if "policy_type" in updates or "sub_category" in updates:
            policy.sub_category = self.normalize_sub_category(
                policy.policy_type, policy.sub_category
            )
        if any(k in updates for k in ("policy_type", "country_code", "tax_regime", "applicable_tax_types")):
            merged = {
                "country_code": policy.country_code,
                "tax_regime": policy.tax_regime,
                "applicable_tax_types": policy.applicable_tax_types,
                **{k: updates[k] for k in updates if k in ("country_code", "tax_regime", "applicable_tax_types")},
            }
            tax_fields = self.apply_tax_fields(
                {**merged, "policy_type": policy.policy_type},
                policy.policy_type,
            )
            policy.country_code = tax_fields["country_code"]
            policy.tax_regime = tax_fields["tax_regime"]
            policy.applicable_tax_types = tax_fields["applicable_tax_types"]
        policy.updated_at = _utc_now()
        self.db.flush()
        return policy

    def delete_policy(self, policy: Policy) -> None:
        if policy.claims:
            raise ValueError("Cannot delete policy with existing claims")
        self.db.delete(policy)

    def validate_policy_active(self, policy: Policy) -> Dict[str, Any]:
        now = _utc_now()
        valid_from = _as_utc(policy.valid_from)
        valid_to = _as_utc(policy.valid_to)
        if policy.status != PolicyStatus.ACTIVE:
            return {"is_valid": False, "reason": f"Policy is {policy.status.value}"}
        if valid_from and now < valid_from:
            return {"is_valid": False, "reason": "Policy is not yet effective"}
        if valid_to and now > valid_to:
            return {"is_valid": False, "reason": "Policy has expired"}
        return {"is_valid": True, "reason": None}

    def is_amount_within_limit(self, amount: float, policy: Policy) -> bool:
        return amount <= policy.maximum_amount

    @staticmethod
    def resolve_payment_method(
        policy: Policy, payment_method: Optional[str] = None
    ) -> Optional[str]:
        pm = normalize_payment_mode(payment_method)
        if not pm and policy.payment_method:
            pm = (
                policy.payment_method.value
                if hasattr(policy.payment_method, "value")
                else policy.payment_method
            )
        allowed = policy.allowed_payment_modes
        if pm and allowed and pm not in allowed:
            raise ValueError(
                f"Payment mode '{pm}' is not allowed for this policy. "
                f"Allowed: {', '.join(allowed)}"
            )
        return pm
