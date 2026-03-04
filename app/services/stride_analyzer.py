"""
Serviço de análise de ameaças usando a metodologia STRIDE.
Gera ameaças para cada componente identificado no diagrama de arquitetura.
"""

import json
import logging

from google import genai
from google.genai import types

from app.config import settings
from app.models.schemas import ArchitectureComponent, Threat

logger = logging.getLogger(__name__)

_STRIDE_ANALYSIS_PROMPT = """
Você é um especialista em segurança de sistemas e modelagem de ameaças (Threat Modeling).
Utilize a metodologia STRIDE para analisar os componentes de arquitetura fornecidos e identificar ameaças.

Metodologia STRIDE:
- Spoofing: Falsificação de identidade de usuários ou componentes
- Tampering: Adulteração de dados em trânsito ou em repouso
- Repudiation: Negação de ter realizado uma ação (falta de auditoria)
- Information Disclosure: Exposição indevida de informações confidenciais
- Denial of Service: Tornar um serviço indisponível
- Elevation of Privilege: Obter acesso não autorizado a recursos privilegiados

Componentes da arquitetura:
{components_json}

Para cada ameaça identificada, retorne um JSON no seguinte formato:
{{
  "threats": [
    {{
      "stride_category": "<uma das 6 categorias STRIDE exatas>",
      "title": "Título curto e descritivo da ameaça",
      "description": "Descrição detalhada de como esta ameaça pode se concretizar neste componente",
      "affected_component": "Nome exato do componente afetado",
      "severity": "Alta | Média | Baixa",
      "countermeasures": [
        "Contramedida específica 1",
        "Contramedida específica 2",
        "Contramedida específica 3"
      ]
    }}
  ],
  "summary": "Resumo executivo da análise de ameaças (2-3 parágrafos)"
}}

Seja abrangente: identifique pelo menos uma ameaça por categoria STRIDE para os componentes mais críticos.
Retorne APENAS o JSON, sem texto adicional.
"""

_STRIDE_CATEGORIES = {
    "Spoofing",
    "Tampering",
    "Repudiation",
    "Information Disclosure",
    "Denial of Service",
    "Elevation of Privilege",
}


async def generate_stride_threats(
    components: list[ArchitectureComponent],
) -> tuple[list[Threat], str]:
    """
    Gera ameaças STRIDE para uma lista de componentes de arquitetura.
    Retorna (lista de Threat, resumo executivo).
    """
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY não configurada. Defina a variável de ambiente.")

    client = genai.Client(api_key=settings.gemini_api_key)

    components_json = json.dumps(
        [c.model_dump() for c in components],
        ensure_ascii=False,
        indent=2,
    )

    prompt = _STRIDE_ANALYSIS_PROMPT.format(components_json=components_json)

    logger.info("Gerando ameaças STRIDE para %d componentes", len(components))

    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
            max_output_tokens=4000,
        ),
    )

    raw = response.text or "{}"
    data = json.loads(raw)

    threats_data = data.get("threats", [])
    summary = data.get("summary", "")

    threats: list[Threat] = []
    for item in threats_data:
        if item.get("stride_category") not in _STRIDE_CATEGORIES:
            logger.warning("Categoria STRIDE inválida ignorada: %s", item.get("stride_category"))
            continue
        threats.append(Threat(**item))

    logger.info("Ameaças geradas: %d", len(threats))
    return threats, summary
