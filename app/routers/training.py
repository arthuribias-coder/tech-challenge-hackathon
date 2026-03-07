"""
Router FastAPI para gerenciamento de fine-tuning YOLOv8.

Endpoints:
  GET  /training/          → Interface web
  POST /training/download  → Baixa dataset COCO-Architecture
  POST /training/start     → Inicia fine-tuning (SSE streaming)
  GET  /training/status    → Status atual
  POST /training/cancel    → Cancela treinamento
  GET  /training/models    → Lista modelos disponíveis
  POST /training/delete    → Deleta modelo
"""

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.constants import TEMPLATES_DIRECTORY
from app.services.finetuning_service import finetuning_service, training_state

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=TEMPLATES_DIRECTORY)

router = APIRouter(prefix="/training", tags=["training"])


@router.get("/", response_class=HTMLResponse)
async def training_interface(request: Request):
    """Página web de gerenciamento de fine-tuning."""
    return templates.TemplateResponse("training.html", {"request": request})


@router.post("/download")
async def prepare_dataset():
    """
    Prepara o dataset para treinamento.

    Fluxo:
      1. Se o dataset local já estiver completo, retorna imediatamente.
      2. Caso contrário, baixa os datasets do Roboflow Universe e executa o
         merge via ``scripts/merge_datasets.py`` (requer ROBOFLOW_API_KEY).
    """
    try:
        data_dir = finetuning_service.data_dir

        # 1. Dataset local já completo — retorna sem nenhum download
        if finetuning_service.use_local_dataset():
            n_train = (
                sum(1 for _ in (data_dir / "images" / "train").glob("*"))
                if (data_dir / "images" / "train").exists()
                else 0
            )
            return {
                "status": "success",
                "message": f"Dataset local pronto — {n_train} imagens de treino",
                "source": "local",
                "source_label": "Dataset mergeado local",
                "data_dir": str(data_dir),
                "n_train": n_train,
            }

        # 2. Dataset incompleto/ausente → baixar e mesclar via Roboflow Universe
        success = await finetuning_service.download_and_merge_datasets()
        if not success:
            raise HTTPException(
                status_code=400,
                detail=training_state.error or "Erro ao baixar/mesclar datasets",
            )

        n_train = (
            sum(1 for _ in (data_dir / "images" / "train").glob("*"))
            if (data_dir / "images" / "train").exists()
            else 0
        )
        return {
            "status": "success",
            "message": f"Datasets baixados e mesclados — {n_train} imagens de treino",
            "source": "merged",
            "source_label": "Roboflow Universe (mergeado)",
            "data_dir": str(data_dir),
            "n_train": n_train,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Erro no prepare dataset: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/use-demo")
async def use_demo_dataset():
    """Configura uso do dataset COCO128 embutido no ultralytics."""
    try:
        finetuning_service.use_demo_mode()
        return {"status": "success", "message": "Modo demo configurado (COCO128)", "demo": True}
    except Exception as e:
        logger.error("Erro ao configurar demo: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/checkpoint")
async def get_checkpoint_status():
    """Verifica se existe um checkpoint de treinamento anterior para retomada."""
    checkpoint = finetuning_service.get_resumable_checkpoint()
    if checkpoint:
        run_name = checkpoint.parent.parent.name  # .../runs/<run_name>/weights/last.pt
        return {
            "resumable": True,
            "checkpoint": str(checkpoint),
            "run_name": run_name,
        }
    return {"resumable": False, "checkpoint": None, "run_name": None}


@router.get("/start")
async def start_training(
    request: Request,
    epochs: int = 100,
    batch_size: int = 8,
    img_size: int = 640,
    patience: int = 20,
    workers: int = 4,
    demo: bool = False,
    resume: bool = False,
):
    """
    Inicia fine-tuning e retorna stream SSE com progresso.
    Usa GET (necessário para EventSource/SSE).

    O header ``Last-Event-ID`` indica que o browser está se reconectando
    automaticamente (comportamento padrão do EventSource). Nesse caso,
    o treinamento NÃO é reiniciado — o endpoint retorna o status atual
    ou encerra o stream se nenhum treinamento está em andamento.

    Query params:
      - epochs: Número de épocas (padrão 50)
      - batch_size: Batch size (padrão 16)
      - img_size: Tamanho imagem (padrão 640)
      - patience: Early stopping patience (padrão 20)
      - demo: Usar dataset COCO128 embutido (padrão False)
    """
    is_reconnect = request.headers.get("last-event-id") is not None

    async def event_stream() -> AsyncIterator[str]:
        """Generator SSE com progresso do treinamento."""
        # Reconexão automática do EventSource: não iniciar novo treinamento.
        # Retorna estado atual e encerra o stream para que o frontend decida.
        if is_reconnect:
            logger.info("EventSource reconectou ao /training/start — ignorando para não reiniciar treinamento.")
            current = training_state.to_dict()
            yield f"data: {json.dumps(current)}\n\n"
            return

        try:
            async for state in finetuning_service.start_finetuning(
                epochs=epochs,
                batch_size=batch_size,
                img_size=img_size,
                patience=patience,
                workers=workers,
                demo=demo,
                resume=resume,
            ):
                yield f"data: {json.dumps(state)}\n\n"
        except Exception as e:
            logger.error("Erro no stream: %s", e)
            error_state = training_state.to_dict()
            error_state["error"] = str(e)
            yield f"data: {json.dumps(error_state)}\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@router.get("/status")
async def get_training_status():
    """Retorna status atual do treinamento."""
    return finetuning_service.get_training_status()


@router.post("/cancel")
async def cancel_training():
    """Cancela treinamento em andamento."""
    return finetuning_service.cancel_training()


@router.get("/models")
async def list_models():
    """Lista modelos fine-tuned disponíveis."""
    models = finetuning_service.get_available_models()
    return {"models": models, "count": len(models)}


@router.post("/delete/{model_filename}")
async def delete_model(model_filename: str):
    """Deleta modelo fine-tuned especificado."""
    # Validar nome para evitar path traversal
    if "/" in model_filename or "\\" in model_filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")

    success = finetuning_service.delete_model(model_filename)
    if not success:
        raise HTTPException(status_code=404, detail="Modelo não encontrado")

    return {"status": "success", "message": f"Modelo {model_filename} deletado"}
