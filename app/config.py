import logging
import os
from pathlib import Path
from typing import List, Optional

from openai import OpenAI
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def _resolve_env_file() -> Optional[str]:
    """Load .env locally; on Render/Docker use process env only (.env is not in the image)."""
    override = os.getenv("ENV_FILE", "").strip()
    if override:
        path = Path(override)
        return str(path) if path.is_file() else None
    default = Path(".env")
    return str(default) if default.is_file() else None


_ENV_FILE = _resolve_env_file()

class Settings(BaseSettings):
    database_url: str
    # NullPool = one connection per request, released immediately (required for low Aiven limits)
    db_use_null_pool: bool = True
    db_pool_size: int = 1
    db_max_overflow: int = 0
    db_pool_recycle: int = 1800
    db_pool_timeout: int = 10
    db_pool_pre_ping: bool = True
    uvicorn_workers: int = 1
    uvicorn_limit_concurrency: int = 40
    upload_dir: str = "/tmp/bizwy-uploads"
    max_upload_size: int = 10485760
    allowed_extensions: List[str] = ["jpg", "jpeg", "png", "pdf", "webp", "avi"]

    # OpenAI / AI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"  # alias for primary; prefer openai_primary_model
    openai_primary_model: str = "gpt-4o-mini"
    openai_fallback_model: str = "gpt-4.1-mini"
    openai_vision_model: str = "gpt-4o-mini"
    openai_vision_timeout_seconds: float = 90.0
    openai_timeout_seconds: float = 60.0
    openai_max_retries: int = 3
    openai_temperature: float = 0.55
    openai_conversational_enabled: bool = True
    openai_dynamic_welcome: bool = True
    ai_max_prompt_tokens: int = 12000

    # Tool execution
    max_tool_execution_seconds: float = 15.0
    tool_circuit_failure_threshold: int = 5
    tool_circuit_recovery_seconds: int = 60

    # Idempotency (seconds)
    ai_idempotency_ttl_seconds: int = 86400

    # Session memory TTLs (seconds; reserved for future expiry policies)
    ai_session_ttl_seconds: int = 3600
    ai_draft_expense_ttl_seconds: int = 7200
    ai_pending_intent_ttl_seconds: int = 1800
    ai_workflow_state_ttl_seconds: int = 86400

    # Memory decay
    ai_memory_decay_low_importance_threshold: float = 0.25
    ai_stale_intent_hours: int = 24
    ai_memory_soft_half_life_days: float = 90.0
    ai_memory_soft_floor_importance: float = 0.12

    # Preference learning & conflict resolution
    ai_pref_min_observations_for_prompt: int = 3
    ai_pref_min_observations_for_primary: int = 2
    ai_pref_min_confidence_for_prompt: float = 0.45
    ai_pref_draft_learning_weight: float = 0.35
    ai_pref_conflict_decay_factor: float = 0.88
    ai_pref_evolve_min_recent: int = 2
    ai_pref_evolve_window_days: int = 14

    # Workflow interrupt recovery (seconds before safe-recovery prompt)
    ai_workflow_interrupt_seconds: int = 3600

    # Context limits
    ai_recent_message_limit: int = 20
    ai_summary_trigger_message_count: int = 30

    # Human confirmation
    ai_confirmation_ttl_seconds: int = 600

    # Cost tracking (USD per 1M tokens — approximate)
    ai_cost_per_1m_prompt_tokens: float = 0.15
    ai_cost_per_1m_completion_tokens: float = 0.60

    # Tool rate limits (per user per minute)
    ai_tool_rate_limit_default: int = 30
    ai_tool_rate_limit_financial: int = 10

    # Safety thresholds
    ai_high_amount_threshold: float = 50000.0

    # Phase 4 — Voice (Whisper)
    whisper_model: str = "whisper-1"
    voice_max_audio_bytes: int = 25 * 1024 * 1024
    voice_max_duration_seconds: int = 300
    voice_allowed_extensions: List[str] = ["m4a", "mp3", "mp4", "mpeg", "mpga", "wav", "webm", "ogg"]
    voice_allowed_mime_types: List[str] = [
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/m4a",
        "audio/wav",
        "audio/webm",
        "audio/ogg",
        "audio/x-wav",
        "video/webm",
    ]

    # Receipt / document scanning (LLM vision)
    ocr_provider: str = "gpt4o_vision"
    ocr_field_confidence_threshold: float = 0.65
    ocr_overall_confidence_threshold: float = 0.55
    ocr_human_review_threshold: float = 0.60
    ocr_explainability_enabled: bool = True

    # Phase 5 — Manager copilot
    manager_approval_urgent_hours: float = 48.0
    manager_department_meal_budget_monthly: float = 50000.0
    manager_department_travel_budget_monthly: float = 200000.0

    # Phase 6+ manager analytics (disabled by default)
    forecasting_enabled: bool = False
    forecast_lookback_months: int = 6
    export_signatures_enabled: bool = False
    export_signing_secret: str = ""

    # Pre-Phase 7 — analytics caching
    analytics_cache_enabled: bool = True
    analytics_cache_ttl_quarterly: int = 3600
    analytics_cache_ttl_vendor: int = 1800
    analytics_cache_ttl_department: int = 1800
    analytics_cache_ttl_default: int = 900

    # Pre-Phase 7 — KPI alerting thresholds
    kpi_alert_budget_spike_pct: float = 25.0
    kpi_alert_policy_surge_count: int = 10
    kpi_alert_sla_overdue_pct: float = 20.0

    # Pre-Phase 7 — forecast explainability
    forecast_explainability_enabled: bool = True

    # Pre-Phase 7 — executive hardening
    kpi_alert_correlation_enabled: bool = False
    finance_report_version_default: str = "executive_pack_v1"

    # Future intelligence (disabled by default)
    receipt_fingerprint_enabled: bool = False
    ocr_locale_normalization_enabled: bool = False
    voice_biometric_enabled: bool = False

    # CORS — comma-separated origins, or "*" for all (default)
    cors_origins: str = "*"

    # Bizwy identity — token validation (production) or dev query-param trust
    bizwy_auth_mode: str = "dev"  # dev | token
    bizwy_api_base_url: str = "https://business.bizwy.in/v2"
    bizwy_validate_token_path: str = "authorization/validateToken.php"
    bizwy_token_cache_seconds: int = 300
    bizwy_http_timeout_seconds: float = 10.0

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()

if _ENV_FILE:
    logger.info("Settings loaded from %s and process environment", _ENV_FILE)
else:
    logger.info("Settings loaded from process environment only (no .env file)")

client = OpenAI(api_key=settings.openai_api_key)