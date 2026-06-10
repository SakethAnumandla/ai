"""Generate transparent memory explanations for user-facing prompts."""
from typing import Any, Dict, Optional

from app.ai.schemas.memory_intelligence import MemoryExplanation


def _fmt_payment(method: str) -> str:
    if method.lower() == "upi":
        return "UPI"
    return method.replace("_", " ")


class MemoryExplanationBuilder:
    def payment_method(
        self,
        store: Dict[str, Any],
        *,
        category: Optional[str] = None,
    ) -> Optional[MemoryExplanation]:
        method = store.get("payment_method")
        if not method:
            return None

        candidates = store.get("candidates") or {}
        entry = candidates.get(method, {})
        weighted = float(entry.get("weighted_count", store.get("weighted_count", 0)))
        count = int(entry.get("count", store.get("count", 0)))
        confidence = float(store.get("primary_confidence", entry.get("confidence", 0)))

        cat_label = category.replace("_", " ") if category else None
        if cat_label and entry.get("category_counts", {}).get(category, 0) >= 2:
            n = entry["category_counts"][category]
            text = (
                f"Using {_fmt_payment(method)} because you used it in "
                f"your last {n} {cat_label} claims."
            )
        elif count >= 3:
            text = (
                f"Using {_fmt_payment(method)} because it appears in "
                f"{count} of your recent expenses."
            )
        elif count >= 1:
            text = (
                f"Suggesting {_fmt_payment(method)} based on your recent expense history "
                f"({count} observation{'s' if count != 1 else ''})."
            )
        else:
            return None

        superseded = None
        if store.get("evolved_at"):
            for k, v in candidates.items():
                if k != method and float(v.get("confidence", 0)) < confidence:
                    superseded = k
                    break

        return MemoryExplanation(
            text=text,
            field="payment_method",
            confidence=confidence,
            evidence_count=count,
            category=category,
            superseded=superseded,
        )

    def vendor(self, store: Dict[str, Any]) -> Optional[MemoryExplanation]:
        name = store.get("vendor_name")
        if not name:
            return None
        count = int(store.get("count", 0))
        if count < 2:
            return None
        return MemoryExplanation(
            text=f"Using {name} as a frequently used vendor ({count} times).",
            field="vendor_name",
            confidence=float(store.get("confidence", 0.5)),
            evidence_count=count,
        )

    def append_to_prompt(self, prompt: str, explanation: Optional[MemoryExplanation]) -> str:
        if not explanation:
            return prompt
        return f"{prompt}\n\n({explanation.format_user_facing()})"
