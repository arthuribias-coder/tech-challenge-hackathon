"""
Utilitários compartilhados para Server-Sent Events (SSE).

Centraliza a formatação de payloads SSE e a criação de StreamingResponse
com headers padronizados, eliminando duplicação entre routers.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

from app.constants import SSE_DONE_SENTINEL, SSE_MEDIA_TYPE, SSE_RESPONSE_HEADERS


def format_sse(payload: dict) -> str:
    """Formata um payload dict como evento SSE (``data: {...}\\n\\n``)."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sse_done() -> str:
    """Retorna o sentinel de encerramento do stream SSE."""
    return SSE_DONE_SENTINEL


def create_sse_response(event_generator: AsyncIterator[str]) -> StreamingResponse:
    """Cria uma ``StreamingResponse`` SSE com headers padronizados."""
    return StreamingResponse(
        event_generator,
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_RESPONSE_HEADERS,
    )
