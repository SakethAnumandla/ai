"""OCR scan quality — decide when to ask the user to retake a blurry/unreadable photo."""
from __future__ import annotations

from typing import Any, Dict, Optional

class OcrScanUnreadable(Exception):
    """Receipt image could not be parsed reliably enough to prefill the form."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        self.message = message
        super().__init__(message)


_USER_MESSAGES = {
    "no_text": (
        "Couldn't read receipt. Please retake the photo in good lighting "
        "with the receipt flat and in focus, then upload again."
    ),
    "image_too_blurry": (
        "Couldn't read receipt — this photo looks too blurry. "
        "Please retake it with the receipt flat, in focus, and well lit."
    ),
    "parse_failed": (
        "Couldn't read receipt. We couldn't identify the amount or merchant — "
        "please retake the photo or upload a clearer copy."
    ),
    "low_confidence": (
        "Couldn't read receipt — scan confidence was too low. "
        "Please retake the photo and try again."
    ),
}


def _quality_payload(
    quality: str,
    *,
    retake_recommended: bool,
    failure_reason: Optional[str] = None,
    user_message: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "quality": quality,
        "retake_recommended": retake_recommended,
        "failure_reason": failure_reason,
        "user_message": user_message,
    }


def assess_ocr_scan_quality(extracted: Dict[str, Any]) -> Dict[str, Any]:
    """
    Classify OCR output as good / partial / unreadable.
    Blur alone does not fail a scan when amounts and vendor were parsed cleanly.
    """
    raw = (extracted.get("raw_text") or "").strip()
    conf = float(extracted.get("confidence_score") or 0.0)
    engine_conf = float(extracted.get("ocr_engine_confidence") or 0.0)
    blurry = extracted.get("image_blurry") is True
    total = extracted.get("total_amount")
    vendor = (extracted.get("vendor_name") or extracted.get("restaurant_name") or "").strip()
    items = extracted.get("items_list") or []

    from app.services.ocr_draft_service import resolve_prefill_bill_amount

    amount, needs_review = resolve_prefill_bill_amount(extracted)
    has_amount = amount > 1.0 and not (needs_review and amount <= 1.5)
    has_vendor = len(vendor) >= 3
    has_items = len(items) >= 1
    text_len = len(raw)

    parse_signals = sum(
        [
            1 if has_amount else 0,
            1 if has_vendor else 0,
            1 if has_items else 0,
            1 if conf >= 45 else 0,
            1 if text_len >= 60 else 0,
        ]
    )
    parse_ok = parse_signals >= 2 or (has_amount and text_len >= 25)

    if text_len < 12:
        return _quality_payload(
            "unreadable",
            retake_recommended=True,
            failure_reason="no_text",
            user_message=_USER_MESSAGES["no_text"],
        )

    if not parse_ok:
        if blurry and text_len < 100:
            return _quality_payload(
                "unreadable",
                retake_recommended=True,
                failure_reason="image_too_blurry",
                user_message=_USER_MESSAGES["image_too_blurry"],
            )
        if engine_conf < 0.28 and not has_amount and conf < 30:
            return _quality_payload(
                "unreadable",
                retake_recommended=True,
                failure_reason="low_confidence",
                user_message=_USER_MESSAGES["low_confidence"],
            )
        return _quality_payload(
            "unreadable",
            retake_recommended=True,
            failure_reason="parse_failed",
            user_message=_USER_MESSAGES["parse_failed"],
        )

    if needs_review or (amount <= 1.0 and conf < 55):
        return _quality_payload(
            "partial",
            retake_recommended=False,
            user_message="Some fields need your review — please verify amount and category.",
        )

    return _quality_payload("good", retake_recommended=False)


def ensure_ocr_readable(extracted: Dict[str, Any]) -> Dict[str, Any]:
    """Attach scan quality to extracted dict; raise when the image cannot be used."""
    quality = assess_ocr_scan_quality(extracted)
    extracted["scan_quality"] = quality["quality"]
    extracted["retake_recommended"] = quality["retake_recommended"]
    if quality.get("failure_reason"):
        extracted["scan_failure_reason"] = quality["failure_reason"]
    if quality["quality"] == "unreadable":
        raise OcrScanUnreadable(
            quality.get("failure_reason") or "parse_failed",
            quality.get("user_message") or _USER_MESSAGES["parse_failed"],
        )
    return quality
