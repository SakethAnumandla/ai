"""Create database (if missing) and all tables. Run from project root."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from app.config import settings
from app.database import Base
from app import models  # noqa: F401
from app.ai import models as ai_models  # noqa: F401


def main():
    url = settings.database_url
    # Connect to default DB to create expense_tracker if needed
    if url.rsplit("/", 1)[-1] == "expense_tracker":
        admin_url = url.rsplit("/", 1)[0] + "/postgres"
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = 'expense_tracker'")
            ).scalar()
            if not exists:
                conn.execute(text("CREATE DATABASE expense_tracker"))
                print("Created database expense_tracker")
            else:
                print("Database expense_tracker already exists")

    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully.")


if __name__ == "__main__":
    main()
