import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.config import settings
from app.database import engine, Base, dispose_engine, check_database
from app.routers import expenses, ocr, wallet, dashboard, policies, claims, approvals, categories, tax, ai, ai_memory, intelligence, manager, finance, executive, filters, expense_workflow
from app.schemas import get_all_categories, get_category_hierarchy, get_policy_types
from app.ai.dependencies import shutdown_ai_services
from app.ai import models as _ai_models  # noqa: F401 — register AI tables with Base
from app.models import AIChatSession  # noqa: F401 — register chat session table
from app.middleware.no_buffer import NoBufferMiddleware

logger = logging.getLogger(__name__)

# Set True after background schema/migrations finish (used by /health/ready).
_startup_ready = False


def _db_unavailable_message(exc: BaseException) -> str:
    msg = str(getattr(exc, "orig", exc))
    if "connection slots" in msg.lower() or "too many clients" in msg.lower():
        return (
            "PostgreSQL connection limit reached. "
            "Stop pgAdmin/extra apps, restart backend, or use Aiven's connection pooler URL."
        )
    return msg[:500]


def _init_database_schema() -> None:
    """Create tables if missing. Log and continue when DB is unreachable (e.g. bad Render env)."""
    host = urlparse(settings.database_url).hostname or "(unknown)"
    logger.info("database.connecting host=%s", host)
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("database.schema_ready host=%s", host)
    except Exception as exc:
        logger.error(
            "database.schema_init_failed host=%s error=%s — "
            "check DATABASE_URL in Render Environment (Aiven host must resolve)",
            host,
            exc,
        )


async def _run_startup_init() -> None:
    """Schema + migrations off the critical path so Uvicorn binds $PORT before Render's scan."""
    global _startup_ready
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _init_database_schema)
        from app.migrations.add_expense_business_fields import run as _migrate_business
        from app.migrations.add_expense_submitted_by import run as _migrate_submitted_by

        await loop.run_in_executor(None, _migrate_business)
        await loop.run_in_executor(None, _migrate_submitted_by)
        from app.migrations.add_expense_company_scope import run as _migrate_company_scope

        await loop.run_in_executor(None, _migrate_company_scope)
    except Exception as exc:
        logger.warning("startup_init: %s", exc)
    finally:
        _startup_ready = True
        logger.info("startup_init complete ready=%s", _startup_ready)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_task = asyncio.create_task(_run_startup_init())
    if (settings.openai_api_key or "").strip():
        logger.info(
            "openai.ready model=%s conversational=%s welcome=%s",
            settings.openai_primary_model,
            settings.openai_conversational_enabled,
            settings.openai_dynamic_welcome,
        )
    else:
        logger.warning(
            "openai.not_configured — set OPENAI_API_KEY in .env for interactive copilot chat"
        )
    yield
    if not init_task.done():
        try:
            await asyncio.wait_for(init_task, timeout=120)
        except asyncio.TimeoutError:
            logger.warning("startup_init still running at shutdown")
            init_task.cancel()
    await shutdown_ai_services()
    dispose_engine()


app = FastAPI(
    title="Expense Tracker API",
    description="Track expenses with manual entry and LLM vision receipt scanning",
    version="1.0.0",
    lifespan=lifespan,
)

_cors_raw = (settings.cors_origins or "*").strip()
_cors_origins = ["*"] if _cors_raw == "*" else [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(NoBufferMiddleware)


@app.exception_handler(OperationalError)
async def database_operational_error_handler(_request: Request, exc: OperationalError):
    msg = _db_unavailable_message(exc)
    logger.warning("database.request_failed: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": msg, "database": {"ok": False, "error": msg}},
    )


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_request: Request, exc: SQLAlchemyError):
    msg = _db_unavailable_message(exc)
    logger.warning("database.request_failed: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": msg, "database": {"ok": False, "error": msg}},
    )


# Include routers
app.include_router(filters.router)
app.include_router(categories.router)
app.include_router(tax.router)
app.include_router(expenses.router)
app.include_router(ocr.router)
app.include_router(wallet.router)
app.include_router(dashboard.router)
app.include_router(policies.router)
app.include_router(claims.router)
app.include_router(approvals.router)
app.include_router(ai.router)
app.include_router(ai_memory.router)
app.include_router(intelligence.router)
app.include_router(manager.router)
app.include_router(finance.router)
app.include_router(executive.router)
app.include_router(expense_workflow.router)

@app.get("/")
async def root():
    return {"message": "Expense Tracker API", "status": "running"}

@app.get("/health")
async def health_check():
    """Liveness probe — always HTTP 200 so Render does not stop routing on transient DB blips."""
    from app.config import settings

    loop = asyncio.get_running_loop()
    db = await loop.run_in_executor(None, check_database)
    openai_configured = bool((settings.openai_api_key or "").strip())
    return {
        "status": "healthy" if db["ok"] else "degraded",
        "startup_ready": _startup_ready,
        "database": db,
        "openai": {
            "configured": openai_configured,
            "primary_model": settings.openai_primary_model,
            "vision_model": settings.openai_vision_model,
            "conversational": settings.openai_conversational_enabled and openai_configured,
            "dynamic_welcome": settings.openai_dynamic_welcome and openai_configured,
        },
    }


@app.get("/health/ready")
async def health_ready():
    """Readiness probe — fails when startup or database is not ready (use for strict checks)."""
    from app.config import settings

    if not _startup_ready:
        return JSONResponse(
            status_code=503,
            content={"status": "starting", "startup_ready": False},
        )

    loop = asyncio.get_running_loop()
    db = await loop.run_in_executor(None, check_database)
    openai_configured = bool((settings.openai_api_key or "").strip())
    body = {
        "status": "healthy" if db["ok"] else "degraded",
        "startup_ready": True,
        "database": db,
        "openai": {
            "configured": openai_configured,
            "primary_model": settings.openai_primary_model,
            "vision_model": settings.openai_vision_model,
            "conversational": settings.openai_conversational_enabled and openai_configured,
            "dynamic_welcome": settings.openai_dynamic_welcome and openai_configured,
        },
    }
    if not db["ok"]:
        return JSONResponse(status_code=503, content=body)
    return body


@app.get("/categories")
async def list_categories():
    return get_all_categories()


@app.get("/categories/hierarchy")
async def category_hierarchy():
    return get_category_hierarchy()


@app.get("/policy-types")
async def policy_types():
    return {"policy_types": get_policy_types()}


@app.get("/payment-modes")
async def payment_modes():
    from app.utils.payment_modes import list_payment_modes

    return list_payment_modes()