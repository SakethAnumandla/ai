"""OCR field confidence scoring — never blindly trust OCR."""
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.intelligence.receipt.explainability import OCRExplainabilityBuilder
from app.intelligence.schemas import FieldConfidence, ReceiptEntities


class OCRConfidenceScorer:
    def __init__(
        self,
        field_threshold: Optional[float] = None,
        overall_threshold: Optional[float] = None,
        explainability: Optional[OCRExplainabilityBuilder] = None,
    ):
        self._field_threshold = field_threshold or settings.ocr_field_confidence_threshold
        self._overall_threshold = overall_threshold or settings.ocr_overall_confidence_threshold
        self._explain = explainability or OCRExplainabilityBuilder()
        self._explain_enabled = settings.ocr_explainability_enabled

    def score_fields(self, normalized: Dict[str, Any]) -> Tuple[ReceiptEntities, List[str], List[str]]:
        base = float(normalized.get("confidence_score") or 0.5)
        field_map: Dict[str, FieldConfidence] = {}
        clarify: List[str] = []
        explanations: List[str] = []
        penalty_hints: Dict[str, Dict[str, float]] = {}

        def _fc(name: str, value: Any, boost: float = 0.0, penalty: float = 0.0) -> None:
            conf = max(0.1, min(1.0, base + boost - penalty))
            needs = conf < self._field_threshold or value is None
            hints: Dict[str, float] = {}
            if value is None:
                conf = 0.0
                needs = True
                hints["missing"] = 1.0
            if penalty > 0.2:
                hints["inconsistent"] = penalty
            if base < 0.45:
                hints["blur_hint"] = 1.0
            penalty_hints[name] = hints

            reason = None
            if self._explain_enabled:
                reason = self._explain.reason_for_field(
                    name,
                    value=value,
                    confidence=conf,
                    base_confidence=base,
                    field_threshold=self._field_threshold,
                    penalties=hints,
                )
                if reason and needs:
                    explanations.append(reason)

            field_map[name] = FieldConfidence(
                field=name,
                value=value,
                confidence=conf,
                needs_clarification=needs,
                source="ocr",
                confidence_reason=reason,
            )
            if needs and name in ("total", "merchant", "invoice_date"):
                clarify.append(name)

        _fc("merchant", normalized.get("merchant"), boost=0.1 if normalized.get("merchant") else -0.2)
        _fc("vendor_gst", normalized.get("vendor_gst"), boost=0.15 if normalized.get("vendor_gst") else 0)
        _fc("invoice_date", normalized.get("invoice_date"), boost=0.1 if normalized.get("invoice_date") else -0.15)
        _fc("invoice_id", normalized.get("invoice_id"))
        _fc("subtotal", normalized.get("subtotal"))
        _fc("total", normalized.get("total"), boost=0.15 if normalized.get("total") else -0.3)
        _fc("tax", normalized.get("tax"))

        overall = sum(f.confidence for f in field_map.values()) / max(len(field_map), 1)

        entities = ReceiptEntities(
            merchant=normalized.get("merchant"),
            vendor_gst=normalized.get("vendor_gst"),
            invoice_date=normalized.get("invoice_date"),
            invoice_id=normalized.get("invoice_id"),
            subtotal=normalized.get("subtotal"),
            total=normalized.get("total"),
            tax=normalized.get("tax"),
            currency=normalized.get("currency") or "INR",
            payment_method=normalized.get("payment_method"),
            field_confidence=field_map,
        )
        if overall < self._overall_threshold:
            for key in ("total", "merchant"):
                if key not in clarify:
                    clarify.append(key)
        return entities, list(dict.fromkeys(clarify)), list(dict.fromkeys(explanations))
