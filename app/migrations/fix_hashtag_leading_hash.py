"""Strip leading # from expenses.hashtags JSON. Run: python -m app.migrations.fix_hashtag_leading_hash"""
from sqlalchemy import text

from app.database import SessionLocal
from app.models import Expense
from app.utils.category_hashtags import normalize_hashtags_list


def run():
    db = SessionLocal()
    try:
        rows = db.query(Expense).filter(Expense.hashtags.isnot(None)).all()
        updated = 0
        for expense in rows:
            raw = expense.hashtags or []
            if not isinstance(raw, list):
                continue
            cleaned = normalize_hashtags_list(raw)
            if cleaned != raw:
                expense.hashtags = cleaned
                updated += 1
        db.commit()
        print(f"Normalized hashtags on {updated} expense(s).")
    finally:
        db.close()


if __name__ == "__main__":
    run()
