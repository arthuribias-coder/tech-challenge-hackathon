"""
Router do chat contextual de relatório STRIDE.

Endpoints:
  POST /analysis/{upload_id}/chat/stream  → SSE streaming com contexto da análise
  GET  /analysis/{upload_id}/chat/ping    → Verifica se o relatório existe (contexto disponível)
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.graphs.report_chat_graph import report_chat_graph
from app.utils.sse import create_sse_response, format_sse, sse_done

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["report-chat"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ReportChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_report_context(upload_id: str) -> dict:
    """Carrega o JSON do relatório salvo em disco. Lança 404 se não encontrado."""
    report_json = Path(settings.upload_dir) / f"{upload_id}.report.json"
    if not report_json.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Relatório '{upload_id}' não encontrado. "
                "A análise pode ainda não ter sido concluída."
            ),
        )
    try:
        return json.loads(report_json.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Erro ao ler relatório %s: %s", upload_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao carregar o contexto do relatório.",
        ) from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{upload_id}/chat/ping")
async def report_chat_ping(upload_id: str) -> JSONResponse:
    """
    Verifica se o relatório de um upload existe e o chat contextual está disponível.
    Usado pelo frontend para habilitar/desabilitar o botão de chat.
    """
    report_json = Path(settings.upload_dir) / f"{upload_id}.report.json"
    if not report_json.exists():
        return JSONResponse({"available": False})

    try:
        context = json.loads(report_json.read_text(encoding="utf-8"))
        report = context.get("report", {})
        return JSONResponse({
            "available": True,
            "image_filename": context.get("image_filename", ""),
            "threat_count": len(report.get("threats", [])),
            "component_count": len(report.get("components", [])),
        })
    except Exception:
        return JSONResponse({"available": False})


@router.post("/{upload_id}/chat/stream")
async def report_chat_stream(
    upload_id: str,
    body: ReportChatRequest,
) -> StreamingResponse:
    """
    Executa o chat contextual com guardrail e streaming SSE.

    Tipos de evento:
      {"type": "token",       "content": "..."}   ← fragmento de resposta
      {"type": "tool_use",    "name": "..."}       ← ferramenta em uso
      {"type": "tool_result", "name": "...", "result": "..."}
      {"type": "blocked",     "reason": "..."}     ← guardrail bloqueou
      {"type": "error",       "message": "..."}
    """
    # Carrega o contexto do relatório do disco
    analysis_context = _load_report_context(upload_id)

    async def token_generator():
        config = {"configurable": {"thread_id": body.session_id}}

        # Estado inicial: injeta a mensagem do usuário e o contexto
        # (analysis_context é salvo no checkpoint na 1ª vez; nas seguintes
        # o checkpointer restaura session_initialized=True e pula inject_context)
        initial_input: dict = {
            "messages": [HumanMessage(content=body.message)],
            "analysis_context": analysis_context,
            "guardrail_passed": True,    # padrão; será sobrescrito pelo nó
            "refusal_reason": "",
        }

        # Rastreia se o nó "respond" atual emitiu tokens via streaming.
        # Resetado a cada nova ativação do nó (on_chain_start).
        respond_streaming_active = False

        try:
            async for event in report_chat_graph.astream_events(
                initial_input,
                config=config,
                version="v2",
            ):
                event_type = event.get("event", "")
                name = event.get("name", "")
                metadata = event.get("metadata", {})
                lg_node = metadata.get("langgraph_node", "")

                # ── EVENTO DE DEBUG (sempre emitido para diagnóstico) ──────────
                try:
                    debug_data = event.get("data", {})
                    # Serializa apenas campos seguros (evita objetos não-serializáveis)
                    debug_payload: dict = {
                        "event": event_type,
                        "name": name,
                        "lg_node": lg_node,
                    }
                    if "chunk" in debug_data:
                        chunk = debug_data["chunk"]
                        debug_payload["chunk_content"] = (
                            chunk.content[:120] if hasattr(chunk, "content") and isinstance(chunk.content, str)
                            else str(type(chunk.content))[:60]
                        )
                        debug_payload["tool_calls"] = bool(getattr(chunk, "tool_calls", None))
                    if "output" in debug_data:
                        out = debug_data["output"]
                        if isinstance(out, dict):
                            msgs = out.get("messages", [])
                            debug_payload["output_messages"] = [
                                {
                                    "type": type(m).__name__,
                                    "content_preview": (m.content[:80] if isinstance(m.content, str) else str(type(m.content))[:60]),
                                    "tool_calls": bool(getattr(m, "tool_calls", None)),
                                }
                                for m in msgs
                            ]
                        elif hasattr(out, "content"):
                            debug_payload["output_content"] = str(out.content)[:120]
                    yield format_sse({"type": "debug", "payload": debug_payload})
                except Exception:
                    pass  # debug nunca quebra o fluxo principal

                # Reseta o flag a cada nova invocação do nó respond
                if event_type == "on_chain_start" and lg_node == "respond":
                    respond_streaming_active = False

                # Tokens de resposta: apenas do nó "respond", nunca do guardrail
                elif event_type == "on_chat_model_stream" and lg_node == "respond":
                    chunk = event["data"].get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        content = chunk.content
                        if isinstance(content, str) and content:
                            respond_streaming_active = True
                            yield format_sse({"type": "token", "content": content})
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                                    respond_streaming_active = True
                                    yield format_sse({"type": "token", "content": part["text"]})

                # Fallback: respond terminou sem emitir streaming → envia a mensagem completa
                elif event_type == "on_chain_end" and lg_node == "respond" and not respond_streaming_active:
                    output = event.get("data", {}).get("output", {})
                    messages = output.get("messages", []) if isinstance(output, dict) else []
                    for msg in messages:
                        # Ignora mensagens que são apenas tool_calls (sem texto para exibir)
                        if getattr(msg, "tool_calls", None):
                            continue
                        content = getattr(msg, "content", None)
                        if not content:
                            continue
                        if isinstance(content, str):
                            yield format_sse({"type": "token", "content": content})
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                                    yield format_sse({"type": "token", "content": part["text"]})

                # Ferramenta sendo chamada
                elif event_type == "on_tool_start":
                    tool_display = name.replace("_", " ").title()
                    yield format_sse({"type": "tool_use", "name": tool_display})

                # Resultado da ferramenta
                elif event_type == "on_tool_end":
                    output = event["data"].get("output", "")
                    tool_display = name.replace("_", " ").title()
                    yield format_sse({
                        "type": "tool_result",
                        "name": tool_display,
                        "result": str(output)[:500],
                    })

                # Detecção de bloqueio pelo guardrail
                elif event_type == "on_chain_end" and lg_node == "guardrail":
                    output = event.get("data", {}).get("output", {})
                    if isinstance(output, dict) and not output.get("guardrail_passed", True):
                        yield format_sse({
                            "type": "blocked",
                            "reason": output.get("refusal_reason", "Fora do escopo"),
                        })

        except Exception as exc:
            logger.error("Erro no chat de relatório %s: %s", upload_id, exc, exc_info=True)
            yield format_sse({"type": "error", "message": str(exc)})

        yield sse_done()

    return create_sse_response(token_generator())
