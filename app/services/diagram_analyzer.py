"""
Serviço de análise de diagramas de arquitetura usando OpenAI Vision.
Responsável por identificar os componentes da arquitetura a partir de uma imagem.
"""

import base64
import json
import logging
from pathlib import Path

from openai import AsyncOpenAI

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


def _encode_image_to_base64(image_path: Path) -> str:
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _get_image_media_type(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return media_types.get(suffix, "image/png")


async def extract_components(image_path: Path) -> list[ArchitectureComponent]:
    """
    Usa a OpenAI Vision API para identificar os componentes de um diagrama de arquitetura.
    Retorna uma lista de ArchitectureComponent.
    """
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY não configurada. Defina a variável de ambiente.")

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    image_data = _encode_image_to_base64(image_path)
    media_type = _get_image_media_type(image_path)

    logger.info("Enviando imagem para análise de componentes: %s", image_path.name)

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _COMPONENT_EXTRACTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_data}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        max_tokens=2000,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)

    components = [ArchitectureComponent(**item) for item in data.get("components", [])]
    logger.info("Componentes identificados: %d", len(components))
    return components
