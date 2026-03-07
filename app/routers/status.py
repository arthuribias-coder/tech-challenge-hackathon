"""
Router de Status — página de monitoramento e logs em tempo real.

Endpoints:
  GET /status/              → Interface web de status e logs
  GET /status/logs/stream   → SSE: stream de logs em tempo real
  GET /status/logs          → JSON: últimas N entradas do buffer
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.constants import APP_VERSION, TEMPLATES_DIRECTORY
from app.utils.log_buffer import log_buffer

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=TEMPLATES_DIRECTORY)

router = APIRouter(prefix="/status", tags=["status"])

_SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@router.get("/", response_class=HTMLResponse)
async def status_page(request: Request):
    """Página de status e logs da aplicação."""
    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "version": APP_VERSION,
            "debug": settings.debug,
        },
    )


@router.get("/logs")
async def get_logs(n: int = 200):
    """Retorna as últimas N entradas do buffer de log em JSON."""
    return {"entries": [e.to_dict() for e in log_buffer.recent(n)]}


@router.get("/logs/stream")
async def stream_logs():
    """SSE: emite cada nova entrada de log conforme ela ocorre."""

    async def _generate():
        # Envia o backlog imediatamente ao conectar
        for entry in log_buffer.recent(200):
            yield f"data: {json.dumps(entry.to_dict(), ensure_ascii=False)}\n\n"

        # Stream de novos logs via pub/sub
        async for entry in log_buffer.stream():
            yield f"data: {json.dumps(entry.to_dict(), ensure_ascii=False)}\n\n"

    return StreamingResponse(_generate(), headers=_SSE_HEADERS)
