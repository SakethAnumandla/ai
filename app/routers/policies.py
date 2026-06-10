"""Policy CRUD — manual entry and OCR scan."""
from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.dependencies import get_current_admin_user, get_current_user
from app.models import MainCategory, Policy, PolicyStatus
from app.schemas import PolicyCreate, PolicyUpdate, PolicyResponse, get_policy_types
from app.services.policy_service import PolicyService, POLICY_SUB_CATEGORIES
from app.utils.file_upload import process_uploaded_file
from app.utils.policy_helpers import build_policy_response
from app.utils.policy_ocr import process_policy_with_ocr
from app.utils.payment_modes import list_payment_modes
from app.utils.tax_regimes import POLICY_TYPE_DEFAULT_TAX, get_regime

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("/types")
async def list_policy_types():
    types = get_policy_types()
    for pt in types:
        code = pt["value"]
        tax = POLICY_TYPE_DEFAULT_TAX.get(code, POLICY_TYPE_DEFAULT_TAX["general"])
        regime = get_regime(tax["country_code"])
        pt["default_tax"] = {
            **tax,
            "regime_label": regime["regime_label"] if regime else None,
        }
    return {
        "policy_types": types,
        "sub_categories": [{"value": s, "label": s.replace("_", " ").title()} for s in POLICY_SUB_CATEGORIES],
        "main_category": MainCategory.POLICY.value,
        "tax_note": "Set country_code and tax_regime on create, or use defaults per policy_type.",
        "payment_modes": list_payment_modes()["payment_modes"],
        "default_payment_mode": list_payment_modes()["default"],
    }


@router.post("", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
@router.post("/create", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
    policy_data: PolicyCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin_user),
):
    """Create policy from JSON body (use POST /policies/scan-ocr for document upload)."""
    service = PolicyService(db)
    if service.get_policy_by_code(policy_data.policy_id):
        raise HTTPException(status_code=400, detail="Policy ID already exists")

    payload = policy_data.model_dump()
    policy = service.create_policy(payload, current_user.id)
    db.commit()
    db.refresh(policy)
    return build_policy_response(policy)


@router.post("/scan-ocr", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
async def scan_policy_ocr(
    file: UploadFile = File(...),
    policy_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin_user),
):
    file_data = await process_uploaded_file(file)
    extracted = await process_policy_with_ocr(
        file_data["file_data"], file_data["file_name"]
    )

    code = policy_id or f"POL-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    service = PolicyService(db)
    if service.get_policy_by_code(code):
        raise HTTPException(status_code=400, detail="Policy ID already exists")

    payload = {
        **extracted,
        "policy_id": code,
        "is_ocr_created": True,
        "original_file_data": file_data["file_data"],
        "original_file_name": file_data["file_name"],
        "requires_approval": True,
        "approval_flow": ["department_head", "manager"],
    }
    policy = service.create_policy(payload, current_user.id)
    db.commit()
    db.refresh(policy)
    return build_policy_response(policy)


@router.get("", response_model=List[PolicyResponse])
@router.get("/", response_model=List[PolicyResponse])
async def get_policies(
    status_filter: Optional[PolicyStatus] = None,
    policy_type: Optional[str] = None,
    main_category: Optional[MainCategory] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = PolicyService(db)
    policies = service.list_policies(
        status=status_filter,
        policy_type=policy_type,
        main_category=main_category,
        skip=skip,
        limit=limit,
    )
    return [build_policy_response(p) for p in policies]


@router.get("/{policy_id}/tax-regime")
async def get_policy_tax_regime(
    policy_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Tax regime linked to this policy (for claim bill entry)."""
    from app.utils.policy_tax import policy_tax_context
    from app.utils.tax_regimes import get_regime

    policy = PolicyService(db).get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    ctx = policy_tax_context(policy)
    regime = get_regime(ctx["country_code"])
    pm_catalog = list_payment_modes()["payment_modes"]
    allowed = policy.allowed_payment_modes
    if allowed:
        pm_catalog = [m for m in pm_catalog if m["value"] in allowed]
    pm = policy.payment_method.value if hasattr(policy.payment_method, "value") else policy.payment_method
    return {
        "policy_id": policy.id,
        "policy_code": policy.policy_id,
        "tax_context": ctx,
        "regime": regime,
        "payment_method": pm,
        "payment_mode": pm,
        "allowed_payment_modes": allowed,
        "payment_modes": pm_catalog,
    }


@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    policy = PolicyService(db).get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return build_policy_response(policy)


@router.put("/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: int,
    policy_update: PolicyUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin_user),
):
    service = PolicyService(db)
    policy = service.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    service.update_policy(policy, policy_update.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(policy)
    return build_policy_response(policy)


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin_user),
):
    service = PolicyService(db)
    policy = service.get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    try:
        service.delete_policy(policy)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return None
