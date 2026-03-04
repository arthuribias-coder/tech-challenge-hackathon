"""
Serviço de análise de diagramas de arquitetura usando Google Gemini Vision.
Responsável por identificar os componentes da arquitetura a partir de uma imagem.
"""

import json
import logging
from pathlib import Path

from google import genai
from google.genai import types

from app.config import settings
from app.models.schemas import ArchitectureComponent

logger = logging.getLogger(__name__)

_COMPONENT_EXTRACTION_PROMPT = """
Você é um especialista em arquitetura de software e segurança de sistemas.
Analise o diagrama de arquitetura de software fornecido e identifique TODOS os componentes presentes.

Para cada componente identificado, retorne um JSON no seguinte formato:
{
  "components": [
    {
      "name": "Nome do componente",
      "component_type": "Tipo (ex: usuário, servidor web, banco de dados, API, serviço externo, firewall, balanceador de carga, fila de mensagens, cache, etc.)",
      "description": "Descrição breve do papel deste componente na arquitetura"
    }
  ]
}

Seja detalhado e identifique todos os elementos visíveis, incluindo conexões, fluxos de dados,
zonas de confiança (trust boundaries), protocolos e qualquer elemento relevante de segurança.
Retorne APENAS o JSON, sem texto adicional.
"""


def _get_image_mime_type(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return mime_types.get(suffix, "image/png")


async def extract_components(image_path: Path) -> list[ArchitectureComponent]:
    """
    Usa o Google Gemini Vision para identificar componentes de um diagrama de arquitetura.
    Retorna uma lista de ArchitectureComponent.
    """
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY não configurada. Defina a variável de ambiente.")

    client = genai.Client(api_key=settings.gemini_api_key)

    image_bytes = image_path.read_bytes()
    mime_type = _get_image_mime_type(image_path)

    logger.info("Enviando imagem para análise de componentes: %s", image_path.name)

    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=[_COMPONENT_EXTRACTION_PROMPT, image_part],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )

    raw = response.text or "{}"
    data = json.loads(raw)

    components = [ArchitectureComponent(**item) for item in data.get("components", [])]
    logger.info("Componentes identificados: %d", len(components))
    return components
