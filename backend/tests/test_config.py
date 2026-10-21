from __future__ import annotations

import logging

import pytest

from backend.app.config import load_settings, log_openai_configuration


def _clear_openai_environment(monkeypatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_AGENT_MODEL",
        "OPENAI_AGENT_TIMEOUT_SECONDS",
        "OPENAI_EXPLANATION_MODEL",
        "OPENAI_MODEL",
        "FRONTEND_ORIGIN",
        "SUPABASE_URL",
        "SUPABASE_PUBLISHABLE_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_repository_environment_file_is_loaded_with_role_specific_models(tmp_path, monkeypatch):
    _clear_openai_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=file-secret\nOPENAI_AGENT_MODEL=agent-from-file\n"
        "OPENAI_EXPLANATION_MODEL=explanation-from-file\n",
        encoding="utf-8",
    )
    settings = load_settings(env_file)
    assert settings.api_key == "file-secret"
    assert settings.agent_model == "agent-from-file"
    assert settings.explanation_model == "explanation-from-file"
    assert settings.agent_timeout_seconds == 180


def test_operating_system_environment_wins(tmp_path, monkeypatch):
    _clear_openai_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=file-secret\nOPENAI_AGENT_MODEL=file-agent\n"
        "OPENAI_EXPLANATION_MODEL=file-explanation\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "os-secret")
    monkeypatch.setenv("OPENAI_AGENT_MODEL", "os-agent")
    settings = load_settings(env_file)
    assert settings.api_key == "os-secret"
    assert settings.agent_model == "os-agent"
    assert settings.explanation_model == "file-explanation"


def test_legacy_model_is_agent_only(tmp_path, monkeypatch):
    _clear_openai_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_MODEL=legacy-agent\n", encoding="utf-8")
    settings = load_settings(env_file)
    assert settings.agent_model == "legacy-agent"
    assert settings.explanation_model == "gpt-5.6-luna"


def test_missing_key_uses_safe_model_defaults_and_logs_no_secret(tmp_path, monkeypatch, caplog):
    _clear_openai_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    settings = load_settings(env_file)
    assert settings.api_key is None
    assert settings.agent_model == "gpt-5.6-sol"
    assert settings.explanation_model == "gpt-5.6-luna"
    assert settings.agent_timeout_seconds == 180
    with caplog.at_level(logging.INFO):
        log_openai_configuration(settings)
    assert "Formulation Agent: not configured" in caplog.text
    assert "gpt-5.6-sol" in caplog.text
    assert "gpt-5.6-luna" in caplog.text
    assert "OPENAI_API_KEY" not in caplog.text


def test_agent_timeout_can_be_extended_from_environment(tmp_path, monkeypatch):
    _clear_openai_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_AGENT_TIMEOUT_SECONDS", "210")

    settings = load_settings(tmp_path / "missing.env")

    assert settings.agent_timeout_seconds == 210


def test_agent_timeout_rejects_values_beyond_serverless_budget(tmp_path, monkeypatch):
    _clear_openai_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_AGENT_TIMEOUT_SECONDS", "300")

    with pytest.raises(ValueError, match="between 30 and 240"):
        load_settings(tmp_path / "missing.env")


def test_configured_log_never_contains_key(tmp_path, monkeypatch, caplog):
    _clear_openai_environment(monkeypatch)
    secret = "secret-that-must-not-appear"
    env_file = tmp_path / ".env"
    env_file.write_text(f"OPENAI_API_KEY={secret}\n", encoding="utf-8")
    settings = load_settings(env_file)
    with caplog.at_level(logging.INFO):
        log_openai_configuration(settings)
    assert "Formulation Agent: configured" in caplog.text
    assert secret not in caplog.text


def test_frontend_origin_adds_exact_remote_origin_and_keeps_localhost(tmp_path, monkeypatch):
    _clear_openai_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("FRONTEND_ORIGIN=https://regulens.example/\n", encoding="utf-8")

    settings = load_settings(env_file)

    assert settings.frontend_origins == (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://regulens.example",
    )


def test_frontend_origin_rejects_paths(tmp_path, monkeypatch):
    _clear_openai_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("FRONTEND_ORIGIN=https://regulens.example/app\n", encoding="utf-8")

    try:
        load_settings(env_file)
    except ValueError as error:
        assert "without paths" in str(error)
    else:
        raise AssertionError("Expected an invalid CORS origin to fail configuration")


def test_supabase_configuration_loads_without_logging_credentials(tmp_path, monkeypatch, caplog):
    _clear_openai_environment(monkeypatch)
    service_secret = "service-secret-that-must-not-appear"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SUPABASE_URL=https://project.supabase.co\n"
        "SUPABASE_PUBLISHABLE_KEY=publishable-test-key\n"
        f"SUPABASE_SERVICE_ROLE_KEY={service_secret}\n",
        encoding="utf-8",
    )

    settings = load_settings(env_file)

    assert settings.supabase_configured is True
    with caplog.at_level(logging.INFO):
        log_openai_configuration(settings)
    assert "Supabase: configured" in caplog.text
    assert service_secret not in caplog.text
    assert "publishable-test-key" not in caplog.text
