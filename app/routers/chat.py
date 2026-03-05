"""
Router do chat agêntico STRIDE.

Endpoints:
  GET  /chat/                → página do chat
  POST /chat/message/stream  → SSE streaming (tokens individuais + tool use)
  POST /chat/sessions        → lista sessões (histórico do MemorySaver)
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.constants import TEMPLATES_DIRECTORY
from app.graphs.chat_graph import chat_graph
from app.utils.sse import create_sse_response, format_sse, sse_done

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])
templates = Jinja2Templates(directory=TEMPLATES_DIRECTORY)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ChatStreamRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    """Página do chat com o assistente Gemini especialista em STRIDE."""
    return templates.TemplateResponse("chat.html", {"request": request})


@router.post("/message/stream")
async def chat_stream(body: ChatStreamRequest) -> StreamingResponse:
    """
    Envia mensagem ao agente ReAct e faz streaming dos tokens via SSE.

    Tipos de evento:
      {"type": "token",    "content": "..."}   ← fragmento de resposta
      {"type": "tool_use", "name": "..."}       ← agente usando uma ferramenta
      {"type": "tool_result", "name": "...", "result": "..."}
      {"type": "error",    "message": "..."}
    """

    async def token_generator():
        config = {"configurable": {"thread_id": body.session_id}}
        try:
            async for event in chat_graph.astream_events(
                {"messages": [HumanMessage(content=body.message)]},
                config=config,
                version="v2",
            ):
                event_type = event.get("event", "")
                name = event.get("name", "")

                if event_type == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        content = chunk.content
                        if isinstance(content, str):
                            yield format_sse({"type": "token", "content": content})
                        elif isinstance(content, list):
                            # Gemini pode retornar lista de parts
                            for part in content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    yield format_sse({"type": "token", "content": part["text"]})

                elif event_type == "on_tool_start":
                    tool_name = name.replace("_", " ").title()
                    yield format_sse({"type": "tool_use", "name": tool_name})

                elif event_type == "on_tool_end":
                    output = event["data"].get("output", "")
                    tool_name = name.replace("_", " ").title()
                    yield format_sse({"type": "tool_result", "name": tool_name, "result": str(output)[:500]})

        except Exception as exc:
            logger.error("Erro no chat stream: %s", exc, exc_info=True)
            yield format_sse({"type": "error", "message": str(exc)})

        yield sse_done()

    return create_sse_response(token_generator())
