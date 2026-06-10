"""Enrich OCR/manual prefill with business taxonomy + fiscal year + GST hints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from app.data.business_taxonomy import (
    LEGACY_MAIN_TO_BUSINESS,
    classify_taxonomy_from_scan,
    map_business_main_to_legacy_manual,
    resolve_line_item_meta,
    suggest_categories_from_text,
)
from app.utils.fiscal_year import financial_year_label, validate_bill_date


def enrich_prefill_dict(prefill: Dict[str, Any]) -> Dict[str, Any]:
    """Merge taxonomy, FY, and tax fields into a prefill payload."""
    out = dict(prefill)
    main = (out.get("main_category") or "").lower()
    if main in LEGACY_MAIN_TO_BUSINESS:
        out["main_category"] = LEGACY_MAIN_TO_BUSINESS[main]
        out["manual_category"] = main

    scan_source = {
        "vendor_name": out.get("vendor_name"),
        "restaurant_name": out.get("restaurant_name"),
        "bill_name": out.get("bill_name"),
        "description": out.get("description"),
        "raw_text": out.get("raw_text"),
        "items_list": out.get("items_list") or [],
    }
    scan_cat = classify_taxonomy_from_scan(scan_source)
    if scan_cat.get("main_category"):
        business_main = scan_cat["main_category"]
        out["main_category"] = business_main
        out["manual_category"] = map_business_main_to_legacy_manual(business_main)
        out["sub_category"] = scan_cat.get("sub_category")
        out["line_item"] = scan_cat.get("line_item")
        out["category_needs_review"] = False
    else:
        text = " ".join(
            filter(
                None,
                [
                    str(out.get("bill_name") or ""),
                    str(out.get("vendor_name") or ""),
                    str(out.get("restaurant_name") or ""),
                    str(out.get("description") or ""),
                ],
            )
        )
        hinted = suggest_categories_from_text(text)
        low_confidence = main in ("", "miscellaneous") or not out.get("sub_category")

        if low_confidence and hinted.get("main_category"):
            business_main = hinted["main_category"]
            out["main_category"] = business_main
            out["manual_category"] = map_business_main_to_legacy_manual(business_main)
            out["sub_category"] = hinted.get("sub_category")
            out["line_item"] = hinted.get("line_item")
            out["category_needs_review"] = False
        elif not out.get("sub_category") or not out.get("line_item"):
            if hinted.get("main_category"):
                out.setdefault("main_category", hinted.get("main_category"))
            out.setdefault("sub_category", hinted.get("sub_category"))
            out.setdefault("line_item", hinted.get("line_item"))

        if (
            (out.get("main_category") or "").lower() in ("", "miscellaneous")
            and not out.get("sub_category")
            and not out.get("line_item")
        ):
            out["category_needs_review"] = True
            out["main_category"] = out.get("main_category") or "miscellaneous"
            out["sub_category"] = None
            out["line_item"] = None
        else:
            out.setdefault("category_needs_review", False)

    out.pop("items_list", None)

    meta = resolve_line_item_meta(
        out.get("main_category"),
        out.get("sub_category"),
        out.get("line_item"),
    )
    if meta:
        out["line_item_label"] = meta.get("label")
        gst = meta.get("gst_pct")
        if gst and gst not in ("No", "Varies") and str(gst).endswith("%"):
            try:
                out["gst_rate_pct"] = float(str(gst).replace("%", ""))
            except ValueError:
                pass
        out["itc_eligible"] = str(meta.get("itc_eligible", "No")).lower() == "yes"
        if meta.get("notes"):
            out.setdefault("description", meta["notes"])

    bill_date = out.get("bill_date")
    if isinstance(bill_date, datetime):
        try:
            out["financial_year"] = validate_bill_date(bill_date.date())
        except ValueError:
            out["financial_year"] = financial_year_label(bill_date.date())
    elif bill_date:
        try:
            dt = datetime.fromisoformat(str(bill_date).replace("Z", "+00:00"))
            out["financial_year"] = financial_year_label(dt.date())
        except Exception:
            pass

    total = float(out.get("bill_amount") or 0)
    rate = out.get("gst_rate_pct")
    if rate and total > 0 and not out.get("amount_excl_gst"):
        excl = round(total / (1 + float(rate) / 100), 2)
        out["amount_excl_gst"] = excl
        out["gst_amount"] = round(total - excl, 2)
    elif out.get("subtotal") and total > 0:
        out["amount_excl_gst"] = float(out["subtotal"])
        out["gst_amount"] = round(total - float(out["subtotal"]), 2)

    if not out.get("gst_rate_pct"):
        sub = out.get("subtotal") or out.get("amount_excl_gst")
        tax = out.get("gst_amount") or out.get("tax_amount")
        if sub and tax:
            try:
                sub_f = float(sub)
                tax_f = float(tax)
                if sub_f > 0 and tax_f > 0:
                    out["gst_rate_pct"] = round(tax_f / sub_f * 100, 2)
            except (TypeError, ValueError):
                pass

    out.setdefault("currency_code", "EUR")

    if out.get("classification_confidence") is None:
        conf = prefill.get("classification_confidence")
        if conf is not None:
            out["classification_confidence"] = float(conf)

    if out.get("scan_quality") is None and prefill.get("scan_quality"):
        out["scan_quality"] = prefill.get("scan_quality")

    return out
