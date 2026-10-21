from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOGGER = logging.getLogger(__name__)
LOCAL_DEVELOPMENT_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


@dataclass(frozen=True)
class OpenAISettings:
    api_key: str | None
    agent_model: str
    explanation_model: str
    agent_timeout_seconds: float = 180.0
    frontend_origins: tuple[str, ...] = LOCAL_DEVELOPMENT_ORIGINS
    supabase_url: str | None = None
    supabase_publishable_key: str | None = None
    supabase_service_role_key: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_publishable_key and self.supabase_service_role_key)


def _configured_frontend_origins(value: str | None) -> tuple[str, ...]:
    origins = list(LOCAL_DEVELOPMENT_ORIGINS)
    for raw_origin in (value or "").split(","):
        origin = raw_origin.strip().rstrip("/")
        if not origin:
            continue
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path:
            raise ValueError("FRONTEND_ORIGIN must contain absolute HTTP(S) origins without paths")
        if origin not in origins:
            origins.append(origin)
    return tuple(origins)


def _agent_timeout_seconds(value: str | None) -> float:
    if value is None or not value.strip():
        return 180.0
    try:
        timeout = float(value)
    except ValueError as error:
        raise ValueError("OPENAI_AGENT_TIMEOUT_SECONDS must be a number") from error
    if not 30 <= timeout <= 240:
        raise ValueError("OPENAI_AGENT_TIMEOUT_SECONDS must be between 30 and 240 seconds")
    return timeout


def load_settings(env_path: Path | None = None) -> OpenAISettings:
    load_dotenv(env_path or REPOSITORY_ROOT / ".env", override=False)
    legacy_model = os.getenv("OPENAI_MODEL")
    return OpenAISettings(
        api_key=os.getenv("OPENAI_API_KEY") or None,
        agent_model=os.getenv("OPENAI_AGENT_MODEL") or legacy_model or "gpt-5.6-sol",
        explanation_model=os.getenv("OPENAI_EXPLANATION_MODEL") or "gpt-5.6-luna",
        agent_timeout_seconds=_agent_timeout_seconds(os.getenv("OPENAI_AGENT_TIMEOUT_SECONDS")),
        frontend_origins=_configured_frontend_origins(os.getenv("FRONTEND_ORIGIN")),
        supabase_url=os.getenv("SUPABASE_URL") or None,
        supabase_publishable_key=os.getenv("SUPABASE_PUBLISHABLE_KEY") or None,
        supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY") or None,
    )


@lru_cache(maxsize=1)
def get_settings() -> OpenAISettings:
    return load_settings()


def log_openai_configuration(settings: OpenAISettings) -> None:
    LOGGER.info("Formulation Agent: %s", "configured" if settings.configured else "not configured")
    LOGGER.info("Agent model: %s", settings.agent_model)
    LOGGER.info("Agent request timeout: %s seconds", settings.agent_timeout_seconds)
    LOGGER.info("Explanation model: %s", settings.explanation_model)
    LOGGER.info("Supabase: %s", "configured" if settings.supabase_configured else "not configured")
