import copy
import re
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.utils.ocr_categories import classify_bill

# Currency symbol optional; amounts may be 27.5 or 605
AMOUNT = r"(\d+(?:\.\d{1,2})?)"
AMOUNT_COMMA = r"([\d,]+(?:\.\d{1,2})?)"
CURRENCY_PREFIX = r"(?:₹|€|\$|Rs\.?|`)?\s*"

# Statement-level totals (higher priority than line-item "Total" lines)
_PAYABLE_TOTAL_PATTERNS: List[Tuple[str, int]] = [
    (r"Total\s+Amount\s+Payable\s*:?\s*" + CURRENCY_PREFIX + AMOUNT_COMMA, 100),
    (r"This\s+month'?s?\s+charges\s*" + CURRENCY_PREFIX + AMOUNT_COMMA, 95),
    (
        r"(?<!Sub[-\s])Grand\s+Total\s*(?:\([^)]*\))?\s*:?\s*"
        + CURRENCY_PREFIX
        + AMOUNT_COMMA,
        85,
    ),
    # OCR splits label and amount across lines (e.g. "Total:\nMode: Cash\n3150")
    (
        r"(?<!Sub[-\s])Total\s*:?\s*\n(?:(?!Sub[-\s]*Total)[^\n]*\n){0,8}?"
        + CURRENCY_PREFIX
        + AMOUNT_COMMA,
        92,
    ),
    (
        r"(?:Net\s+Payable|Paid\s+Amount|Amount\s+Paid)\s*:?\s*\n?"
        + CURRENCY_PREFIX
        + AMOUNT_COMMA,
        88,
    ),
    (r"^\s*TOTAL\s*" + CURRENCY_PREFIX + AMOUNT_COMMA, 80),
    (
        r"(?<!Sub[-\s])Total\s+Amount\s*:?\s*" + CURRENCY_PREFIX + AMOUNT_COMMA,
        70,
    ),
    (
        rf"(?<!Sub[-\s])Total\s*:?\s*{CURRENCY_PREFIX}{AMOUNT_COMMA}",
        50,
    ),
]

# Sub-total label often on its own line before the amount
_SUBTOTAL_PATTERNS: List[str] = [
    r"Sub[-\s]*Total\s*:?\s*" + CURRENCY_PREFIX + AMOUNT_COMMA,
    r"Sub[-\s]*Total\s*:?\s*\n\s*" + CURRENCY_PREFIX + AMOUNT_COMMA,
]

_ITEM_SECTION_STOP = re.compile(
    r"^(item|price|qty|quantity|total|sub[-\s]*total|cgst|sgst|igst|cast|"
    r"mode|payment|time|receipt|gst|vat|tax|save\s+paper|net\s+payable|discount)",
    re.IGNORECASE,
)

_TABLE_HEADER_WORDS = frozenset(
    {"item", "price", "qty", "quantity", "total", "amount", "rate", "sno", "sr", "no"}
)

_TELECOM_VENDOR_PATTERNS: List[Tuple[str, str]] = [
    (r"bharti\s+airtel|one\s+airtel|airtel\.in|airtel\s+thanks|\.mairtel", "Bharti Airtel"),
    (r"reliance\s+jio|\bjio\b|jio\.com", "Jio"),
    (r"vodafone\s+idea|\bvi\s+postpaid|\bvi\s+prepaid", "Vi"),
    (r"\bbsnl\b|bharat\s+sanchar", "BSNL"),
    (r"act\s+fibernet|spectra\s", "ACT Fibernet"),
]


