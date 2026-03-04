"""
Router de análise de ameaças STRIDE.

Endpoints:
  GET  /analysis/                    → formulário de upload
  POST /analysis/upload              → salva imagem, retorna upload_id
  GET  /analysis/stream/{upload_id}  → pipeline LangGraph + SSE streaming
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.graphs.analysis_graph import NODE_LABELS, analysis_graph
from app.models.schemas import AnalysisState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])
templates = Jinja2Templates(directory="app/templates")

_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _initial_state(image_path: Path, notes: str, mime_type: str) -> AnalysisState:
    return AnalysisState(
        image_path=str(image_path),
        notes=notes,
        mime_type=mime_type,
        detections=[],
        has_yolo_detections=False,
        components=[],
        threats=[],
        summary="",
        report={},
        step="start",
        error=None,
    )


def _sse(payload: dict) -> str:
    """Formata um payload como evento SSE."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _save_upload(diagram: UploadFile) -> tuple[Path, str]:
    """Persiste o arquivo enviado e retorna (path, mime_type)."""
    content = await diagram.read()
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Arquivo muito grande. Máximo: {settings.max_upload_size_mb}MB.",
        )

    mime = diagram.content_type or "image/png"
    ext = _MIME_TO_EXT.get(mime, Path(diagram.filename or "img.png").suffix or ".png")
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = upload_dir / filename

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    logger.info("Upload salvo: %s (%s bytes)", file_path, len(content))
    return file_path, mime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def analysis_form(request: Request) -> HTMLResponse:
    """Página principal com formulário de upload e legenda STRIDE."""
    return templates.TemplateResponse("index.html", {"request": request})


@router.post("/upload")
async def upload_diagram(
    diagram: UploadFile = File(..., description="Imagem do diagrama de arquitetura"),
    notes: str = Form(default=""),
) -> JSONResponse:
    """
    Salva o arquivo e retorna {upload_id, image_filename, notes, mime_type}.
    O frontend conecta ao SSE stream usando o upload_id retornado.
    """
    if diagram.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Tipo não suportado: {diagram.content_type}. Use JPEG, PNG, GIF ou WebP.",
        )

    file_path, mime = await _save_upload(diagram)
    upload_id = file_path.stem  # uuid sem extensão

    return JSONResponse({
        "upload_id": upload_id,
        "image_filename": file_path.name,
        "notes": notes,
        "mime_type": mime,
    })


@router.get("/stream/{upload_id}")
async def analysis_stream(
    upload_id: str,
    notes: str = "",
    mime_type: str = "image/png",
) -> StreamingResponse:
    """
    Executa o pipeline LangGraph e emite eventos SSE com progresso em tempo real.

    Eventos:
      {"type": "progress", "node": "...", "label": "...", "step": "..."}
      {"type": "complete", "report": {...}, "image_filename": "..."}
      {"type": "error",    "message": "..."}
    """
    upload_dir = Path(settings.upload_dir)
    matches = list(upload_dir.glob(f"{upload_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"Upload '{upload_id}' não encontrado.")

    image_path = matches[0]
    image_filename = image_path.name

    async def event_generator():
        initial_state = _initial_state(image_path, notes, mime_type)

        try:
            async for update in analysis_graph.astream(
                initial_state, stream_mode="updates"
            ):
                for node_name, node_output in update.items():
                    label = NODE_LABELS.get(node_name, node_name)
                    step = node_output.get("step", node_name)

                    yield _sse({"type": "progress", "node": node_name, "label": label, "step": step})

                    if node_name == "compile_report" and node_output.get("report"):
                        yield _sse({
                            "type": "complete",
                            "report": node_output["report"],
                            "image_filename": image_filename,
                        })

                    if node_output.get("error") and not node_output.get("report"):
                        logger.warning("Nó '%s' reportou erro: %s", node_name, node_output["error"])

        except Exception as exc:
            logger.error("Erro no pipeline de análise: %s", exc, exc_info=True)
            yield _sse({"type": "error", "message": str(exc)})

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
