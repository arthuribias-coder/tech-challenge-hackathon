"""
Aplicação FastAPI — STRIDE Threat Modeler
Modelagem de ameaças com IA a partir de diagramas de arquitetura de software.
"""

import logging
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.constants import APP_VERSION, TEMPLATES_DIRECTORY
from app.routers import analysis, report_chat, status, training
import app.utils.log_buffer as _log_buf

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Suprime FutureWarning do google.api_core sobre Python < 3.10
# (warning informativo sem impacto funcional; remover ao migrar para Python 3.10+)
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core")

# Instala o handler de buffer de logs para exibição em /status
_log_buf.install(level=logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    logger.info("STRIDE Threat Modeler iniciado. Debug=%s", settings.debug)
    yield
    logger.info("Aplicação encerrada.")


app = FastAPI(
    title="STRIDE Threat Modeler",
    description=(
        "MVP de Modelagem de Ameaças com Inteligência Artificial. "
        "Analisa diagramas de arquitetura de software e gera relatórios de ameaças "
        "seguindo a metodologia STRIDE."
    ),
    version=APP_VERSION,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

app.include_router(analysis.router)
app.include_router(report_chat.router)
app.include_router(training.router)
app.include_router(status.router)

templates = Jinja2Templates(directory=TEMPLATES_DIRECTORY)


@app.get("/", response_class=HTMLResponse)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/analysis/")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION}
