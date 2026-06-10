"""Post-process assistant responses before delivery."""
import re
from typing import Any, Dict, List, Optional, Set

from app.ai.schemas.tool_result import ToolResult

# IDs mentioned without backing in tool results
_ID_PATTERN = re.compile(
    r"\b(?:expense|claim|approval|reimbursement)\s*#?\s*(\d+)\b",
    re.IGNORECASE,
)
_CURRENCY_PATTERN = re.compile(
    r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d{1,2})?)|\b(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(?:₹|rupees?|rs)\b",
    re.IGNORECASE,
)
_HALLUCINATED_TOOL_PATTERN = re.compile(
    r"\b(?:I (?:have |'ve )?)(?:called|invoked|executed|ran)\s+([a-z_.]+\.v\d+)\b",
    re.IGNORECASE,
)


def _format_inr(amount: float) -> str:
    if amount == int(amount):
        return f"₹{int(amount):,}"
    return f"₹{amount:,.2f}"


def _normalize_currency_in_text(text: str) -> str:
    def _repl(m: re.Match) -> str:
        raw = m.group(1) or m.group(2) or ""
        try:
            val = float(raw.replace(",", ""))
            return _format_inr(val)
        except ValueError:
            return m.group(0)

    return _CURRENCY_PATTERN.sub(_repl, text)


def _collect_ground_truth_ids(tool_results: List[ToolResult]) -> Dict[str, Set[int]]:
    buckets: Dict[str, Set[int]] = {
        "expense": set(),
        "claim": set(),
        "approval": set(),
    }
    for r in tool_results:
        data = r.data or {}
        if "expense_id" in data:
            buckets["expense"].add(int(data["expense_id"]))
        if "claim_id" in data:
            buckets["claim"].add(int(data["claim_id"]))
        if "approval_id" in data:
            buckets["approval"].add(int(data["approval_id"]))
        for item in data.get("expenses") or []:
            if isinstance(item, dict) and "expense_id" in item:
                buckets["expense"].add(int(item["expense_id"]))
        for item in data.get("approvals") or []:
            if isinstance(item, dict):
                if "claim_id" in item:
                    buckets["claim"].add(int(item["claim_id"]))
                if "approval_id" in item:
                    buckets["approval"].add(int(item["approval_id"]))
    return buckets


def _strip_ungrounded_ids(text: str, truth: Dict[str, Set[int]]) -> tuple[str, List[str]]:
    warnings: List[str] = []

    def _repl(m: re.Match) -> str:
        kind = m.group(0).split()[0].lower()
        num = int(m.group(1))
        key = "expense" if "expense" in kind else "claim" if "claim" in kind else "approval"
        if key in truth and truth[key] and num not in truth[key]:
            warnings.append(f"removed ungrounded {key} #{num}")
            return f"that {key}"
        return m.group(0)

    return _ID_PATTERN.sub(_repl, text), warnings


def _verify_tool_mentions(text: str, executed_tools: Set[str]) -> tuple[str, List[str]]:
    warnings: List[str] = []
    for m in _HALLUCINATED_TOOL_PATTERN.finditer(text):
        tool = m.group(1)
        if tool not in executed_tools:
            warnings.append(f"unverified tool mention: {tool}")
    return text, warnings


def postprocess_response(
    content: str,
    *,
    tool_results: Optional[List[ToolResult]] = None,
    executed_tool_names: Optional[List[str]] = None,
    policy_hints: Optional[List[str]] = None,
) -> tuple[str, Dict[str, Any]]:
    """
    Sanitize assistant text for production.
    Returns (processed_content, metadata).
    """
    tool_results = tool_results or []
    meta: Dict[str, Any] = {"warnings": [], "repairs": []}

    text = content or ""

    # Currency formatting
    before = text
    text = _normalize_currency_in_text(text)
    if text != before:
        meta["repairs"].append("currency_formatted")

    # Grounded IDs only
    truth = _collect_ground_truth_ids(tool_results)
    text, id_warnings = _strip_ungrounded_ids(text, truth)
    meta["warnings"].extend(id_warnings)

    # Tool reference check
    executed = set(executed_tool_names or [])
    for r in tool_results:
        if r.data and r.data.get("tool_name"):
            executed.add(r.data["tool_name"])
    _, tool_warnings = _verify_tool_mentions(text, executed)
    meta["warnings"].extend(tool_warnings)

    # Policy consistency footnote (light touch)
    if policy_hints:
        for hint in policy_hints:
            if "high_amount" in hint and "policy" not in text.lower():
                meta["warnings"].append("high_amount_without_policy_mention")

    # Remove duplicate whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # Enterprise tone: strip casual emoji / hype
    text = re.sub(r"[\U0001F300-\U0001FAFF]+", "", text)
    text = re.sub(
        r"\b(awesome|totally|super)\b[!]*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s{2,}", " ", text).strip()

    return text, meta
