"""OCR field confidence explainability — rule-based reasons (phase 1)."""
from typing import Any, Dict, List, Optional


class OCRExplainabilityBuilder:
    """
    Build human-readable reasons for low field confidence.

    Phase 2 (future): image blur/contrast, OCR word scores, layout heuristics.
    """

    _FIELD_LABELS = {
        "merchant": "Merchant name",
        "vendor_gst": "Vendor GST",
        "invoice_date": "Invoice date",
        "invoice_id": "Invoice number",
        "subtotal": "Subtotal",
        "total": "Total amount",
        "tax": "Tax amount",
    }

    def reason_for_field(
        self,
        field: str,
        *,
        value: Any,
        confidence: float,
        base_confidence: float,
        field_threshold: float,
        penalties: Optional[Dict[str, float]] = None,
    ) -> Optional[str]:
        label = self._FIELD_LABELS.get(field, field.replace("_", " ").title())

        if value is None:
            return f"{label} could not be read from the receipt."

        if confidence >= field_threshold:
            return None

        reasons: List[str] = []
        penalties = penalties or {}

        if penalties.get("missing"):
            reasons.append(f"{label} was not detected in the OCR output.")
        if penalties.get("blur_hint"):
            reasons.append("the receipt image may be blurred or low resolution")
        if penalties.get("inconsistent"):
            reasons.append("extracted values do not match other fields on the receipt")

        if base_confidence < 0.45:
            reasons.append("overall OCR quality on this image appears low")

        if field == "total" and confidence < field_threshold:
            if not reasons:
                reasons.append(
                    "the total amount line may be unclear, cropped, or missing a nearby label"
                )

        if not reasons:
            reasons.append(
                f"confidence ({confidence:.0%}) is below the review threshold ({field_threshold:.0%})"
            )

        tail = reasons[0] if len(reasons) == 1 else "; ".join(reasons)
        return f"{label} confidence is low because {tail}."

    def summarize(self, field_reasons: Dict[str, Optional[str]]) -> List[str]:
        return [r for r in field_reasons.values() if r]
