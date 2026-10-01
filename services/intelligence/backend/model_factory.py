"""
model_factory.py — LLM · 임베딩 프로바이더 팩토리

.env 설정:
    LLM_PROVIDER   = ollama | openrouter | openai | anthropic | google  (기본: ollama)
    CHAT_LLM_PROVIDER = 빈 값이면 LLM_PROVIDER, 챗봇만 전환할 때 openrouter
    APPRAISAL_INTENT_LLM_PROVIDER = 빈 값이면 LLM_PROVIDER, 시세추정 주소·유형 추출만 전환
    EMBED_PROVIDER = ollama | openai | google              (기본: LLM_PROVIDER, 임베딩 미지원이면 ollama)

지원 프로바이더별 필요 패키지:
    ollama    → langchain-ollama (기본 설치)
    openrouter/openai → langchain-openai
    anthropic → pip install langchain-anthropic  (임베딩 미지원 → EMBED_PROVIDER 별도 설정)
    google    → pip install langchain-google-genai
"""

from __future__ import annotations

import os
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

LLM_PROVIDER   = os.getenv("LLM_PROVIDER",   "ollama").lower().strip()
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER",  "").lower().strip()

# 임베딩 모델을 바꾸면 기존 벡터를 다시 적재해야 하므로, 생성 모델만 바꿀 때는 Ollama를 유지한다.
if not EMBED_PROVIDER:
    EMBED_PROVIDER = "ollama" if LLM_PROVIDER in {"anthropic", "openrouter"} else LLM_PROVIDER


