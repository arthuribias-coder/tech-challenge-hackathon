"""
Nó LangGraph: aplica a metodologia STRIDE sobre os componentes identificados.

Usa LangChain com saída estruturada Pydantic para garantir o schema correto
sem parsing manual de JSON.
"""

from __future__ import annotations

import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from app.config import settings
from app.models.schemas import AnalysisState, StrideCategory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output schema Pydantic
# ---------------------------------------------------------------------------


class _Threat(BaseModel):
    stride_category: StrideCategory
    title: str = Field(description="Título curto e descritivo da ameaça")
    description: str = Field(description="Como esta ameaça pode se concretizar neste componente")
    affected_component: str = Field(description="Nome exato do componente afetado")
    severity: str = Field(description="Alta | Média | Baixa")
    countermeasures: list[str] = Field(
        description="Contramedidas específicas e implementáveis (mínimo 2)"
    )


class _StrideAnalysis(BaseModel):
    threats: list[_Threat] = Field(
        description="Lista completa de ameaças identificadas (mínimo 1 por categoria STRIDE para cada componente crítico)"
    )
    summary: str = Field(description="Resumo executivo da análise (2-3 parágrafos)")


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_STRIDE_SYSTEM = (
    "Você é um especialista sênior em segurança de sistemas e modelagem de ameaças. "
    "Aplique rigorosamente a metodologia STRIDE a todos os componentes fornecidos.\n\n"
    "Categorias STRIDE:\n"
    "- Spoofing: Falsificação de identidade de usuários ou componentes\n"
    "- Tampering: Adulteração de dados em trânsito ou em repouso\n"
    "- Repudiation: Negação de ações realizadas (falta de auditoria)\n"
    "- Information Disclosure: Exposição indevida de informações confidenciais\n"
    "- Denial of Service: Tornar serviços indisponíveis\n"
    "- Elevation of Privilege: Obter acesso não autorizado a recursos privilegiados\n\n"
    "Seja abrangente: identifique ao menos uma ameaça por categoria para os componentes mais críticos. "
    "Sugira contramedidas concretas e implementáveis."
)

_STRIDE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _STRIDE_SYSTEM),
    (
        "human",
        (
            "Componentes da arquitetura:\n{components_json}\n\n"
            "Observações adicionais: {notes}\n\n"
            "Gere o relatório completo de ameaças STRIDE."
        ),
    ),
])


def _get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.3,
    )


async def analyze_stride_node(state: AnalysisState) -> dict:
    """
    Nó LangGraph: gera ameaças STRIDE para os componentes identificados.
    Filtra categorias inválidas via enum antes de persistir.
    """
    components = state.get("components", [])
    if not components:
        logger.warning("[analyze_stride] Nenhum componente disponível — pulando STRIDE")
        return {
            "threats": [],
            "summary": "Não foi possível identificar componentes para análise STRIDE.",
            "step": "stride_skipped",
        }

    logger.info("[analyze_stride] Analisando %d componentes", len(components))

    try:
        llm = _get_llm()
        chain = _STRIDE_PROMPT | llm.with_structured_output(_StrideAnalysis)

        components_json = json.dumps(components, ensure_ascii=False, indent=2)
        result: _StrideAnalysis = await chain.ainvoke(
            {
                "components_json": components_json,
                "notes": state.get("notes") or "(sem observações adicionais)",
            }
        )

        # Serializa para dict — StrideCategory enum → valor string
        threats = [t.model_dump(mode="json") for t in result.threats]
        logger.info("[analyze_stride] %d ameaças identificadas", len(threats))

        return {
            "threats": threats,
            "summary": result.summary,
            "step": "stride_done",
        }

    except Exception as exc:
        logger.error("[analyze_stride] Erro: %s", exc, exc_info=True)
        return {
            "threats": [],
            "summary": "",
            "step": "stride_failed",
            "error": str(exc),
        }
