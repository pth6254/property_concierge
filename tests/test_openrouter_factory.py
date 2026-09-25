"""챗봇만 OpenRouter로 전환해도 임베딩·다른 생성 경로의 설정은 유지된다."""
from types import SimpleNamespace
import sys

import pytest

from backend import model_factory


def test_openrouter_chat_requires_key_and_model(monkeypatch):
    monkeypatch.setenv("CHAT_LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY.*OPENROUTER_MODEL"):
        model_factory.get_chat_llm()


def test_openrouter_chat_uses_json_mode_and_keeps_global_provider(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(
        ChatOpenAI=lambda **kwargs: calls.append(kwargs) or kwargs))
    monkeypatch.setenv("CHAT_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/free")
    monkeypatch.setenv("OPENROUTER_SITE_URL", "https://example.com")
    monkeypatch.setattr(model_factory, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(model_factory, "EMBED_PROVIDER", "ollama")

    plain = model_factory.get_chat_llm()
    structured = model_factory.get_chat_llm(json_mode=True)

    assert plain["base_url"] == "https://openrouter.ai/api/v1"
    assert plain["api_key"] == "test-key"
    assert plain["max_tokens"] == 768
    assert plain["default_headers"]["HTTP-Referer"] == "https://example.com"
    assert structured["model_kwargs"]["response_format"] == {"type": "json_object"}
    assert structured["max_tokens"] == 256
    assert model_factory.LLM_PROVIDER == model_factory.EMBED_PROVIDER == "ollama"
    assert len(calls) == 2


def test_openrouter_real_client_constructs_without_network(monkeypatch):
    pytest.importorskip("langchain_openai")
    monkeypatch.setenv("CHAT_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/free")
    llm = model_factory.get_chat_llm(json_mode=True)
    assert llm.model_name == "openrouter/free"
    assert str(llm.openai_api_base).rstrip("/") == "https://openrouter.ai/api/v1"


def test_openrouter_rejects_paid_model_before_request(monkeypatch):
    monkeypatch.setenv("CHAT_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    with pytest.raises(ValueError, match="free"):
        model_factory.get_chat_llm()


def test_appraisal_address_intent_uses_free_openrouter_json_model(monkeypatch):
    from backend import intent_agent

    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(ChatOpenAI=lambda **kwargs: kwargs))
    monkeypatch.setenv("APPRAISAL_INTENT_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/free")
    llm = intent_agent.get_llm()
    assert llm["model"] == "openrouter/free"
    assert llm["max_tokens"] == 1024
    assert llm["model_kwargs"]["response_format"] == {"type": "json_object"}
