import logging

from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from app.config import settings

logger = logging.getLogger(__name__)


def _connect_args() -> dict:
    """PostgreSQL driver options for managed hosts (Aiven, Render)."""
    args: dict = {"connect_timeout": settings.db_pool_timeout}
    url = settings.database_url
    if "sslmode=require" in url or "aivencloud.com" in url:
        args["sslmode"] = "require"
    # Cloud load balancers and Postgres often drop idle TCP sessions around 5 minutes.
    args.update(
        {
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        }
    )
    return args


def _build_engine():
    connect_args = _connect_args()
    if settings.db_use_null_pool:
        logger.info(
            "database.engine pool=null (one connection per checkout; use Aiven pooler URL on Render)"
        )
        return create_engine(
            settings.database_url,
            poolclass=NullPool,
            connect_args=connect_args,
        )

    logger.info(
        "database.engine pool=queue size=%s overflow=%s recycle=%ss pre_ping=%s",
        settings.db_pool_size,
        settings.db_max_overflow,
        settings.db_pool_recycle,
        settings.db_pool_pre_ping,
    )
    return create_engine(
        settings.database_url,
        poolclass=QueuePool,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=settings.db_pool_pre_ping,
        connect_args=connect_args,
    )


engine = _build_engine()
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
    """Quick connectivity probe (does not hold a pooled connection long)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:
        msg = str(exc)
        if "connection slots" in msg.lower() or "too many clients" in msg.lower():
            msg = (
                "PostgreSQL connection limit reached. "
                "Use Aiven's connection pooler URL, stop extra clients, and restart the backend."
            )
        logger.warning("database.check failed: %s", exc)
        return {"ok": False, "error": msg[:500]}


def dispose_engine() -> None:
    """Release all pooled connections (call on app shutdown)."""
    engine.dispose()
    logger.info("database.engine disposed")
