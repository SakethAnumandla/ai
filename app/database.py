import logging

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from app.config import settings

logger = logging.getLogger(__name__)

_connect_args = {}
if "sslmode=require" in settings.database_url or "aivencloud.com" in settings.database_url:
    _connect_args["sslmode"] = "require"

_use_null_pool = settings.db_use_null_pool

if _use_null_pool:
    engine = create_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args=_connect_args,
    )
    logger.info("database.engine pool=null")
else:
    engine = create_engine(
        settings.database_url,
        poolclass=QueuePool,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=settings.db_pool_pre_ping,
        connect_args=_connect_args,
    )
    logger.info(
        "database.engine pool_size=%s max_overflow=%s (max ~%s connections per process)",
        settings.db_pool_size,
        settings.db_max_overflow,
        settings.db_pool_size + settings.db_max_overflow,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Register finance immutability hooks (snapshot before_update/delete guards)
import app.finance.events  # noqa: F401, E402


def get_db():
    db = SessionLocal()
    try:
        yield db
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
                "Stop pgAdmin/extra apps, restart backend, or use Aiven's connection pooler URL."
            )
        logger.warning("database.check failed: %s", exc)
        return {"ok": False, "error": msg[:500]}


def dispose_engine() -> None:
    """Release all pooled connections (call on app shutdown)."""
    engine.dispose()
    logger.info("database.engine disposed")
