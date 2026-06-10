"""Multi-page PDF aggregation — stitch pages, merge totals."""
import re
from typing import Any, Dict, List, Optional


class PdfPageExtractor:
    """Extract per-page OCR from PDF via image conversion."""

    def __init__(self, processor):
        self._processor = processor

    def extract_per_page(self, pdf_path: str) -> List[Dict[str, Any]]:
        import os

        import pdf2image

        try:
            images = pdf2image.convert_from_path(pdf_path, dpi=300)
        except Exception:
            return []

        pages: List[Dict[str, Any]] = []
        base = pdf_path.rsplit(".", 1)[0]
        for i, image in enumerate(images, start=1):
            temp_path = f"{base}_page{i}.jpg"
            image.save(temp_path, "JPEG")
            try:
                page_result = self._processor.process_image_sync(temp_path)
                page_result["page_number"] = i
                pages.append(page_result)
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        return pages


class PdfReceiptAggregator:
    """Merge multi-page extractions into a single invoice."""

    @staticmethod
    def stitch(page_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not page_results:
            return {}
        if len(page_results) == 1:
            merged = dict(page_results[0])
            merged["pdf_page_count"] = 1
            merged["page_extractions"] = page_results
            return merged

        texts = []
        totals: List[float] = []
        subtotals: List[float] = []
        taxes: List[float] = []
        merchants: List[str] = []
        invoice_ids: List[str] = []
        dates = []
        confidences: List[float] = []

        for p in page_results:
            raw = (p.get("raw_text") or "").strip()
            if raw:
                texts.append(f"--- page {p.get('page_number', '?')} ---\n{raw}")
            for key, bucket in (
                ("total_amount", totals),
                ("subtotal", subtotals),
                ("tax_amount", taxes),
            ):
                val = p.get(key)
                if val is not None:
                    try:
                        bucket.append(float(val))
                    except (TypeError, ValueError):
                        pass
            vn = p.get("vendor_name") or p.get("restaurant_name")
            if vn:
                merchants.append(vn)
            if p.get("bill_number"):
                invoice_ids.append(str(p["bill_number"]))
            if p.get("bill_date"):
                dates.append(p["bill_date"])
            if p.get("confidence_score") is not None:
                confidences.append(float(p["confidence_score"]))

        primary = page_results[0]
        merged = dict(primary)
        merged["raw_text"] = "\n".join(texts)
        merged["pdf_page_count"] = len(page_results)
        merged["page_extractions"] = page_results

        if totals:
            merged["total_amount"] = max(totals)
        if subtotals:
            merged["subtotal"] = max(subtotals)
        if taxes:
            merged["tax_amount"] = sum(taxes)
        if merchants:
            merged["vendor_name"] = PdfReceiptAggregator._best_merchant(merchants)
        if invoice_ids:
            merged["bill_number"] = invoice_ids[0]
        if dates:
            merged["bill_date"] = min(dates)
        if confidences:
            merged["confidence_score"] = sum(confidences) / len(confidences)

        merged["stitched"] = True
        return merged

    @staticmethod
    def _best_merchant(merchants: List[str]) -> str:
        from collections import Counter

        counts = Counter(m.strip() for m in merchants if m and m.strip())
        if counts:
            return counts.most_common(1)[0][0]
        return merchants[0]
