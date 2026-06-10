"""Analyze a bill PDF, create mobile/wifi policy, evaluate reimbursement."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PDF = r"e:\Downloads\10101032375955_May2026.pdf"


def main():
    if not Path(PDF).exists():
        print(json.dumps({"error": f"File not found: {PDF}"}))
        sys.exit(1)

    from app.services.ocr_service import OCRProcessor
    from app.utils.ocr_categories import classify_bill, resolve_classification
    from app.database import SessionLocal
    from app.models import MainCategory, Policy, PolicyStatus, User, UserRole, Department
    from app.services.policy_service import PolicyService
    from app.services.claim_service import ClaimService

    proc = OCRProcessor()
    extracted = proc.process_pdf_sync(PDF)
    raw = extracted.get("raw_text", "") or ""
    classification = classify_bill(extracted, raw)
    tt, mc, sub = resolve_classification(extracted, raw)

    bill_amount = extracted.get("total_amount") or extracted.get("subtotal")
    bill_date = extracted.get("bill_date")

    ocr_summary = {
        "file": PDF,
        "vendor_name": extracted.get("vendor_name"),
        "restaurant_name": extracted.get("restaurant_name"),
        "customer_name": extracted.get("customer_name"),
        "bill_number": extracted.get("bill_number"),
        "bill_date": str(bill_date) if bill_date else None,
        "due_date": str(extracted.get("due_date")) if extracted.get("due_date") else None,
        "subtotal": extracted.get("subtotal"),
        "total_amount": extracted.get("total_amount"),
        "tax_amount": extracted.get("tax_amount"),
        "tax_breakdown": extracted.get("tax_breakdown"),
        "discount_amount": extracted.get("discount_amount"),
        "payment_method": extracted.get("payment_method"),
        "payment_status": extracted.get("payment_status"),
        "payment_transaction_id": extracted.get("payment_transaction_id"),
        "vendor_gst": extracted.get("vendor_gst"),
        "vendor_address": (extracted.get("vendor_address") or "")[:200] or None,
        "confidence_score": extracted.get("confidence_score"),
        "classification": classification,
        "transaction_type": tt.value,
        "main_category": mc.value,
        "sub_category": sub,
        "raw_text_length": len(raw),
        "raw_text_preview": raw[:3000],
    }

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.is_admin.is_(True)).first()
        if not admin:
            admin = db.query(User).filter(User.username == "devuser").first()
        if not admin:
            admin = User(
                email="dev@local.test",
                username="devuser",
                hashed_password="not-used",
                full_name="Dev User",
                is_active=True,
                is_admin=True,
                role=UserRole.EMPLOYEE,
                department=Department.ENGINEERING,
            )
            db.add(admin)
            db.flush()

        policy_code = "POL-MOBILE-WIFI-5000"
        ps = PolicyService(db)
        policy = ps.get_policy_by_code(policy_code)
        policy_created = False
        if not policy:
            policy_created = True
            policy = ps.create_policy(
                {
                    "policy_id": policy_code,
                    "policy_name": "Mobile & WiFi Bills Reimbursement 2026",
                    "policy_type": "utilities",
                    "description": (
                        "Reimbursement for employee mobile and broadband/WiFi utility bills "
                        "up to INR 5000 per claim."
                    ),
                    "maximum_amount": 5000.0,
                    "minimum_amount": 0.0,
                    "coverage_percentage": 100.0,
                    "main_category": MainCategory.POLICY,
                    "sub_category": "bills",
                    "requires_approval": True,
                    "approval_flow": ["department_head", "manager"],
                    "terms_and_conditions": (
                        "Valid mobile postpaid/prepaid and broadband/WiFi bills only. "
                        "Bill amount above 5000 is not reimbursable under this policy."
                    ),
                    "exclusions": "Personal entertainment packs, device purchase, roaming beyond plan.",
                    "valid_from": datetime.now(timezone.utc),
                    "valid_to": None,
                },
                admin.id,
            )

        db.commit()
        db.refresh(policy)

        claim_service = ClaimService(db)
        def _grab(pat: str, flags=0):
            import re

            m = re.search(pat, raw, flags)
            return m.group(1).strip() if m else None

        payable_str = _grab(r"Total Amount Payable:\s*[^\d]*([\d,]+\.?\d*)")
        correct_amount = (
            float(payable_str.replace(",", "")) if payable_str else None
        )

        amount = float(bill_amount) if bill_amount else 0.0
        if correct_amount and correct_amount != amount:
            amount_for_policy = correct_amount
            amount_source = "manual_parse_total_amount_payable"
            ocr_amount_mismatch = {
                "ocr_parsed_total": bill_amount,
                "correct_total_payable": correct_amount,
            }
        else:
            amount_for_policy = amount
            amount_source = "ocr_parser"
            ocr_amount_mismatch = None

        policy_validation = claim_service.validate_claim_against_policy(
            amount_for_policy, policy
        )
        over_limit = (
            claim_service.exceeds_policy_limit(amount_for_policy, policy)
            if amount_for_policy
            else True
        )
        approved_if_within = (
            claim_service.calculate_approved_amount(amount_for_policy, policy)
            if amount_for_policy and not over_limit
            else 0
        )

        expense_main_for_policy = PolicyService.expense_category_for_policy(policy)

        corpus = raw.lower()
        mobile_wifi_signals = [
            "airtel", "jio", "vodafone", "vi ", "bsnl", "broadband", "wifi", "wi-fi",
            "internet", "mobile", "postpaid", "prepaid", "fiber", "bharat fiber",
        ]
        bill_matches_policy_scope = any(s in corpus for s in mobile_wifi_signals) or mc == MainCategory.BILLS or mc == MainCategory.UTILITIES

        manual_fields = {
            "provider": "Bharti Airtel Limited" if "Bharti Airtel" in raw else None,
            "one_airtel_id": _grab(r"One Airtel ID\s*(\d+)"),
            "customer_name": _grab(r"(MOHAMMED KHWAJA NIZAMUDDIN)"),
            "registered_email": _grab(r"Registered Email:\s*(\S+)"),
            "registered_mobile": _grab(r"RTN\):\s*(\d+)"),
            "plan": _grab(r"Your Plan:\s*([^\n]+)"),
            "statement_date": _grab(r"Statement Date\s*(\d+ \w+ \d+)"),
            "statement_period": _grab(r"Statement Period\s*([^\n]+)"),
            "total_amount_payable_inr": correct_amount,
            "due_date": _grab(r"Due Date:\s*([^\n]+)"),
            "wifi_id": _grab(r"Wi-Fi ID\s*:\s*(\S+)"),
            "fixedline_number": _grab(r"Fixedline number\s*:\s*(\d+)"),
            "account_no": _grab(r"Account No\s*(\d+)"),
            "bill_no": _grab(r"Bill NO\s*(\S+)") or extracted.get("bill_number"),
            "bill_date": _grab(r"Bill Date\s*(\d+ \w+ \d+)"),
            "connections": _grab(r"Number of connections\s*(\d+)"),
            "amazon_prime_wifi_charge_inr": _grab(
                r"Amazon Prime[^0-9]*([\d,]+\.?\d*)"
            ),
            "correct_category": {
                "main_category": "bills",
                "sub_category": "mobile",
                "transaction_type": "expense",
            },
        }

        if not amount_for_policy:
            reimbursement_verdict = "CANNOT_DECIDE"
            reimbursement_reason = "OCR could not extract a reliable bill amount from the PDF."
        elif not policy_validation["is_valid"]:
            reimbursement_verdict = "NO"
            reimbursement_reason = policy_validation["reason"]
        elif over_limit:
            reimbursement_verdict = "NO"
            reimbursement_reason = (
                f"Bill amount {amount_for_policy} exceeds policy maximum {policy.maximum_amount}. "
                "Recorded as personal expense, not reimbursable."
            )
        elif tt.value != "expense":
            reimbursement_verdict = "NO"
            reimbursement_reason = f"Transaction type is {tt.value}; policy covers expense bills only."
        elif not bill_matches_policy_scope:
            reimbursement_verdict = "LIKELY_NO"
            reimbursement_reason = (
                "Bill category does not clearly match mobile/WiFi utilities scope "
                f"(detected: {mc.value}/{sub}). Manual review recommended."
            )
        else:
            reimbursement_verdict = "YES_PENDING_APPROVAL"
            reimbursement_reason = (
                f"Amount {amount_for_policy} is within policy limit {policy.maximum_amount}. "
                f"Approved amount would be {approved_if_within} after dept head + manager approval."
            )

        result = {
            "manual_fields_from_pdf": manual_fields,
            "ocr_amount_mismatch": ocr_amount_mismatch,
            "ocr_extraction": ocr_summary,
            "policy": {
                "created_new": policy_created,
                "id": policy.id,
                "policy_id": policy.policy_id,
                "policy_name": policy.policy_name,
                "maximum_amount": policy.maximum_amount,
                "sub_category": policy.sub_category,
                "policy_type": policy.policy_type,
                "expense_category_mapping": expense_main_for_policy.value,
            },
            "reimbursement_check": {
                "bill_amount_used": amount_for_policy,
                "amount_source": amount_source,
                "policy_active": policy_validation,
                "over_policy_limit": over_limit,
                "calculated_approved_amount": approved_if_within,
                "matches_mobile_wifi_scope": bill_matches_policy_scope,
                "verdict": reimbursement_verdict,
                "reason": reimbursement_reason,
            },
        }
        print(json.dumps(result, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
