import logging

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings

logger = logging.getLogger(__name__)

_connect_args = {"connect_timeout": 10}
if "sslmode=require" in settings.database_url or "aivencloud.com" in settings.database_url:
    _connect_args["sslmode"] = "require"

# NullPool only: no idle pooled connections — each request borrows one slot and releases it.
engine = create_engine(
    settings.database_url,
    poolclass=NullPool,
    connect_args=_connect_args,
)
logger.info("database.engine pool=null (single shared database, no connection pool)")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Register finance immutability hooks (snapshot before_update/delete guards)
import app.finance.events  # noqa: F401, E402


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database() -> dict:
    """Quick connectivity probe for /health (does not hold a pooled connection long)."""
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:
        msg = str(exc)
        if "connection slots" in msg.lower() or "too many clients" in msg.lower():
            msg = (
                "PostgreSQL connection limit reached. "
                "Stop other apps using this database and restart the backend."
            )
        logger.warning("database.check failed: %s", exc)
        return {"ok": False, "error": msg[:500]}


def dispose_engine() -> None:
    """Release all pooled connections (call on app shutdown)."""
    engine.dispose()
    logger.info("database.engine disposed")
