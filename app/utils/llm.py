"""
Fábrica centralizada de instâncias LLM (ChatGoogleGenerativeAI).

Evita duplicação de ``_get_llm()`` / ``_build_llm()`` espalhada
por nodes e graphs. Cada chamada cria uma instância nova (stateless),
usando o modelo e api_key de ``settings``.
"""

from __future__ import annotations

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings
from app.constants import (
    LLM_TEMPERATURE_ANALYSIS,
    LLM_TEMPERATURE_CHAT,
    LLM_TEMPERATURE_DETERMINISTIC,
    LLM_TEMPERATURE_STRIDE,
)


def create_analysis_llm(
    *,
    temperature: float = LLM_TEMPERATURE_ANALYSIS,
    streaming: bool = False,
) -> ChatGoogleGenerativeAI:
    """LLM para nós de análise (component_mapper, vision_fallback)."""
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=temperature,
        streaming=streaming,
    )


def create_stride_llm(
    *,
    temperature: float = LLM_TEMPERATURE_STRIDE,
    streaming: bool = False,
) -> ChatGoogleGenerativeAI:
    """LLM para o nó STRIDE (analyze_stride)."""
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=temperature,
        streaming=streaming,
    )


def create_validator_llm(
    *,
    temperature: float = LLM_TEMPERATURE_DETERMINISTIC,
) -> ChatGoogleGenerativeAI:
    """LLM econômico para validação de diagrama (sem streaming)."""
    return ChatGoogleGenerativeAI(
        model=settings.gemini_validator_model,
        google_api_key=settings.gemini_api_key,
        temperature=temperature,
        streaming=False,
    )


def create_chat_llm(
    *,
    temperature: float = LLM_TEMPERATURE_CHAT,
    streaming: bool = True,
) -> ChatGoogleGenerativeAI:
    """LLM para chats (chat_graph, report_chat_graph)."""
    return ChatGoogleGenerativeAI(
        model=settings.gemini_chat_model,
        google_api_key=settings.gemini_api_key,
        temperature=temperature,
        streaming=streaming,
    )
