"""Regression tests for production-failed endpoints."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_tax_regimes_list(client: TestClient):
    r = client.get("/tax/regimes")
    assert r.status_code == 200
    data = r.json()
    assert "countries" in data
    assert "regimes" in data
    assert any(c["country_code"] == "IN" for c in data["countries"])


def test_tax_regimes_by_country(client: TestClient):
    r = client.get("/tax/regimes", params={"country": "IN"})
    assert r.status_code == 200
    assert r.json()["country_code"] == "IN"
    assert r.json()["regime_code"] == "india_gst"

    r404 = client.get("/tax/regimes", params={"country": "ZZ"})
    assert r404.status_code == 404


def test_manual_expense_hierarchy_line_item(client: TestClient):
    """Legacy main_category + hierarchy line_item should not 500."""
    files = [("files", ("receipt.png", MINIMAL_PNG, "image/png"))]
    data = {
        "bill_name": "Hierarchy lunch",
        "bill_amount": "150.0",
        "bill_date": "15/05/2026",
        "main_category": "food",
        "sub_category": "business_meals",
        "line_item": "working_lunches",
        "save_as_draft": "true",
    }
    r = client.post("/expenses/manual", data=data, files=files)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["main_category"] == "meals_entertainment"
    assert body["sub_category"] == "business_meals"
    assert body["line_item"] == "working_lunches"


def test_expense_details_no_duplicate_kwargs(client: TestClient):
    files = [("files", ("receipt.png", MINIMAL_PNG, "image/png"))]
    created = client.post(
        "/expenses/manual",
        data={
            "bill_name": "Details test",
            "bill_amount": "99.0",
            "bill_date": "15/05/2026",
            "main_category": "miscellaneous",
            "save_as_draft": "true",
        },
        files=files,
    )
    assert created.status_code == 201, created.text
    expense_id = created.json()["id"]

    r = client.get(f"/expenses/{expense_id}/details")
    assert r.status_code == 200, r.text
    assert "remarks_table" in r.json()


def test_ocr_scan_returns_draft_not_500(client: TestClient):
    files = {"file": ("receipt.png", io.BytesIO(MINIMAL_PNG), "image/png")}
    r = client.post("/ocr/scan", files=files)
    assert r.status_code in (200, 201), r.text


def test_manual_scan_returns_draft_not_500(client: TestClient):
    files = {"file": ("receipt.png", io.BytesIO(MINIMAL_PNG), "image/png")}
    r = client.post("/expenses/manual/scan", files=files)
    assert r.status_code == 201, r.text


def test_ocr_scan_drafts_not_500(client: TestClient):
    files = [("files", ("receipt.png", io.BytesIO(MINIMAL_PNG), "image/png"))]
    r = client.post("/ocr/scan-drafts", files=files)
    assert r.status_code == 200, r.text
