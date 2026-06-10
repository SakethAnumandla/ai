#!/usr/bin/env python3
"""
Seed random dated expenses, exercise time-period APIs, and verify against PostgreSQL.

Run from project root:
  .venv/bin/python scripts/test_time_period_filters.py
  .venv/bin/python scripts/test_time_period_filters.py --keep   # leave seed data in DB
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import func

from app.database import SessionLocal
from app.dependencies import DEV_USER_USERNAME
from app.main import app
from app.models import (
    Expense,
    ExpenseStatus,
    MainCategory,
    TransactionType,
    UploadMethod,
    User,
    Wallet,
    WalletTransaction,
)
from app.services.wallet_service import WalletService
from app.utils.time_period import apply_bill_date_filter, resolve_date_filter, resolve_time_period

PREFIX = "TZ_TEST_"


def _utc(*args) -> datetime:
    return datetime(*args)


def seed_rows(user_id: int) -> list[dict]:
    """Test expenses with known amounts and dates (May 2026 = 'today' in tests)."""
    now = datetime.utcnow()
    y, m = now.year, now.month
    if m == 1:
        last_m_y, last_m = y - 1, 12
    else:
        last_m_y, last_m = y, m - 1

    return [
        {
            "bill_name": f"{PREFIX}Custom pick day",
            "bill_amount": 77.0,
            "bill_date": _utc(y, m, 8, 18, 0, 0),
            "transaction_type": TransactionType.EXPENSE,
            "main_category": MainCategory.FOOD,
        },
        {
            "bill_name": f"{PREFIX}Lunch this month",
            "bill_amount": 500.0,
            "bill_date": _utc(y, m, 10, 12, 0, 0),
            "transaction_type": TransactionType.EXPENSE,
            "main_category": MainCategory.FOOD,
        },
        {
            "bill_name": f"{PREFIX}Cab this month",
            "bill_amount": 300.0,
            "bill_date": _utc(y, m, 15, 9, 0, 0),
            "transaction_type": TransactionType.EXPENSE,
            "main_category": MainCategory.TRAVEL,
        },
        {
            "bill_name": f"{PREFIX}Salary this month",
            "bill_amount": 2000.0,
            "bill_date": _utc(y, m, 5, 10, 0, 0),
            "transaction_type": TransactionType.INCOME,
            "main_category": MainCategory.SALARY,
        },
        {
            "bill_name": f"{PREFIX}Electricity last month",
            "bill_amount": 200.0,
            "bill_date": _utc(last_m_y, last_m, 20, 14, 0, 0),
            "transaction_type": TransactionType.EXPENSE,
            "main_category": MainCategory.BILLS,
        },
        {
            "bill_name": f"{PREFIX}Fuel earlier this year",
            "bill_amount": 150.0,
            "bill_date": _utc(y, 2, 8, 11, 0, 0) if m > 2 else _utc(y - 1, 11, 8),
            "transaction_type": TransactionType.EXPENSE,
            "main_category": MainCategory.FUEL,
        },
        {
            "bill_name": f"{PREFIX}Shopping last year",
            "bill_amount": 1000.0,
            "bill_date": _utc(y - 1, 6, 1, 16, 0, 0),
            "transaction_type": TransactionType.EXPENSE,
            "main_category": MainCategory.SHOPPING,
        },
    ]


def cleanup_seed(db, user_id: int) -> int:
    rows = (
        db.query(Expense)
        .filter(Expense.user_id == user_id, Expense.bill_name.like(f"{PREFIX}%"))
        .all()
    )
    ws = WalletService(db)
    for e in rows:
        ws.revert_transaction(e.id)
        db.delete(e)
    db.commit()
    return len(rows)


def seed_database(db, user_id: int) -> list[Expense]:
    wallet_svc = WalletService(db)
    created = []
    for row in seed_rows(user_id):
        exp = Expense(
            user_id=user_id,
            bill_name=row["bill_name"],
            bill_amount=row["bill_amount"],
            bill_date=row["bill_date"],
            transaction_type=row["transaction_type"],
            main_category=row["main_category"],
            status=ExpenseStatus.APPROVED,
            upload_method=UploadMethod.MANUAL,
            approved_at=datetime.utcnow(),
        )
        db.add(exp)
        db.flush()
        wallet_svc.update_wallet_balance(user_id, exp)
        created.append(exp)
    db.commit()
    for e in created:
        db.refresh(e)
    return created


def db_totals_for_filter(
    db,
    user_id: int,
    *,
    period: str | None = None,
    date: datetime | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> dict:
    resolved = resolve_date_filter(
        period=period, date=date, start_date=start_date, end_date=end_date
    )
    if not resolved:
        return {
            "count": 0,
            "income": 0,
            "expense": 0,
            "names": [],
            "filter_type": None,
            "label": None,
        }
    q = db.query(Expense).filter(
        Expense.user_id == user_id,
        Expense.status == ExpenseStatus.APPROVED,
        Expense.bill_name.like(f"{PREFIX}%"),
    )
    q = apply_bill_date_filter(q, Expense, resolved)
    rows = q.all()
    income = sum(r.bill_amount for r in rows if r.transaction_type == TransactionType.INCOME)
    expense = sum(r.bill_amount for r in rows if r.transaction_type == TransactionType.EXPENSE)
    return {
        "count": len(rows),
        "income": income,
        "expense": expense,
        "names": [r.bill_name for r in rows],
        "filter_type": resolved.filter_type,
        "label": resolved.label,
    }


def db_totals_for_period(db, user_id: int, period: str) -> dict:
    return db_totals_for_filter(db, user_id, period=period)


def wallet_tx_count_for_filter(
    db, user_id: int, *, period=None, date=None, start_date=None, end_date=None
) -> int:
    resolved = resolve_date_filter(
        period=period, date=date, start_date=start_date, end_date=end_date
    )
    if not resolved:
        return 0
    wallet = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    if not wallet:
        return 0
    q = (
        db.query(WalletTransaction)
        .join(Expense, Expense.id == WalletTransaction.expense_id)
        .filter(
            WalletTransaction.wallet_id == wallet.id,
            Expense.bill_name.like(f"{PREFIX}%"),
        )
    )
    q = apply_bill_date_filter(q, Expense, resolved)
    return q.count()


def wallet_tx_count(db, user_id: int, period: str) -> int:
    return wallet_tx_count_for_filter(db, user_id, period=period)


def print_db_snapshot(db, user_id: int) -> None:
    print("\n--- Database: seeded TZ_TEST_ expenses ---")
    rows = (
        db.query(Expense)
        .filter(Expense.user_id == user_id, Expense.bill_name.like(f"{PREFIX}%"))
        .order_by(Expense.bill_date)
        .all()
    )
    for r in rows:
        print(
            f"  id={r.id}  {r.bill_date.date()}  {r.transaction_type.value:7}  "
            f"₹{r.bill_amount:8.2f}  {r.bill_name}"
        )
    print(f"  Total rows: {len(rows)}")


def _stats(client: TestClient, period: str) -> dict | None:
    r = client.get(f"/dashboard/stats?period={period}")
    if r.status_code != 200:
        return None
    return r.json()["stats"]


def run_api_checks(client: TestClient, baseline: dict[str, dict], db, user_id: int) -> list[str]:
    errors = []
    # Expected deltas from our seed data only
    seed_expected = {
        "this_month": {"income": 2000.0, "expense": 877.0, "count": 4},
        "last_month": {"income": 0.0, "expense": 200.0, "count": 1},
        "last_year": {"income": 0.0, "expense": 1000.0, "count": 1},
        "all_time": {"income": 2000.0, "expense": 2227.0, "count": 7},
    }

    for period in ["this_month", "last_month", "this_year", "last_year", "all_time"]:
        r = client.get(f"/dashboard/stats?period={period}")
        if r.status_code != 200:
            errors.append(f"stats/{period}: HTTP {r.status_code} {r.text[:200]}")
            continue
        body = r.json()
        dr = body["date_range"]
        stats = body["stats"]
        base = baseline.get(period, {"total_income": 0, "total_expense": 0})
        d_inc = stats["total_income"] - base["total_income"]
        d_exp = stats["total_expense"] - base["total_expense"]

        print(f"\n--- API GET /dashboard/stats?period={period} ---")
        print(f"  label: {dr['label']}")
        print(f"  range: {dr.get('start_date')} → {dr['end_date']}")
        print(
            f"  totals: income={stats['total_income']}  expense={stats['total_expense']}  "
            f"(Δ seed +{d_inc:.0f} / +{d_exp:.0f} vs baseline)"
        )

        if period in seed_expected:
            exp = seed_expected[period]
            db_t = db_totals_for_period(db, user_id, period)
            if abs(d_inc - exp["income"]) > 0.01:
                errors.append(
                    f"stats/{period}: income delta expected +{exp['income']}, got +{d_inc}"
                )
            if abs(d_exp - exp["expense"]) > 0.01:
                errors.append(
                    f"stats/{period}: expense delta expected +{exp['expense']}, got +{d_exp}"
                )
            if db_t["count"] != exp["count"]:
                errors.append(
                    f"DB/{period}: expected {exp['count']} TZ_TEST rows, got {db_t['count']}"
                )

        ov = client.get(f"/dashboard/overview?period={period}")
        if ov.status_code != 200:
            errors.append(f"overview/{period}: HTTP {ov.status_code}")
        else:
            oj = ov.json()
            print(
                f"  overview: recent={len(oj.get('recent_transactions', []))}  "
                f"categories={len(oj.get('category_breakdown', []))}"
            )

        ws = client.get(f"/wallet/summary?period={period}")
        if ws.status_code != 200:
            errors.append(f"wallet/summary/{period}: HTTP {ws.status_code}")
        else:
            wj = ws.json()
            db_w = wallet_tx_count(db, user_id, period)
            print(
                f"  wallet: period_income={wj['period_income']}  period_expense={wj['period_expense']}  "
                f"tx_count={wj['transaction_count']} (TZ_TEST wallet_tx in DB={db_w})"
            )
            if period in seed_expected and wj["transaction_count"] < seed_expected[period]["count"]:
                # wallet may include non-test txs; only warn if fewer than our seed
                pass

    return errors


def run_custom_date_range_checks(
    client: TestClient, db, user_id: int, y: int, m: int
) -> list[str]:
    errors = []
    pick_day = _utc(y, m, 8)
    day_iso = pick_day.strftime("%Y-%m-%d")
    lm = resolve_date_filter(period="last_month")
    range_start, range_end = lm.start_date, lm.end_date

    cases = [
        (
            "custom single date",
            f"/dashboard/stats?date={day_iso}",
            {"date": pick_day},
            {"count": 1, "expense": 77.0, "filter_type": "single_date"},
        ),
        (
            "custom range (last calendar month)",
            f"/dashboard/stats?start_date={range_start.isoformat()}&end_date={range_end.isoformat()}",
            {"start_date": range_start, "end_date": range_end},
            {"count": 1, "expense": 200.0, "filter_type": "date_range"},
        ),
    ]

    print("\n========== Custom date / range tests ==========")
    for label, path, db_kw, expected in cases:
        r = client.get(path)
        if r.status_code != 200:
            errors.append(f"{label}: HTTP {r.status_code}")
            continue
        dr = r.json()["date_range"]
        stats = r.json()["stats"]
        db_t = db_totals_for_filter(db, user_id, **db_kw)
        print(f"\n--- {label} ---")
        print(f"  API: {path[:70]}...")
        print(f"  filter_type={dr.get('filter_type')}  label={dr.get('label')}")
        print(f"  API expense delta in stats: {stats['total_expense']} (includes all approved)")
        print(f"  DB TZ_TEST: count={db_t['count']} expense=₹{db_t['expense']:.0f}")
        for n in db_t["names"]:
            print(f"      - {n}")
        if db_t["count"] != expected["count"]:
            errors.append(f"{label}: DB count {db_t['count']} != {expected['count']}")
        if abs(db_t["expense"] - expected["expense"]) > 0.01:
            errors.append(
                f"{label}: DB expense {db_t['expense']} != {expected['expense']}"
            )
        if dr.get("filter_type") != expected.get("filter_type"):
            errors.append(
                f"{label}: filter_type {dr.get('filter_type')} != {expected['filter_type']}"
            )

        ws = client.get(path.replace("/dashboard/stats", "/wallet/summary"))
        if ws.status_code == 200:
            print(f"  wallet tx (TZ_TEST in DB): {wallet_tx_count_for_filter(db, user_id, **db_kw)}")

    # Overview with custom date
    ov = client.get(f"/dashboard/overview?date={day_iso}")
    if ov.status_code != 200:
        errors.append(f"overview?date=: HTTP {ov.status_code}")
    else:
        tz_recent = [
            t
            for t in ov.json().get("recent_transactions", [])
            if str(t.get("bill_name", "")).startswith(PREFIX)
        ]
        print(f"\n--- overview?date={day_iso} ---")
        print(f"  TZ_TEST in recent_transactions: {len(tz_recent)}")
        if len(tz_recent) != 1:
            errors.append(f"overview date: expected 1 TZ_TEST recent, got {len(tz_recent)}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="Do not delete seed data after test")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == DEV_USER_USERNAME).first()
        if not user:
            print("ERROR: dev user not found. Start API once to create devuser.")
            return 1

        removed = cleanup_seed(db, user.id)
        if removed:
            print(f"Removed {removed} previous TZ_TEST_ rows")

        client = TestClient(app)
        baseline = {}
        for period in ["this_month", "last_month", "this_year", "last_year", "all_time"]:
            s = _stats(client, period)
            baseline[period] = s or {"total_income": 0, "total_expense": 0}
        print("Captured API baseline before seeding.")

        created = seed_database(db, user.id)
        print(f"Seeded {len(created)} approved expenses + wallet transactions for user {user.username} (id={user.id})")
        print_db_snapshot(db, user.id)

        print("\n--- DB verification by period (TZ_TEST_ rows only) ---")
        for period in ["this_month", "last_month", "this_year", "last_year", "all_time"]:
            t = db_totals_for_period(db, user.id, period)
            w = wallet_tx_count(db, user.id, period)
            print(
                f"  {period:12}  expenses={t['count']}  income=₹{t['income']:.0f}  "
                f"expense=₹{t['expense']:.0f}  wallet_tx={w}"
            )
            if t["count"] <= 4:
                for n in t["names"]:
                    print(f"      - {n}")

        now = datetime.utcnow()
        y, m = now.year, now.month

        print("\n========== Preset period API tests ==========")
        errors = run_api_checks(client, baseline, db, user.id)
        errors.extend(run_custom_date_range_checks(client, db, user.id, y, m))

        print("\n--- pgAdmin: verify in SQL ---")
        print("  SELECT id, bill_date::date, transaction_type, bill_amount, bill_name")
        print("  FROM expenses WHERE bill_name LIKE 'TZ_TEST_%' ORDER BY bill_date;")

        # TZ_TEST rows in DB must match resolve_time_period boundaries
        for period in ["this_month", "last_month", "last_year"]:
            resolved = resolve_time_period(period)
            q = db.query(Expense).filter(
                Expense.user_id == user.id,
                Expense.bill_name.like(f"{PREFIX}%"),
            )
            if resolved.start_date:
                q = q.filter(Expense.bill_date >= resolved.start_date)
            q = q.filter(Expense.bill_date <= resolved.end_date)
            db_count = q.count()
            db_exp = (
                db.query(Expense)
                .filter(
                    Expense.user_id == user.id,
                    Expense.bill_name.like(f"{PREFIX}%"),
                    Expense.transaction_type == TransactionType.EXPENSE,
                )
            )
            if resolved.start_date:
                db_exp = db_exp.filter(Expense.bill_date >= resolved.start_date)
            db_exp = db_exp.filter(Expense.bill_date <= resolved.end_date)
            db_exp_count = db_exp.count()

            api_list = client.get(f"/expenses?period={period}&limit=100")
            if api_list.status_code == 200:
                api_tz = [
                    e
                    for e in api_list.json()
                    if e.get("bill_name", "").startswith(PREFIX)
                ]
                if len(api_tz) != db_exp_count:
                    errors.append(
                        f"expenses/{period}: API lists {len(api_tz)} TZ_TEST expenses, "
                        f"DB has {db_exp_count} (income excluded by default)"
                    )

        if errors:
            print("\n*** FAILURES ***")
            for e in errors:
                print(f"  - {e}")
            return 1

        print("\n✓ All checks passed.")
        if args.keep:
            print("\nData kept in DB (bill_name LIKE 'TZ_TEST_%'). View in pgAdmin: http://localhost:5050/")
        return 0
    finally:
        if not args.keep:
            user = db.query(User).filter(User.username == DEV_USER_USERNAME).first()
            if user:
                n = cleanup_seed(db, user.id)
                if n:
                    print(f"\nCleaned up {n} TZ_TEST_ rows from database.")
        db.close()


if __name__ == "__main__":
    sys.exit(main())
