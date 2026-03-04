import logging
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from google.genai.errors import ClientError, ServerError

from app.config import settings
from app.services.report_generator import generate_threat_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])
templates = Jinja2Templates(directory="app/templates")

_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


@router.get("/", response_class=HTMLResponse)
async def analysis_form(request: Request) -> HTMLResponse:
    """Página principal com o formulário de upload."""
    return templates.TemplateResponse("index.html", {"request": request})


@router.post("/", response_class=HTMLResponse)
async def run_analysis(
    request: Request,
    diagram: UploadFile = File(..., description="Imagem do diagrama de arquitetura"),
    notes: str = Form(default=""),
) -> HTMLResponse:
    """
    Recebe o upload do diagrama, executa a análise e exibe o relatório STRIDE.
    """
    if diagram.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Tipo de arquivo não suportado: {diagram.content_type}. Use JPEG, PNG, GIF ou WebP.",
        )

    content = await diagram.read()
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Arquivo muito grande. Tamanho máximo: {settings.max_upload_size_mb}MB.",
        )

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(diagram.filename or "diagram.png").suffix
    filename = f"{uuid.uuid4().hex}{suffix}"
    file_path = upload_dir / filename

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    logger.info("Arquivo salvo em: %s", file_path)

    try:
        report = await generate_threat_report(file_path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ClientError as exc:
        http_status = exc.status_code or 400
        if http_status == 429:
            detail = "Cota da API Gemini esgotada ou limite de requisições atingido. Tente novamente em alguns instantes."
        elif http_status in (401, 403):
            detail = "Chave de API Gemini inválida ou sem permissão. Verifique a variável GEMINI_API_KEY."
        else:
            detail = f"Erro da API Gemini: {exc}"
        raise HTTPException(status_code=http_status, detail=detail) from exc
    except ServerError as exc:
        logger.error("Erro no servidor Gemini: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="O servidor da API Gemini retornou um erro. Tente novamente.",
        ) from exc
    except Exception as exc:
        logger.exception("Erro durante a análise: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao processar a análise. Tente novamente.",
        ) from exc

    severity_order = {"Alta": 0, "Média": 1, "Baixa": 2}
    sorted_threats = sorted(report.threats, key=lambda t: severity_order.get(t.severity, 99))

    return templates.TemplateResponse(
        "report.html",
        {
            "request": request,
            "report": report,
            "threats": sorted_threats,
            "image_filename": filename,
            "original_filename": diagram.filename,
        },
    )
