"""
config.py — Centralized application configuration.

All runtime behaviour is controlled through environment variables.
For local development, copy .env.example to .env and fill in the values.
In production (Vercel / Docker), set variables directly in the environment.
"""
from __future__ import annotations

import json
import logging

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables (and optionally a .env file).
    Every setting has a safe default so the server can start without a .env file,
    but GEMINI_API_KEY must be set for extraction to work.

    SOC2 note: all sensitive values are environment-only; they are never committed to source
    control and never logged.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",           # ignore unknown env vars — avoids noisy validation errors
        populate_by_name=True,
    )

    # ── Gemini API ────────────────────────────────────────────────────────────
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")

    # ── Upload limits ─────────────────────────────────────────────────────────
    # Maximum accepted file size in bytes (default 50 MB)
    max_file_bytes: int = Field(default=50 * 1024 * 1024, validation_alias="MAX_FILE_BYTES")

    # ── Rate limiting ─────────────────────────────────────────────────────────
    # slowapi format: "N/period"  e.g. "10/minute", "100/hour"
    # Note: in-process rate limiting does not carry over across serverless invocations
    # (Vercel). For serverless, rely on Vercel's built-in DDoS protection instead.
    rate_limit: str = Field(default="10/minute", validation_alias="RATE_LIMIT")

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins, or "*" to allow all.
    # Example: "https://app.ibislabs.com,https://staging.ibislabs.com"
    allowed_origins: str = Field(default="*", validation_alias="ALLOWED_ORIGINS")

    # ── Logging ───────────────────────────────────────────────────────────────
    # "json"  → one JSON object per line (production, structured log ingestion)
    # "text"  → human-readable format (local development)
    log_format: str = Field(default="json", validation_alias="LOG_FORMAT")


# Module-level singleton — import this everywhere instead of reading os.environ directly.
settings = Settings()


# ─── Logging ──────────────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """
    Emits each log record as a single-line JSON object suitable for ingestion by
    Datadog, CloudWatch, Vercel Log Drains, or any structured log pipeline.

    SOC2 (CC7.2): supports detection and monitoring of security events via
    structured, machine-parseable audit logs.
    """

    # Fields forwarded from logging.extra={...} to the JSON payload.
    _EXTRA_FIELDS = ("request_id", "file_bytes", "pages", "elapsed_ms")

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for field in self._EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    """
    Configure the root logger. Must be called once at application startup,
    before any other module emits log records.
    """
    handler = logging.StreamHandler()
    if settings.log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s")
        )
    logging.root.handlers = [handler]
    logging.root.setLevel(logging.INFO)

    # Validate critical environment setup
    if not settings.gemini_api_key:
        logging.critical(
            "GEMINI_API_KEY is not configured! "
            "Extraction will fail. Please set it in Vercel Settings > Environment Variables."
        )
    else:
        # Log limited confirmation (sanitize for SOC2/Privacy)
        masked_key = f"{settings.gemini_api_key[:4]}...{settings.gemini_api_key[-4:]}"
        logging.info("GEMINI_API_KEY is configured (starts with: %s)", settings.gemini_api_key[:4])

    # Suppress chatty third-party loggers that are not useful in production.
    for noisy in ("httpx", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