def _openrouter_llm(*, json_mode: bool = False, max_tokens: int | None = None):
    """OpenRouter의 OpenAI 호환 엔드포인트를 LangChain 호출 계약으로 연결한다."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("OPENROUTER_MODEL", "").strip()
    if not api_key or not model:
        raise RuntimeError("OpenRouter 사용에는 OPENROUTER_API_KEY와 OPENROUTER_MODEL이 모두 필요합니다")
    # 일반 유료 모델은 계속 차단하고, 사용자가 지정한 GPT-6 Luna만 과금 예외로 허용한다.
    if model != "openai/gpt-6-luna" and model != "openrouter/free" and not model.endswith(":free"):
        raise ValueError("OPENROUTER_MODEL은 openai/gpt-6-luna 또는 무료 모델만 사용할 수 있습니다")
    from langchain_openai import ChatOpenAI
    headers = {}
    if os.getenv("OPENROUTER_SITE_URL"):
        headers["HTTP-Referer"] = os.environ["OPENROUTER_SITE_URL"]
    if os.getenv("OPENROUTER_APP_TITLE"):
        headers["X-OpenRouter-Title"] = os.environ["OPENROUTER_APP_TITLE"]
    return ChatOpenAI(
        model=model, api_key=api_key, base_url="https://openrouter.ai/api/v1",
        temperature=0, timeout=90, max_retries=1, max_tokens=max_tokens,
        default_headers=headers or None,
        extra_body={"reasoning": {"enabled": False}},
        model_kwargs={"response_format": {"type": "json_object"}} if json_mode else {},
    )


# ─────────────────────────────────────────
#  LLM 팩토리
# ─────────────────────────────────────────

def get_llm():
    """일반 텍스트 출력 LLM"""
    if LLM_PROVIDER == "openrouter":
        return _openrouter_llm()
    if LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "qwen3.5:9b"),
            base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            temperature=0.0,
            # 모델 기본값에 맡기면 내부 추론으로 응답 대기가 길어질 수 있다.
            reasoning=False,
        )

    if LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            api_key=os.getenv("OPENAI_API_KEY"),
            temperature=0.0,
        )

    if LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7"),
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=0.0,
            max_tokens=4096,
        )

    if LLM_PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=os.getenv("GOOGLE_MODEL", "gemini-2.0-flash"),
            google_api_key=os.getenv("GOOGLE_GENERATIVE_AI_API_KEY"),
            temperature=0.0,
        )

    raise ValueError(f"[model_factory] 지원하지 않는 LLM_PROVIDER: '{LLM_PROVIDER}'"
                     " (ollama | openrouter | openai | anthropic | google)")


def get_llm_json():
    """JSON 출력 전용 LLM (프로바이더별 네이티브 JSON 모드 사용)"""
    if LLM_PROVIDER == "openrouter":
        return _openrouter_llm(json_mode=True)
    if LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "qwen3.5:9b"),
            base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            temperature=0.0,
            format="json",
            reasoning=False,
        )

    if LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            api_key=os.getenv("OPENAI_API_KEY"),
            temperature=0.0,
            model_kwargs={"response_format": {"type": "json_object"}},
        )

    if LLM_PROVIDER == "anthropic":
        # Anthropic은 네이티브 JSON 모드 없음 → 프롬프트 기반 JSON 유도
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7"),
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=0.0,
            max_tokens=4096,
        )

    if LLM_PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=os.getenv("GOOGLE_MODEL", "gemini-2.0-flash"),
            google_api_key=os.getenv("GOOGLE_GENERATIVE_AI_API_KEY"),
            temperature=0.0,
            generation_config={"response_mime_type": "application/json"},
        )

    raise ValueError(f"[model_factory] 지원하지 않는 LLM_PROVIDER: '{LLM_PROVIDER}'")


# ─────────────────────────────────────────
#  임베딩 팩토리
# ─────────────────────────────────────────

def get_embeddings():
    """벡터 임베딩 모델 (RAG용)"""
    if EMBED_PROVIDER == "ollama":
        from langchain_ollama import OllamaEmbeddings
        return OllamaEmbeddings(
            model=os.getenv("OLLAMA_EMBED_MODEL", "mxbai-embed-large"),
            base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        )

    if EMBED_PROVIDER == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
            api_key=os.getenv("OPENAI_API_KEY"),
        )

    if EMBED_PROVIDER == "google":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        return GoogleGenerativeAIEmbeddings(
            model=os.getenv("GOOGLE_EMBED_MODEL", "models/text-embedding-004"),
            google_api_key=os.getenv("GOOGLE_GENERATIVE_AI_API_KEY"),
        )

    raise ValueError(f"[model_factory] 지원하지 않는 EMBED_PROVIDER: '{EMBED_PROVIDER}'"
                     " (ollama | openai | google)")


def get_chat_llm(*, json_mode=False):
    """공통 추론 비활성화에 더해 대화 경로의 출력 길이와 대기 시간을 제한한다."""
    chat_provider = os.getenv("CHAT_LLM_PROVIDER", "").lower().strip() or LLM_PROVIDER
    if chat_provider == "openrouter":
        return _openrouter_llm(json_mode=json_mode, max_tokens=256 if json_mode else 768)
    if chat_provider != LLM_PROVIDER:
        raise ValueError("CHAT_LLM_PROVIDER는 현재 openrouter 또는 LLM_PROVIDER만 지원합니다")
    llm = get_llm_json() if json_mode else get_llm()
    from langchain_ollama import ChatOllama
    if isinstance(llm, ChatOllama):
        return ChatOllama(model=llm.model, base_url=llm.base_url, temperature=0,
            format="json" if json_mode else "", reasoning=False, num_ctx=16384,
            num_predict=256 if json_mode else 768, client_kwargs={"timeout": 90})
    return llm


def get_appraisal_intent_llm():
    """시세추정의 주소·유형 자연어 추출용 JSON 모델. 좌표 조회 자체는 주소 API가 수행한다."""
    provider = os.getenv("APPRAISAL_INTENT_LLM_PROVIDER", "").lower().strip() or LLM_PROVIDER
    if provider == "openrouter":
        # 이 단계는 필드가 많아 챗봇의 짧은 도구 선택 제한보다 큰 출력 한도가 필요하다.
        return _openrouter_llm(json_mode=True, max_tokens=1024)
    if provider != LLM_PROVIDER:
        raise ValueError("APPRAISAL_INTENT_LLM_PROVIDER는 현재 openrouter 또는 LLM_PROVIDER만 지원합니다")
    return get_llm_json()


def print_config():
    model_name = {
        "ollama":    os.getenv("OLLAMA_MODEL",    "qwen3.5:9b"),
        "openrouter": os.getenv("OPENROUTER_MODEL", "미설정"),
        "openai":    os.getenv("OPENAI_MODEL",    "gpt-4o"),
        "anthropic": os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7"),
        "google":    os.getenv("GOOGLE_MODEL",    "gemini-3.5-flash"),
    }.get(LLM_PROVIDER, "?")

    embed_name = {
        "ollama": os.getenv("OLLAMA_EMBED_MODEL", "mxbai-embed-large"),
        "openai": os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        "google": os.getenv("GOOGLE_EMBED_MODEL", "models/text-embedding-004"),
    }.get(EMBED_PROVIDER, "?")

    print(f"[model_factory] LLM   : {LLM_PROVIDER} / {model_name}")
    print(f"[model_factory] Chat  : {os.getenv('CHAT_LLM_PROVIDER') or LLM_PROVIDER}")
    print(f"[model_factory] Intent: {os.getenv('APPRAISAL_INTENT_LLM_PROVIDER') or LLM_PROVIDER}")
    print(f"[model_factory] Embed : {EMBED_PROVIDER} / {embed_name}")
