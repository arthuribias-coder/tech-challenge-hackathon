"""
Constantes compartilhadas do projeto STRIDE Threat Modeler.

Centraliza valores que antes estavam hardcoded em múltiplos arquivos,
facilitando manutenção e consistência.
"""

from __future__ import annotations

from importlib.metadata import version as pkg_version

# ---------------------------------------------------------------------------
# Versão da aplicação (fonte única: pyproject.toml)
# ---------------------------------------------------------------------------

try:
    APP_VERSION: str = pkg_version("stride-threat-modeler")
except Exception:
    APP_VERSION = "0.1.0"  # fallback para dev sem instalação

# ---------------------------------------------------------------------------
# Upload — tipos MIME aceitos e extensões
# ---------------------------------------------------------------------------

ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
})

MIME_TO_EXTENSION: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

EXTENSION_TO_MIME: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

DEFAULT_MIME_TYPE: str = "image/png"

# ---------------------------------------------------------------------------
# SSE (Server-Sent Events)
# ---------------------------------------------------------------------------

SSE_DONE_SENTINEL: str = "data: [DONE]\n\n"

SSE_RESPONSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

SSE_MEDIA_TYPE: str = "text/event-stream"

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

TEMPLATES_DIRECTORY: str = "app/templates"

# ---------------------------------------------------------------------------
# YOLO / OpenCV — detecção visual
# ---------------------------------------------------------------------------

YOLO_MODEL_PATH: str = "yolov8s-world.pt"
YOLO_CONFIDENCE_THRESHOLD: float = 0.25
OCR_CONFIDENCE_THRESHOLD: float = 0.3
SHAPE_MIN_AREA_RATIO: float = 0.002
MAX_DETECTED_SHAPES: int = 40
TEXT_ASSOCIATION_MAX_DISTANCE_PX: int = 300

# Validação de diagrama — Gemini
# ---------------------------------------------------------------------------

# Confiança mínima para aceitar a classificação do LLM validador
VALIDATOR_GEMINI_MIN_CONFIDENCE: float = 0.55

DIAGRAM_CLASSES: list[str] = [
    "web server", "application server", "database", "cache",
    "message queue", "load balancer", "firewall", "api gateway",
    "user", "browser", "mobile app", "cloud storage", "cdn",
    "microservice", "container", "kubernetes", "vpn", "proxy",
    "sdk", "external service", "iot device", "email server",
]

# ---------------------------------------------------------------------------
# LLM — temperaturas padrão por finalidade
# ---------------------------------------------------------------------------

LLM_TEMPERATURE_DETERMINISTIC: float = 0.0
LLM_TEMPERATURE_ANALYSIS: float = 0.1
LLM_TEMPERATURE_STRIDE: float = 0.3
LLM_TEMPERATURE_CHAT: float = 0.7