class OCRProcessor:
    def __init__(self):
        pass

    def _normalize_ocr_text(self, text: str) -> str:
        """Fix common OCR quirks before parsing (blur, thermal print, phone photos)."""
        text = (
            text.replace("\u2018", "'")
            .replace("\u2019", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("|", "1")
            .replace("lNC", "INC")
            .replace("lnvoice", "Invoice")
            .replace("lnv0ice", "Invoice")
            .replace("Tota1", "Total")
            .replace("T0tal", "Total")
            .replace("Sub-Tota1", "Sub-Total")
            .replace("Sub Tota1", "Sub Total")
            .replace("CG5T", "CGST")
            .replace("CGST", "CGST")
            .replace("5GST", "SGST")
            .replace("SG5T", "SGST")
            .replace("Ca5h", "Cash")
            .replace("casn", "cash")
            .replace("CASH", "Cash")
            .replace("Pa1ace", "Palace")
            .replace("Palace", "Palace")
            .replace("Tab1e", "Table")
            .replace("Chi11y", "Chilly")
            .replace("₹", "₹")
            .replace("Rs.", "₹")
            .replace("RS.", "₹")
            .replace("INR", "₹")
        )
        text = re.sub(r"(?i)sub[\s\-]*tota[l1I]", "Sub-Total", text)
        text = re.sub(r"(?i)grand[\s\-]*tota[l1I]", "Grand Total", text)
        text = re.sub(r"(?i)tota[l1I]\s*amount", "Total Amount", text)
        text = re.sub(r"(?i)payment\s*mode", "Payment Mode", text)
        text = re.sub(r"(?i)invoice\s*no", "Invoice No", text)
        text = re.sub(r"(?i)\bcgst\b", "CGST", text)
        text = re.sub(r"(?i)\bsgst\b", "SGST", text)
        text = re.sub(r"(?i)\bigst\b", "IGST", text)
        # Blur often reads 0 as O at end of amounts (315O -> 3150).
        text = re.sub(r"(?<=\d)[Oo](?=\s|$)", "0", text)
        # Same-line label + amount only (never span lines — that pairs Total with tax lines).
        text = re.sub(
            r"(?im)^(sub[-\s]*total|grand\s+total|(?<!sub[-\s])total|cgst|sgst|igst)\s*:?\s+"
            r"([\d,Oo]+(?:\.\d{1,2})?)(?!%)",
            lambda m: f"{m.group(1)} ₹ {m.group(2).replace('O', '0').replace('o', '0')}",
            text,
        )
        # Sub-total / grand total when the amount is on the next line.
        text = re.sub(
            r"(?im)^(sub[-\s]*total|grand\s+total)\s*:?\s*\n\s*"
            r"([\d,Oo]{2,}(?:\.\d{1,2})?)\s*$",
            lambda m: f"{m.group(1)} ₹ {m.group(2).replace('O', '0').replace('o', '0')}",
            text,
        )
        # Standalone footer amounts on their own line.
        text = re.sub(
            r"(?m)^\s*([\d,Oo]{2,}(?:\.\d{1,2})?)\s*$",
            lambda m: m.group(1).replace("O", "0").replace("o", "0"),
            text,
        )
        return text

    @staticmethod
    def _looks_like_gst_rate_not_amount(amount: float, line: str) -> bool:
        """Reject 2.5 / 5 / 12 / 18 / 28 when OCR captured GST % instead of rupees."""
        if "%" in line:
            return amount <= 30.0
        common_rates = (0.0, 0.25, 2.5, 5.0, 6.0, 9.0, 12.0, 14.0, 18.0, 28.0)
        if any(abs(amount - r) < 0.06 for r in common_rates):
            return True
        return False

    def _normalize_tax_amount(
        self, amount: float, line: str, subtotal: Optional[float]
    ) -> float:
        """Correct missing decimal (e.g. 275 -> 27.5 when rate is 5% of 550)."""
        rate_m = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
        rate = float(rate_m.group(1)) if rate_m else None

        if subtotal and rate:
            expected = round(subtotal * rate / 100, 2)
            if expected > 0:
                for divisor in (10, 100):
                    scaled = round(amount / divisor, 2)
                    if abs(scaled - expected) <= max(1.5, expected * 0.2):
                        return scaled
                if abs(amount - expected) <= max(1.5, expected * 0.2):
                    return amount
                if amount > expected * 2:
                    return expected

        if subtotal and amount > subtotal * 0.12:
            for divisor in (10, 100):
                scaled = round(amount / divisor, 2)
                if scaled < subtotal * 0.12:
                    return scaled
        return amount

    def _score_parsed_bill(self, parsed: Dict[str, Any]) -> float:
        """Prefer parses with consistent monetary fields over raw OCR confidence."""
        score = float(parsed.get("confidence_score") or 0)
        tot = parsed.get("total_amount")
        sub = parsed.get("subtotal")
        tax = parsed.get("tax_amount")
        items = parsed.get("items_list") or []

        if tot and tot > 1:
            score += 25
        if sub and sub > 1:
            score += 10
        if tax and tax > 0:
            score += 8
        if items:
            score += min(15, len(items) * 3)
        if sub and tot and tax and abs((sub + tax) - tot) <= max(2.0, 0.02 * tot):
            score += 12
        if tot and tot <= 1.5 and (sub or 0) > 50:
            score -= 30
        if sub and tot and tot < sub * 0.98:
            score -= 40
        if sub and tot and tot > sub * 1.6:
            score -= 15
        return score

    def _pick_best_financial_candidate(
        self, candidates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Use one OCR pass for money fields — avoids mixing totals across variants."""
        ranked = sorted(
            candidates,
            key=lambda p: self._score_parsed_bill(p),
            reverse=True,
        )
        for cand in ranked:
            sub = cand.get("subtotal")
            tot = cand.get("total_amount")
            if sub and tot and float(tot) >= float(sub) * 0.98:
                tax = cand.get("tax_amount")
                if tax is None or abs(float(sub) + float(tax) - float(tot)) <= max(
                    2.0, 0.04 * float(tot)
                ):
                    return cand
        return ranked[0]

    def _field_score(self, field: str, value: Any) -> float:
        if value is None or value == [] or value == {}:
            return -1.0
        if field in ("total_amount", "subtotal", "tax_amount"):
            try:
                num = float(value)
            except (TypeError, ValueError):
                return -1.0
            if num <= 0:
                return -1.0
            if num <= 1.5:
                return 1.0
            return 10.0 + min(num / 1000.0, 20.0)
        if field == "items_list":
            items = value if isinstance(value, list) else []
            return len(items) * 4.0
        if field in ("vendor_name", "restaurant_name", "bill_number"):
            text = str(value).strip()
            return len(text) / 4.0 if text else -1.0
        if field == "bill_date":
            return 8.0
        if field == "payment_method":
            return 5.0
        return 1.0

    def _merge_parsed_candidates(
        self, candidates: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Pick the strongest value per field across blurry/multi-pass OCR."""
        if not candidates:
            return None

        ranked = sorted(
            candidates,
            key=lambda p: self._score_parsed_bill(p),
            reverse=True,
        )
        financial = self._pick_best_financial_candidate(ranked)
        merged = copy.deepcopy(financial)

        scalar_fields = (
            "vendor_name",
            "restaurant_name",
            "bill_number",
            "bill_date",
            "payment_method",
            "customer_name",
            "table_number",
            "vendor_gst",
        )
        for field in scalar_fields:
            best_val = merged.get(field)
            best_fs = self._field_score(field, best_val)
            for cand in ranked[1:]:
                val = cand.get(field)
                fs = self._field_score(field, val)
                if fs > best_fs:
                    best_val = val
                    best_fs = fs
            if best_val is not None:
                merged[field] = best_val

        items_by_name: Dict[str, dict] = {}
        for cand in ranked:
            for item in cand.get("items_list") or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip().lower()
                if not name:
                    continue
                prev = items_by_name.get(name)
                if prev is None or float(item.get("price") or 0) > float(
                    prev.get("price") or 0
                ):
                    items_by_name[name] = item
        if items_by_name:
            merged["items_list"] = list(items_by_name.values())

        if not merged.get("tax_breakdown") and financial.get("tax_breakdown"):
            merged["tax_breakdown"] = financial.get("tax_breakdown")

        self._reconcile_financial_fields(merged)
        return merged

    def process_image_sync(self, image_path: str) -> Dict[str, Any]:
        from app.services.paddle_ocr_engine import (
            extract_text_from_image,
            extract_text_variants_from_image,
            measure_image_quality,
            merge_variant_texts,
        )

        from app.services.paddle_ocr_engine import iter_ocr_text_passes

        image_quality = measure_image_quality(image_path)
        variant_texts: List[Tuple[str, float]] = []
        parsed_candidates: List[Dict[str, Any]] = []
        best_raw = ""
        best_engine_conf = 0.0
        best_score = -1.0
        early_exit_score = 78.0

        for raw, engine_conf in iter_ocr_text_passes(image_path):
            if not raw.strip():
                continue
            variant_texts.append((raw, engine_conf))
            parsed = self._parse_bill_text(raw)
            parsed_candidates.append(parsed)
            score = self._score_parsed_bill(parsed)
            if score > best_score:
                best_score = score
                best_raw = raw
                best_engine_conf = engine_conf
            tot = parsed.get("total_amount")
            if score >= early_exit_score and tot is not None and float(tot) > 10.0:
                break

        if not variant_texts:
            raw, engine_conf = extract_text_from_image(image_path)
            if not raw.strip():
                return {
                    "raw_text": "",
                    "confidence_score": 0.0,
                    "ocr_engine_confidence": engine_conf,
                }
            variant_texts = [(raw, engine_conf)]
            parsed = self._parse_bill_text(raw)
            parsed_candidates.append(parsed)
            best_raw = raw
            best_engine_conf = engine_conf

        merged_raw = merge_variant_texts([t for t, _ in variant_texts])
        if merged_raw.strip():
            merged_parsed = self._parse_bill_text(merged_raw)
            parsed_candidates.append(merged_parsed)
            merged_score = self._score_parsed_bill(merged_parsed)
            if merged_score >= best_score:
                best_raw = merged_raw
                best_engine_conf = max(best_engine_conf, 0.5)

        if len(parsed_candidates) == 1:
            best_parsed = parsed_candidates[0]
        else:
            best_parsed = self._merge_parsed_candidates(parsed_candidates)
        if best_parsed is None:
            return {"raw_text": "", "confidence_score": 0.0, "ocr_engine_confidence": 0.0}

        best_parsed["raw_text"] = best_raw or merged_raw
        best_parsed["ocr_engine_confidence"] = best_engine_conf
        best_parsed["image_blurry"] = image_quality.get("blurry")
        best_parsed["laplacian_variance"] = image_quality.get("laplacian_variance")
        return best_parsed

    @staticmethod
    def _parse_money(value: str) -> float:
        return float(value.replace(",", "").replace("`", "").strip())

    @staticmethod
    def _split_lines(text: str) -> List[str]:
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    def _is_table_column_header_total(
        self, lines: List[str], total_idx: int
    ) -> bool:
        """Skip item-table headers like 'Price / Qty / Total / Item' mistaken as bill total."""
        line = lines[total_idx].strip().lower()
        if line not in ("total", "total:"):
            return False
        window: List[str] = []
        for j in range(max(0, total_idx - 3), min(len(lines), total_idx + 4)):
            if j == total_idx:
                continue
            window.append(lines[j].strip().lower())
        header_hits = sum(1 for w in window if w in _TABLE_HEADER_WORDS)
        if header_hits >= 2:
            return True
        if total_idx + 1 < len(lines):
            nxt = lines[total_idx + 1].strip().lower()
            if nxt in _TABLE_HEADER_WORDS:
                return True
        return False

    def _amount_from_following_lines(
        self,
        lines: List[str],
        start_idx: int,
        *,
        max_lookahead: int = 4,
        min_amount: float = 1.0,
    ) -> Optional[float]:
        """Amount on the same line as a label or on the next few lines (common OCR split)."""
        for j in range(start_idx, min(start_idx + max_lookahead + 1, len(lines))):
            stripped = lines[j]
            if j > start_idx and _ITEM_SECTION_STOP.match(stripped):
                if not re.match(r"^Mode\s*:", stripped, re.IGNORECASE):
                    break
            amt = self._amount_from_line(stripped)
            if amt is not None and amt >= min_amount:
                if j == start_idx and not re.search(r"\d", stripped):
                    continue
                return amt
        return None

    def _parse_subtotal(self, text: str) -> Optional[float]:
        for pattern in _SUBTOTAL_PATTERNS:
            m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if m:
                try:
                    return self._parse_money(m.group(1))
                except ValueError:
                    continue
        lines = self._split_lines(text)
        for idx, line in enumerate(lines):
            if re.match(r"Sub[-\s]*Total", line, re.IGNORECASE):
                amt = self._amount_from_line(line)
                if amt is None:
                    amt = self._amount_from_following_lines(lines, idx, max_lookahead=2)
                if amt is not None:
                    return amt
        return None

    def _parse_footer_grand_total(
        self,
        text: str,
        subtotal: Optional[float] = None,
        *,
        exclude_values: Optional[set[float]] = None,
    ) -> Optional[float]:
        """Standalone amount before Time:/footer — e.g. 3150 on its own line after Mode: Cash."""
        lines = self._split_lines(text)
        cutoff = len(lines)
        for i, ln in enumerate(lines):
            if re.match(r"Time\s*:", ln, re.IGNORECASE) or "save paper" in ln.lower():
                cutoff = i
                break

        excluded = exclude_values or set()
        candidates: List[float] = []
        for ln in lines[:cutoff]:
            cleaned = ln.replace(",", "").strip()
            if not re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned):
                continue
            val = float(cleaned)
            if val in excluded:
                continue
            # Skip invoice/table identifiers (e.g. 7767, 37) mistaken as totals.
            if val >= 1000 and subtotal and subtotal > 0 and val > subtotal * 4:
                if not any(tok in ln.lower() for tok in ("total", "amount", "payable", "grand")):
                    continue
            if val >= 10:
                candidates.append(val)

        if not candidates:
            return None
        if subtotal is not None and subtotal > 0:
            with_tax = [c for c in candidates if c >= subtotal * 0.98]
            if with_tax:
                return max(with_tax)
        return max(candidates)

    def _parse_labelled_total(self, text: str) -> Optional[float]:
        """Total when label and amount are on separate lines."""
        lines = self._split_lines(text)
        candidates: List[float] = []
        for idx, line in enumerate(lines):
            if not re.match(r"(?<!Sub[-\s])Total\s*:?\s*$", line, re.IGNORECASE):
                continue
            if self._is_table_column_header_total(lines, idx):
                continue
            amt = self._amount_from_following_lines(
                lines, idx, max_lookahead=6, min_amount=10.0
            )
            if amt is not None:
                candidates.append(amt)
        if not candidates:
            return None
        return max(candidates)

    def _extract_pdf_text_pdftotext(self, pdf_path: str) -> str:
        """All pages via poppler pdftotext (layout preserved)."""
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", pdf_path, "-"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return ""

    def _extract_pdf_text_pypdf(self, pdf_path: str) -> Tuple[str, int]:
        """All pages via pypdf (fallback when pdftotext/poppler unavailable)."""
        try:
            from pypdf import PdfReader

            reader = PdfReader(pdf_path)
            parts: List[str] = []
            for i, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    parts.append(f"\n--- PDF page {i} ---\n{page_text}")
            return "\n".join(parts), len(reader.pages)
        except Exception:
            return "", 0

    def _extract_pdf_text(self, pdf_path: str) -> Tuple[str, int]:
        """Embedded text from every PDF page (pdftotext, then pypdf)."""
        text = self._extract_pdf_text_pdftotext(pdf_path)
        if len(text.strip()) > 80:
            page_count = max(1, len(re.findall(r"\f", text)) + 1)
            return text, page_count

        text, page_count = self._extract_pdf_text_pypdf(pdf_path)
        return text, page_count

    def _process_pdf_via_ocr_images(self, pdf_path: str) -> Dict[str, Any]:
        """OCR every page as an image when embedded text is missing."""
        import os

        import pdf2image

        try:
            images = pdf2image.convert_from_path(pdf_path, dpi=300)
        except Exception:
            return {"raw_text": "", "confidence_score": 0.0, "pdf_page_count": 0}

        if not images:
            return {"raw_text": "", "confidence_score": 0.0, "pdf_page_count": 0}

        page_texts: List[str] = []
        base = pdf_path.rsplit(".", 1)[0]
        for i, image in enumerate(images, start=1):
            temp_image_path = f"{base}_page{i}.jpg"
            image.save(temp_image_path, "JPEG")
            try:
                page_result = self.process_image_sync(temp_image_path)
                raw = (page_result.get("raw_text") or "").strip()
                if raw:
                    page_texts.append(f"\n--- OCR page {i} ---\n{raw}")
            finally:
                if os.path.exists(temp_image_path):
                    os.remove(temp_image_path)

        combined = "\n".join(page_texts)
        if len(combined.strip()) <= 80:
            return {"raw_text": combined, "confidence_score": 0.0, "pdf_page_count": len(images)}

        extracted = self._parse_bill_text(combined)
        extracted["raw_text"] = combined
        extracted["pdf_page_count"] = len(images)
        return extracted

    def process_pdf_sync(self, pdf_path: str) -> Dict[str, Any]:
        text, page_count = self._extract_pdf_text(pdf_path)
        if len(text.strip()) > 80:
            extracted = self._parse_bill_text(text)
            extracted["raw_text"] = text
            extracted["pdf_page_count"] = page_count
            return extracted

        return self._process_pdf_via_ocr_images(pdf_path)

    async def process_image(self, image_path: str) -> Dict[str, Any]:
        return self.process_image_sync(image_path)

    async def process_pdf(self, pdf_path: str) -> Dict[str, Any]:
        return self.process_pdf_sync(pdf_path)

    def _parse_total_amount(self, text: str, subtotal: Optional[float] = None) -> Optional[float]:
        """Prefer statement-level payable totals over incidental line totals."""
        best_amount: Optional[float] = None
        best_priority = -1

        for pattern, priority in _PAYABLE_TOTAL_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                try:
                    amount = self._parse_money(match.group(1))
                except ValueError:
                    continue
                if amount <= 0:
                    continue
                if subtotal and subtotal > 0 and amount < subtotal * 0.98:
                    continue
                if priority > best_priority or (
                    priority == best_priority
                    and (best_amount is None or amount > best_amount)
                ):
                    best_amount = amount
                    best_priority = priority

        if best_amount is None:
            best_amount = self._parse_labelled_total(text)

        if best_amount is None:
            exclude: set[float] = set()
            inv = re.search(
                r"(?:I|1|i)?nvoice\s*(?:No|Na)[.:]?\s*#?\s*(\d+)",
                text,
                re.IGNORECASE,
            )
            if inv:
                try:
                    exclude.add(float(inv.group(1)))
                except ValueError:
                    pass
            table = re.search(r"Table[:\s]*#?\s*(\d+)", text, re.IGNORECASE)
            if table:
                try:
                    exclude.add(float(table.group(1)))
                except ValueError:
                    pass
            best_amount = self._parse_footer_grand_total(
                text, subtotal=subtotal, exclude_values=exclude
            )

        return best_amount

    def _parse_telecom_vendor(self, text: str) -> Optional[str]:
        lower = text.lower()
        for pattern, name in _TELECOM_VENDOR_PATTERNS:
            if re.search(pattern, lower):
                return name
        return None

    def _amount_from_line(self, line: str) -> Optional[float]:
        """Last monetary amount on a line (prefers decimals like 27.5)."""
        glued = re.search(
            r"(\d+(?:\.\d+)?)\s*%\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)%(\d+(?:\.\d+)?)",
            line.replace(",", ""),
        )
        if glued:
            for g in (glued.group(2), glued.group(4)):
                if g:
                    return float(g)

        matches = re.findall(r"\d+\.\d{1,2}|\d+", line.replace(",", ""))
        if not matches:
            return None
        for m in reversed(matches):
            if "." in m:
                return float(m)
        return float(matches[-1])

    def _parse_payment_method(self, text: str) -> Optional[str]:
        """Detect Cash, UPI, Card, etc."""
        known = {
            "cash": "cash",
            "upi": "upi",
            "card": "credit_card",
            "credit": "credit_card",
            "debit": "debit_card",
            "net banking": "net_banking",
            "wallet": "wallet",
            "paytm": "wallet",
            "gpay": "upi",
            "phonepe": "upi",
        }
        patterns = [
            r"Mode\s*of\s*Payment[:\s]*([A-Za-z][A-Za-z\s]*)",
            r"Mode\s*of\s*Payment[:\s]*([A-Za-z]+)",
            r"Mode[:\s]*([A-Za-z]+)",
            r"Payment\s+Mode[:\s]*([A-Za-z]+)",
            r"Paid\s*(?:via|by)?[:\s]*([A-Za-z]+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                val = m.group(1).strip().lower()
                if len(val) < 3:
                    continue
                for key, normalized in known.items():
                    if key in val or val == key:
                        return normalized
                return val

        pay_block = re.search(
            r"Payments\s*\n\s*(Cash|UPI|Card|Wallet|Paytm|GPay|PhonePe)",
            text,
            re.IGNORECASE,
        )
        if pay_block:
            val = pay_block.group(1).lower()
            return known.get(val, val)

        for line in text.splitlines():
            lower = line.lower()
            if "mode" in lower or "payment" in lower:
                for key, normalized in known.items():
                    if re.search(rf"\b{key}\b", lower):
                        return normalized
            if re.search(r"\bcash\b", lower) and (
                "mode" in lower or "payment" in lower or "total" in lower
            ):
                return "cash"
        return None

    def _parse_gst_tax(
        self,
        text: str,
        subtotal: Optional[float] = None,
        grand_total: Optional[float] = None,
    ) -> Tuple[Optional[float], Dict[str, float]]:
        """
        Parse CGST / SGST per line (not item rows). Handles OCR misreads like
        'cast' for CGST and 275 instead of 27.5.
        """
        breakdown: Dict[str, float] = {}
        gst_line = re.compile(
            r"(?i)\b(cgst|sgst|igst|cast)\b(?:\s*\([^)]*\))?",
        )

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or "GST NO" in stripped.upper():
                continue
            m = gst_line.search(stripped)
            if not m:
                continue
            key = m.group(1).lower()
            if key == "cast":
                key = "cgst"
            amt = self._amount_from_line(stripped)
            if amt is None:
                continue
            if amt >= 5000:
                continue
            if self._looks_like_gst_rate_not_amount(amt, stripped):
                continue
            amt = self._normalize_tax_amount(amt, stripped, subtotal)
            breakdown[key] = amt

        if len(breakdown) < 2:
            lines = self._split_lines(text)
            for idx, line in enumerate(lines):
                if not re.match(r"(?i)(cgst|sgst|igst|cast)\b", line):
                    continue
                key = re.match(r"(?i)(cgst|sgst|igst|cast)\b", line).group(1).lower()
                if key == "cast":
                    key = "cgst"
                if key in breakdown:
                    continue
                amt = self._amount_from_line(line)
                if amt is None and idx + 1 < len(lines):
                    nxt = lines[idx + 1].strip()
                    if re.fullmatch(r"\d+(?:\.\d+)?", nxt.replace(",", "")):
                        amt = float(nxt.replace(",", ""))
                if amt is not None and amt < 5000:
                    if self._looks_like_gst_rate_not_amount(amt, line):
                        if idx + 1 < len(lines):
                            nxt = lines[idx + 1].strip()
                            if re.fullmatch(r"\d+(?:\.\d{1,2})?", nxt.replace(",", "")):
                                amt = float(nxt.replace(",", ""))
                    if self._looks_like_gst_rate_not_amount(amt, line):
                        continue
                    amt = self._normalize_tax_amount(amt, line, subtotal)
                    breakdown[key] = amt

        if breakdown:
            total = round(sum(breakdown.values()), 2)
            return total, breakdown

        # Single-line tax: "Tax: ₹55", "VAT 18% 120", "Service Tax 50"
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or "GST NO" in stripped.upper():
                continue
            if re.match(
                r"(?i)^(VAT|Tax|Service\s*Tax|GST\s*Amount)\b",
                stripped,
            ) and not re.search(r"(?i)cgst|sgst|igst", stripped):
                amt = self._amount_from_line(stripped)
                if amt is not None and amt < 50000 and (not subtotal or amt < subtotal * 0.5):
                    return amt, {"tax": amt}

        if subtotal and grand_total:
            implied = round(grand_total - subtotal, 2)
            cap = min(100000.0, (grand_total or 0) * 0.45)
            if 0 < implied < cap:
                half = round(implied / 2, 2)
                return implied, {"cgst": half, "sgst": implied - half}

        return None, breakdown

    def _parse_line_items(self, text: str) -> List[dict]:
        items: List[dict] = self._parse_single_line_items(text)
        if items:
            return items
        return self._parse_multiline_line_items(text)

    def _parse_single_line_items(self, text: str) -> List[dict]:
        items: List[dict] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.upper().startswith(
                ("ITEM", "CGST", "SGST", "SUB", "CAST", "MODE")
            ):
                continue
            m = re.match(
                r"^([A-Za-z][A-Za-z\s']+?)\s+"
                r"(?:€|₹|\$)?\s*(\d+(?:\.\d+)?)\s+"
                r"(\d+)\s+"
                r"(?:€|₹|\$)?\s*(\d+(?:\.\d+)?)\s*$",
                stripped,
                re.IGNORECASE,
            )
            if m:
                name = m.group(1).strip()
                if any(x in name.lower() for x in ("total", "gst", "mode", "payment")):
                    continue
                items.append(
                    {
                        "name": name,
                        "unit_price": float(m.group(2)),
                        "quantity": int(m.group(3)),
                        "price": float(m.group(4)),
                    }
                )
        return items

    def _parse_multiline_line_items(self, text: str) -> List[dict]:
        """Restaurant receipts: name / unit price / qty / line total on consecutive lines."""
        lines = self._split_lines(text)
        items: List[dict] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if _ITEM_SECTION_STOP.match(line) or not re.match(r"^[A-Za-z]", line):
                i += 1
                continue
            if i + 3 >= len(lines):
                break
            try:
                a = float(lines[i + 1].replace(",", ""))
                b = float(lines[i + 2].replace(",", ""))
                c = float(lines[i + 3].replace(",", ""))
            except ValueError:
                i += 1
                continue
            price, qty, total = a, int(b), c
            if abs(price * qty - total) > max(2.0, 0.05 * total):
                price, qty, total = a, int(c), b
            if not (0 < price < 100_000 and 0 < qty < 1000 and total > 0):
                i += 1
                continue
            if abs(price * qty - total) > max(2.0, 0.05 * total):
                i += 1
                continue
            name = line.strip()
            if any(x in name.lower() for x in ("total", "gst", "mode", "payment", "invoice")):
                i += 1
                continue
            items.append(
                {
                    "name": name,
                    "unit_price": price,
                    "quantity": qty,
                    "price": total,
                }
            )
            i += 4
        return items

    def _reconcile_financial_fields(self, extracted: Dict[str, Any]) -> None:
        """
        Cross-check subtotal, tax, line items, and grand total so amounts stay consistent
        when OCR misreads one field.
        """
        sub = extracted.get("subtotal")
        tot = extracted.get("total_amount")
        tax = extracted.get("tax_amount")
        bd = extracted.get("tax_breakdown") or {}
        items = extracted.get("items_list") or []

        def tol(a: float, b: float) -> bool:
            return abs(a - b) <= max(1.0, 0.015 * max(abs(a), abs(b), 1.0))

        items_sum = round(sum(float(i.get("price") or 0) for i in items), 2) if items else None
        labelled_sub = extracted.get("_labelled_subtotal") is True
        labelled_tot = extracted.get("_labelled_total") is True

        if items_sum and items_sum > 0:
            use_items = sub is None
            if sub is not None and tot and sub > tot * 1.05:
                use_items = True
            if labelled_sub and sub is not None and items_sum < sub * 0.85:
                use_items = False
            if use_items:
                extracted["subtotal"] = items_sum
                sub = items_sum

        max_tax = min(500000.0, (tot or sub or 1) * 0.5) if (tot or sub) else 500000.0

        if sub is not None and tot is not None:
            implied = round(tot - sub, 2)
            if 0 < implied < max_tax:
                if tax is None or abs((tax or 0) - implied) > max(2.0, 0.05 * implied):
                    extracted["tax_amount"] = implied
                    if not bd or abs(sum(bd.values()) - implied) > max(2.0, 0.05 * implied):
                        half = round(implied / 2, 2)
                        extracted["tax_breakdown"] = {
                            "cgst": half,
                            "sgst": round(implied - half, 2),
                        }
                    tax = extracted.get("tax_amount")
                    bd = extracted.get("tax_breakdown") or {}

        if tot is None and sub is not None and tax is not None and 0 < tax < sub * 2:
            extracted["total_amount"] = round(sub + tax, 2)
            tot = extracted["total_amount"]

        if bd and tax is not None and "tax" not in bd:
            summed = round(sum(bd.values()), 2)
            if abs(summed - tax) > 0.05 and tol(summed, tax):
                extracted["tax_amount"] = summed

        if sub is not None and tot is not None and tax is not None:
            if not tol(sub + tax, tot) and 0 < tot - sub < max_tax:
                extracted["tax_amount"] = round(tot - sub, 2)
                half = round((tot - sub) / 2, 2)
                extracted["tax_breakdown"] = {
                    "cgst": half,
                    "sgst": round((tot - sub) - half, 2),
                }

        # Fix OCR picking ₹1 / invoice numbers when line items imply a much larger bill.
        tot = extracted.get("total_amount")
        sub = extracted.get("subtotal")
        tax = extracted.get("tax_amount")
        items_sum = (
            round(sum(float(i.get("price") or 0) for i in items), 2) if items else None
        )
        if items_sum and items_sum > 50:
            if tot is None or tot <= 1.5 or tot < items_sum * 0.5:
                if not labelled_sub:
                    extracted["subtotal"] = items_sum
                if tax and tax > 0:
                    if not labelled_tot:
                        extracted["total_amount"] = round(items_sum + tax, 2)
                elif tot and tot > items_sum * 0.9:
                    if not labelled_tot:
                        extracted["total_amount"] = tot
                elif sub and tax and not labelled_tot:
                    extracted["total_amount"] = round(float(sub) + float(tax), 2)
            elif (
                sub is not None
                and sub < items_sum * 0.5
                and not labelled_sub
            ):
                extracted["subtotal"] = items_sum

        extracted.pop("_labelled_subtotal", None)
        extracted.pop("_labelled_total", None)

    _HEADER_VENDOR_STOP = re.compile(
        r"\b("
        r"shop\s*\d|behind\b|opposite\b|"
        r"\b(?:rd|road|street|st|farm|lane|ave|avenue|blvd)\b|"
        r"maan\s+rd|maharashtra|pune|penfield|"
        r"support@|www\.|http|\.com\b|\.net\b|"
        r"delicious|every\s+bite|thank\s+you|"
        r"\b\d{5,6}\b|"
        r"invoice\s*(?:no|na)|date\s*:|time\s*:|table\s*#|name\s*:|"
        r"sub[-\s]*total|total\s+amount|payment\s+mode|mode\s*:|"
        r"net\s+payable|paid\s+amount|vat\b|discounts?|"
        r"cgst|sgst|item\s+price|qty|quantity|save\s+paper|"
        r"price\s+qty|amount\s+payable|unit\s+price"
        r")\b",
        re.IGNORECASE,
    )

    _TAGLINE_LINE = re.compile(
        r"\b(delicious|every\s+bite|bon\s+appetit|enjoy\s+your|savor|"
        r"thank\s+you\s+for|welcome\s+to|we\s+serve|fresh\s+and)\b",
        re.IGNORECASE,
    )

    def _looks_like_vendor_line(self, line: str) -> bool:
        """Single-line business name at top of food/retail receipts."""
        if len(line) < 3 or len(line) > 55:
            return False
        if self._TAGLINE_LINE.search(line):
            return False
        if re.search(
            r"[₹$€`@]|invoice|receipt|bill\s*no|date\s*:|table|name\s*:|"
            r"gst|sub[-\s]*total|total\s+amount|mode\s*:|qty|price|item\b|payable|"
            r"unit\s+price|vat\b|discount|net\s+payable|paid\s+amount",
            line,
            re.IGNORECASE,
        ):
            return False
        if re.search(r"\d{4,}", line):
            return False
        if not re.match(r"^[A-Za-z][A-Za-z0-9\s&'.-]*$", line):
            return False
        if len(line.split()) > 5:
            return False
        if re.search(
            r"\b(palace|hotel|restaurant|cafe|kitchen|dhaba|biryani|biriyani)\b",
            line,
            re.IGNORECASE,
        ):
            return True
        return True

    def _title_case_brand(self, name: str) -> str:
        parts = name.replace("-", " ").split()
        return " ".join(p[:1].upper() + p[1:].lower() if p else "" for p in parts)

    def _parse_vendor_from_branding(self, text: str) -> Optional[str]:
        """Footer, website, or email domain (e.g. Ghiotto / ghiotto.com)."""
        patterns = [
            r"(?:dining\s+in|visit\s+|order\s+from|choose\s+)\s*([A-Za-z][A-Za-z\s&'.-]{2,35})",
            r"thank\s+you\s+for\s+(?:dining\s+in|choosing|visiting)\s+([A-Za-z][A-Za-z\s&'.-]{2,35})",
            r"www\.([a-z0-9][a-z0-9-]{1,30})\.(?:com|net|org|in)\b",
            r"@([a-z0-9][a-z0-9-]{1,30})\.(?:com|net|org|in)\b",
        ]
        skip_domains = frozenset(
            {"gmail", "yahoo", "hotmail", "outlook", "support", "info", "admin", "email"}
        )
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if not m:
                continue
            raw = m.group(1).strip().rstrip(".,;")
            if "." in raw and "www" in pat:
                raw = raw.split(".")[0]
            key = raw.lower().replace(" ", "")
            if key in skip_domains or len(key) < 3:
                continue
            if len(raw.split()) > 3:
                continue
            return self._title_case_brand(raw)
        return None

    def _pick_best_header_vendor(self, candidates: List[str]) -> Optional[str]:
        if not candidates:
            return None
        cleaned = [c.strip() for c in candidates if c and c.strip()]
        if not cleaned:
            return None

        # Brand + venue on consecutive lines (e.g. Bhagini / Sriganda Palace).
        if len(cleaned) >= 2:
            combined = " — ".join(cleaned[:3])
            if len(combined) <= 60:
                return combined

        multi_word = [c for c in cleaned if len(c.split()) >= 2]
        if multi_word:
            return max(multi_word, key=len)

        if len(cleaned) >= 2:
            return max(cleaned, key=len)

        scored: List[Tuple[int, str]] = []
        for name in cleaned:
            words = name.split()
            score = 0
            if len(words) == 2:
                score += 25
            elif len(words) == 1:
                score += 15
            else:
                score += 5
            if len(name) <= 30:
                score += 10
            if name[0].isupper():
                score += 5
            if self._TAGLINE_LINE.search(name):
                score -= 50
            scored.append((score, name))
        scored.sort(key=lambda x: (-x[0], len(x[1])))
        best = scored[0][1]
        return best if scored[0][0] > 0 else None

    def _parse_receipt_header_vendor(self, text: str) -> Optional[str]:
        """
        Merchant on line(s) above address / RECEIPT block (e.g. 'Thali Central').
        """
        lines = [ln.strip() for ln in text.splitlines()]
        collected: List[str] = []

        for line in lines[:14]:
            if not line or re.match(r"^[-_=]{3,}$", line):
                if collected:
                    break
                continue
            if re.fullmatch(r"RECEIPT", line, re.IGNORECASE):
                break
            if self._HEADER_VENDOR_STOP.search(line):
                break
            if self._looks_like_vendor_line(line):
                collected.append(line)
            elif collected:
                break

        if collected:
            return self._pick_best_header_vendor(collected)

        # Standalone brand word near top (e.g. "Ghiotto")
        for line in lines[:6]:
            if self._HEADER_VENDOR_STOP.search(line):
                continue
            m = re.match(r"^([A-Z][a-zA-Z]{2,24})$", line.strip())
            if m and self._looks_like_vendor_line(m.group(1)):
                return m.group(1)

        for i, line in enumerate(lines):
            if not re.fullmatch(r"RECEIPT", line.strip(), re.IGNORECASE):
                continue
            for j in range(i - 1, -1, -1):
                cand = lines[j].strip()
                if not cand or re.match(r"^[-_=]{3,}$", cand):
                    continue
                if self._HEADER_VENDOR_STOP.search(cand):
                    break
                if self._looks_like_vendor_line(cand):
                    return cand
            break

        for pattern in (
            r"^([A-Za-z][A-Za-z\s&'.-]{2,40}\s+(?:Central|Restaurant|Cafe|Café|Dhaba|Kitchen))\s*$",
            r"^([A-Za-z][A-Za-z\s&'.-]{2,35}\s+Thali)\s*$",
        ):
            m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if m and self._looks_like_vendor_line(m.group(1).strip()):
                return m.group(1).strip()

        return self._parse_vendor_from_branding(text)

    def _parse_ride_receipt(self, text: str, extracted: Dict[str, Any]) -> None:
        """Uber / Rapido / Ola ride receipts (email PDF or OCR)."""
        lower = text.lower()
        if not any(x in lower for x in ("uber", "rapido", "ola", "olacabs")):
            return

        if "uber" in lower and "olacabs" not in lower:
            extracted["vendor_name"] = "Uber"
        elif "rapido" in lower:
            extracted["vendor_name"] = "Rapido"
        elif "ola" in lower:
            extracted["vendor_name"] = "Ola"
        else:
            extracted["vendor_name"] = "Uber"

        crn = re.search(r"\bCRN(\d{6,})\b", text, re.IGNORECASE)
        if crn:
            extracted["bill_number"] = f"CRN{crn.group(1)}"

        thanks = re.search(
            r"Thanks for travelling with us,?\s+([A-Za-z][A-Za-z'-]{1,30})",
            text,
            re.IGNORECASE,
        )
        if thanks:
            extracted["customer_name"] = thanks.group(1).strip()

        ride_fare = re.search(
            r"Ride\s+Fare\s+[₹`$€]?\s*([\d,]+\.?\d*)",
            text,
            re.IGNORECASE,
        )
        if ride_fare:
            extracted["subtotal"] = float(ride_fare.group(1).replace(",", ""))

        ola_total = re.search(
            r"Total\s+Bill\s*\(rounded\)\s+[₹`$€]?\s*([\d,]+\.?\d*)",
            text,
            re.IGNORECASE,
        )
        gst_total = re.search(
            r"total of\s*[₹$€]?\s*([\d,]+\.?\d*)",
            text,
            re.IGNORECASE,
        )
        gst_tax = re.search(
            r"GST of\s*[₹$€]?\s*([\d,]+\.?\d*)",
            text,
            re.IGNORECASE,
        )
        ola_tax = re.search(
            r"Includes\s+[₹`$€]?\s*([\d,]+\.?\d*)\s+Taxes",
            text,
            re.IGNORECASE,
        )
        trip_charge = re.search(
            r"Trip\s*charge\s*\n+\s*[₹$€]?\s*([\d,]+\.?\d*)",
            text,
            re.IGNORECASE,
        )
        total_block = re.search(
            r"(?<!Sub[-\s])Total\s*\n+\s*[₹$€]?\s*([\d,]+\.?\d*)",
            text,
            re.IGNORECASE,
        )

        for m in (ola_total, gst_total, trip_charge, total_block):
            if m:
                amt = float(m.group(1).replace(",", ""))
                if amt < 50000:
                    extracted["total_amount"] = amt
                    break

        for tax_m in (ola_tax, gst_tax):
            if tax_m:
                tax = float(tax_m.group(1).replace(",", ""))
                if tax < 5000:
                    extracted["tax_amount"] = tax
                    break

        ride_date = re.search(
            r"(\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4})\s*\n+[\s₹`]*\d",
            text,
            re.IGNORECASE,
        )
        if not ride_date:
            ride_date = re.search(
                r"(\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4})\s*\n+.*?CRN\d{6,}",
                text,
                re.IGNORECASE | re.DOTALL,
            )
        if ride_date:
            raw = ride_date.group(1).strip().replace(",", "")
            for fmt in ("%d %b %Y", "%d %B %Y"):
                try:
                    extracted["bill_date"] = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue

        if not extracted.get("bill_date"):
            for pattern, formats in (
                (
                    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+(\w+\s+\d{1,2},?\s+\d{4})",
                    ["%b %d, %Y", "%B %d, %Y"],
                ),
                (r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})", ["%d %b %Y", "%d %B %Y"]),
            ):
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    raw = m.group(1).strip()
                    for fmt in formats:
                        try:
                            extracted["bill_date"] = datetime.strptime(raw, fmt)
                            break
                        except ValueError:
                            continue
                    if extracted.get("bill_date"):
                        break

        dist = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:km|kilomet(?:er|re)?s?)\b",
            text,
            re.IGNORECASE,
        )
        if dist:
            extracted["ride_distance"] = float(dist.group(1))

        dur = re.search(r"(\d+)\s*(?:min(?:utes?)?)\b", text, re.IGNORECASE)
        if dur:
            extracted["ride_duration"] = int(dur.group(1))

        ride_type = re.search(
            r"(Bike|Auto|Prime|Sedan|SUV|Mini|Share)\s*[-–]\s*([^\n]+)",
            text,
            re.IGNORECASE,
        )
        if ride_type:
            extracted["ride_type"] = f"{ride_type.group(1)} - {ride_type.group(2).strip()}"
        if not extracted.get("ride_type"):
            uber_type = re.search(
                r"Trip details\s*\n+([^\n]+)\s*\n+\s*License Plate",
                text,
                re.IGNORECASE,
            )
            if uber_type:
                extracted["ride_type"] = uber_type.group(1).strip()

        trip_anchor = re.search(
            r"(\d+(?:\.\d+)?)\s*km\s+(\d+)\s*min",
            text,
            re.IGNORECASE,
        )
        if not trip_anchor:
            trip_anchor = re.search(
                r"kilomet(?:er|re)?s?,\s*\d+\s*minutes?",
                text,
                re.IGNORECASE,
            )
        if trip_anchor:
            trip_text = text[trip_anchor.end() :]
            trip_end = re.search(
                r"Rate or tip|Want to review|My trips|Need help|Payment|Paid by|Didn't make",
                trip_text,
                re.IGNORECASE,
            )
            if trip_end:
                trip_text = trip_text[: trip_end.start()]
            def _join_addr(block: str) -> str:
                lines = [
                    ln.strip()
                    for ln in block.splitlines()
                    if ln.strip()
                    and "gmail" not in ln.lower()
                    and not re.match(r"^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$", ln.replace(" ", ""))
                    and not re.match(r"^\d+\.\d+$", ln)
                    and "License Plate" not in ln
                ]
                return ", ".join(lines)[:250]

            ola_stops = list(
                re.finditer(
                    r"(\d{1,2}:\d{2}\s*(?:AM|PM))\s+"
                    r"((?:(?!\d{1,2}:\d{2}\s*(?:AM|PM)|Payment|Paid by).)+)",
                    trip_text,
                    re.IGNORECASE | re.DOTALL,
                )
            )
            valid_stops = [
                s
                for s in ola_stops
                if len(s.group(2).strip()) > 15
                and any(
                    tok in s.group(2)
                    for tok in ("India", "Hyderabad", "Rd", "Road", "Street", "Layout")
                )
            ]
            if len(valid_stops) >= 2:
                extracted["pickup_location"] = _join_addr(valid_stops[0].group(2))
                extracted["dropoff_location"] = _join_addr(valid_stops[1].group(2))
            else:
                time_stops = list(
                    re.finditer(
                        r"\b(\d{1,2}:\d{2}\s*(?:AM|PM)?)\b", trip_text, re.IGNORECASE
                    )
                )
                if len(time_stops) >= 2:
                    pickup_text = trip_text[time_stops[0].end() : time_stops[1].start()]
                    drop_text = trip_text[time_stops[1].end() :]
                    pickup_addr = _join_addr(pickup_text)
                    drop_addr = _join_addr(drop_text)
                    if pickup_addr and "gmail" not in pickup_addr.lower():
                        extracted["pickup_location"] = pickup_addr
                    if drop_addr:
                        extracted["dropoff_location"] = drop_addr

        if not extracted.get("payment_method"):
            if re.search(r"\bCash\b", text, re.IGNORECASE):
                extracted["payment_method"] = "cash"
            elif re.search(r"\bUPI\b", text, re.IGNORECASE):
                extracted["payment_method"] = "upi"

    def _parse_bill_text(self, text: str) -> Dict[str, Any]:
        text = self._normalize_ocr_text(text)
        extracted: Dict[str, Any] = {
            "bill_number": None,
            "bill_date": None,
            "vendor_name": None,
            "vendor_gst": None,
            "total_amount": None,
            "tax_amount": None,
            "tax_breakdown": {},
            "subtotal": None,
            "payment_method": None,
            "restaurant_name": None,
            "items_list": [],
            "customer_name": None,
            "table_number": None,
            "ride_distance": None,
            "ride_duration": None,
            "pickup_location": None,
            "dropoff_location": None,
            "ride_type": None,
            "confidence_score": 0.0,
        }

        self._parse_ride_receipt(text, extracted)

        # Invoice number (tolerate OCR: "nvoice Na: 1208")
        if not extracted.get("bill_number"):
            for pattern in (
                r"\bCRN(\d{6,})\b",
                r"(?:I|1|i)?nvoice\s*(?:No|Na)[.:]?\s*#?\s*(\d+)",
                r"Invoice\s*No[.:]?\s*#?\s*(\d+)",
                r"Bill\s*NO\s*(\w+)",
                r"Bill\s*No[.:]?\s*(\w+)",
            ):
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    num = m.group(1).strip()
                    extracted["bill_number"] = (
                        f"CRN{num}" if pattern.startswith(r"\bCRN") else num
                    )
                    break

        # Customer / table
        cust = re.search(r"Name[:\s]*([A-Za-z][A-Za-z\s]+)", text, re.IGNORECASE)
        if cust:
            extracted["customer_name"] = cust.group(1).strip()
        table = re.search(r"Table[:\s]*#?\s*(\d+)", text, re.IGNORECASE)
        if table:
            extracted["table_number"] = table.group(1)

        # Date (skip if ride receipt already set bill_date)
        if extracted.get("bill_date"):
            date_patterns = []
        else:
            date_patterns = [
                (r"Statement\s+Date\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", ["%d %B %Y", "%d %b %Y"]),
                (r"Bill\s+Date\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", ["%d %B %Y", "%d %b %Y"]),
                (r"Date[.:]?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", ["%d %B %Y", "%d %b %Y"]),
                (r"Date[.:]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", ["%d/%m/%Y", "%d-%m-%Y"]),
            ]
        for pattern, formats in date_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                for fmt in formats:
                    try:
                        extracted["bill_date"] = datetime.strptime(m.group(1).strip(), fmt)
                        break
                    except ValueError:
                        continue
                if extracted["bill_date"]:
                    break

        # Sub-total (explicit line; amount may be on the next line)
        extracted["subtotal"] = self._parse_subtotal(text)
        if extracted["subtotal"] is not None:
            extracted["_labelled_subtotal"] = True

        # Statement-level total (Total Amount Payable, etc.) before line scanning
        extracted["total_amount"] = self._parse_total_amount(
            text, subtotal=extracted.get("subtotal")
        )
        if extracted["total_amount"] is not None:
            extracted["_labelled_total"] = True

        # Fallback: last meaningful Total line (not Sub-Total)
        if extracted["total_amount"] is None:
            lines = self._split_lines(text)
            for idx, line in enumerate(lines):
                if not re.match(r"(?<!Sub[-\s])Total\s*:?\s*$", line, re.IGNORECASE):
                    continue
                if self._is_table_column_header_total(lines, idx):
                    continue
                amt = self._amount_from_following_lines(
                    lines, idx, max_lookahead=6, min_amount=10.0
                )
                if amt is not None:
                    extracted["total_amount"] = amt
                    extracted["_labelled_total"] = True
                    break

        if extracted["total_amount"] is None:
            for line in reversed(text.splitlines()):
                stripped = line.strip()
                if not stripped or re.match(r"Sub[-\s]*Total", stripped, re.IGNORECASE):
                    continue
                if re.search(r"Total\s+Amount\s+Payable", stripped, re.IGNORECASE):
                    amt = self._amount_from_line(stripped)
                    if amt is not None:
                        extracted["total_amount"] = amt
                        break
                if re.search(r"(?<!Sub[-\s])Total\b", stripped, re.IGNORECASE):
                    amt = self._amount_from_line(stripped)
                    if amt is not None:
                        extracted["total_amount"] = amt
                        break

        # GST registration number (not tax amount)
        gst_no = re.search(r"GST\s*No[.:]?\s*([A-Z0-9]+)", text, re.IGNORECASE)
        if gst_no:
            extracted["vendor_gst"] = gst_no.group(1).strip()

        # Vendor — telecom before ride/food heuristics
        telecom_vendor = self._parse_telecom_vendor(text)
        if telecom_vendor:
            extracted["vendor_name"] = telecom_vendor
        elif extracted.get("vendor_name"):
            pass
        elif re.search(r"\buber\b", text, re.IGNORECASE):
            extracted["vendor_name"] = "Uber"
        for line in text.splitlines():
            if extracted.get("vendor_name"):
                break
            line = line.strip()
            if re.search(r"kitchen", line, re.IGNORECASE) and len(line) > 6:
                m = re.search(
                    r"([A-Za-z][A-Za-z'\s&]*Kitchen)",
                    line,
                    re.IGNORECASE,
                )
                if m and len(m.group(1)) > 8:
                    name = m.group(1).strip()
                    extracted["vendor_name"] = name
                    extracted["restaurant_name"] = name
                    break

        if not extracted.get("vendor_name"):
            for pattern in (
                r"(Madhuri'?s?\s*Kitchen)",
                r"^([A-Za-z][\w\s&']{4,}Kitchen)\s*$",
            ):
                m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
                if m:
                    extracted["vendor_name"] = m.group(1).strip()
                    extracted["restaurant_name"] = m.group(1).strip()
                    break

        if not extracted.get("vendor_name"):
            header_vendor = self._parse_receipt_header_vendor(text)
            if header_vendor:
                extracted["vendor_name"] = header_vendor
                extracted["restaurant_name"] = header_vendor

        if not extracted.get("vendor_name"):
            brand_vendor = self._parse_vendor_from_branding(text)
            if brand_vendor:
                extracted["vendor_name"] = brand_vendor
                extracted["restaurant_name"] = brand_vendor

        # Re-apply ride fields after generic total/date may have overwritten
        self._parse_ride_receipt(text, extracted)

        # Tax (CGST + SGST lines only; uses subtotal/total for decimal fix)
        tax_total, tax_breakdown = self._parse_gst_tax(
            text,
            subtotal=extracted.get("subtotal"),
            grand_total=extracted.get("total_amount"),
        )
        extracted["tax_breakdown"] = tax_breakdown
        if tax_total is not None:
            extracted["tax_amount"] = tax_total
        elif extracted.get("subtotal") and extracted.get("total_amount"):
            implied = round(extracted["total_amount"] - extracted["subtotal"], 2)
            cap = min(100000.0, extracted["total_amount"] * 0.45)
            if 0 < implied < cap:
                extracted["tax_amount"] = implied
                half = round(implied / 2, 2)
                extracted["tax_breakdown"] = {"cgst": half, "sgst": implied - half}

        # Payment mode
        extracted["payment_method"] = self._parse_payment_method(text)

        # Line items
        extracted["items_list"] = self._parse_line_items(text)

        self._reconcile_financial_fields(extracted)

        # Confidence score
        score = 0.0
        checks = [
            ("total_amount", 30),
            ("vendor_name", 20),
            ("bill_date", 15),
            ("bill_number", 10),
            ("tax_amount", 10),
            ("payment_method", 10),
            ("pickup_location", 5),
            ("ride_distance", 5),
            ("items_list", 5),
        ]
        for field, weight in checks:
            val = extracted.get(field)
            if val is not None and val != [] and val != {}:
                score += weight
        sub = extracted.get("subtotal")
        tot = extracted.get("total_amount")
        tax = extracted.get("tax_amount")
        if (
            sub is not None
            and tot is not None
            and tax is not None
            and abs((sub + tax) - tot) <= max(2.0, 0.02 * tot)
        ):
            score = min(100.0, score + 5.0)
        extracted["confidence_score"] = min(score, 100.0)

        extracted.update(classify_bill(extracted, text))

        return extracted

    async def extract_bill_data(self, file_path: str, file_type: str) -> Dict[str, Any]:
        return self.extract_bill_data_sync(file_path, file_type)

    def extract_bill_data_sync(self, file_path: str, file_type: str) -> Dict[str, Any]:
        import os

        if os.getenv("OCR_TEST_BYPASS", "").strip().lower() in ("1", "true", "yes"):
            sample = """
Bhagini
Sriganda Palace
Sub-Total 3000
CGST 2.5% 75
SGST 2.5% 75
Payment Mode: Cash
Total
3150
"""
            parsed = self._parse_bill_text(sample)
            parsed["raw_text"] = sample.strip()
            parsed["confidence_score"] = 88.0
            parsed["ocr_engine_confidence"] = 0.88
            return parsed

        if file_type.lower() == "pdf":
            return self.process_pdf_sync(file_path)
        if file_type.lower() in ["jpg", "jpeg", "png", "webp", "avi"]:
            return self.process_image_sync(file_path)
        raise ValueError(f"Unsupported file type: {file_type}")
