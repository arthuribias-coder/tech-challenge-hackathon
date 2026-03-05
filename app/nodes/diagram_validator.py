"""
Nó LangGraph: valida se a imagem enviada é realmente um diagrama de arquitetura
antes de iniciar o pipeline completo de análise STRIDE.

Usa Gemini Vision com um modelo econômico (configurável via GEMINI_VALIDATOR_MODEL)
para classificar a imagem com structured output Pydantic.

Critérios de um diagrama de arquitetura válido:
  - Contém representações de componentes de software/infraestrutura (servidores,
    bancos de dados, APIs, usuários, filas, gateways, etc.)
  - Mostra conexões ou fluxos entre os componentes
  - Pode incluir labels, setas, caixas, cilindros ou ícones de serviços de nuvem
  - Contexto de sistema de informação ou software (não hardware puro, não UML de
    classes sem componentes de runtime, etc.)
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.constants import DEFAULT_MIME_TYPE, VALIDATOR_GEMINI_MIN_CONFIDENCE
from app.models.schemas import AnalysisState
from app.utils.llm import create_validator_llm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema Pydantic para saída estruturada do Gemini
# ---------------------------------------------------------------------------


class _DiagramClassification(BaseModel):
    is_architecture_diagram: bool = Field(
        description=(
            "True se a imagem for um diagrama de arquitetura de software ou infraestrutura. "
            "False para tudo mais (fotos, arte, capturas de tela genéricas, documentos, etc.)."
        )
    )
    confidence: float = Field(
        description="Confiança da classificação de 0.0 a 1.0",
        ge=0.0,
        le=1.0,
    )
    detected_type: str = Field(
        description=(
            "Descrição breve do que foi detectado na imagem. "
            "Exemplos: 'diagrama de arquitetura AWS', 'fluxograma de processo', "
            "'fotografia', 'captura de tela de código', 'documento de texto', "
            "'diagrama UML de classes', 'imagem genérica'."
        )
    )
    rejection_reason: str = Field(
        default="",
        description=(
            "Explicação de por que a imagem não é um diagrama de arquitetura de software. "
            "Deixar em branco se is_architecture_diagram=True."
        ),
    )
    suggestion: str = Field(
        default="",
        description=(
            "Sugestão útil ao usuário sobre o que enviar correto. "
            "Ex: 'Envie um diagrama criado em draw.io, Lucidchart, PlantUML ou similar, "
            "mostrando componentes e suas conexões.' "
            "Deixar em branco se is_architecture_diagram=True."
        ),
    )


# ---------------------------------------------------------------------------
# Prompt de classificação
# ---------------------------------------------------------------------------

_VALIDATOR_PROMPT = (
    "Você é um especialista em diagramas de arquitetura de software e infraestrutura.\n\n"
    "Analise a imagem e determine se ela é um **diagrama de arquitetura de software "
    "ou infraestrutura**. Exemplos válidos:\n"
    "  - Diagrama de microserviços, cloud (AWS, Azure, GCP), DFD, rede, deployment UML\n"
    "  - Qualquer diagrama com componentes de sistema interligados por setas/linhas\n\n"
    "NÃO são válidos — responda is_architecture_diagram=False para TODOS estes casos:\n"
    "  - Fotografias ou imagens naturais\n"
    "  - Capturas de tela de sistemas operacionais (Gerenciador de Tarefas, Explorer,\n"
    "    Painel de Controle, configurações do Windows/macOS/Linux, etc.)\n"
    "  - Capturas de tela de aplicativos comuns (navegador, editor de texto, IDE, terminal)\n"
    "  - Diagramas UML de classes puros (sem componentes de runtime)\n"
    "  - Documentos, tabelas, planilhas ou texto puro\n"
    "  - Wireframes / mockups de interface de usuário\n"
    "  - Fluxogramas de processo de negócio sem componentes de TI\n"
    "  - Memes, arte, logotipos, ícones isolados\n"
    "  - Gráficos estatísticos (barras, pizza, linhas)\n"
    "  - Imagens genéricas ou ambíguas sem componentes de software claros\n\n"
    "Na dúvida, responda is_architecture_diagram=False com confidence baixa.\n"
    "Esboços à mão com caixas e setas representando servidores/serviços também são válidos."
)


# ---------------------------------------------------------------------------
# Classificação via Gemini Vision
# ---------------------------------------------------------------------------


async def _classify_image(
    image_path: Path,
    mime: str,
) -> _DiagramClassification | None:
    """
    Classifica a imagem via Gemini Vision usando modelo econômico.

    Retorna ``None`` apenas em caso de erro irrecuperável.
    """
    try:
        image_b64 = base64.b64encode(image_path.read_bytes()).decode()
        llm = create_validator_llm()
        chain = llm.with_structured_output(_DiagramClassification)
        message = HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                },
                {"type": "text", "text": _VALIDATOR_PROMPT},
            ]
        )
        result: _DiagramClassification = await chain.ainvoke([message])
        logger.info(
            "[validate_diagram] Gemini: valid=%s confidence=%.2f type='%s'",
            result.is_architecture_diagram,
            result.confidence,
            result.detected_type,
        )
        return result
    except Exception as exc:
        logger.error("[validate_diagram] Erro no Gemini: %s", exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Helpers de resultado
# ---------------------------------------------------------------------------


def _valid_result(detected_type: str) -> dict:
    logger.info("[validate_diagram] Diagrama validado — tipo: %s", detected_type)
    return {
        "is_valid_diagram": True,
        "validation_message": "",
        "detected_type": detected_type,
        "step": "validation_done",
    }


def _invalid_result(detected_type: str, reason: str, suggestion: str) -> dict:
    message = (
        f"A imagem não parece ser um diagrama de arquitetura de software. "
        f"Detectado: **{detected_type}**. "
        f"{reason} {suggestion}"
    )
    return {
        "is_valid_diagram": False,
        "validation_message": message,
        "detected_type": detected_type,
        "step": "validation_failed",
    }


def _error_result(error_message: str) -> dict:
    """Rejeita a imagem quando a validação falha por erro técnico."""
    logger.error("[validate_diagram] Falha na validação: %s", error_message)
    return {
        "is_valid_diagram": False,
        "validation_message": (
            "Não foi possível validar a imagem. "
            "Tente novamente ou envie um diagrama de arquitetura mais claro."
        ),
        "detected_type": "",
        "step": "validation_error",
    }


# ---------------------------------------------------------------------------
# Nó LangGraph principal
# ---------------------------------------------------------------------------


async def validate_diagram_node(state: AnalysisState) -> dict:
    """
    Valida se a imagem enviada é um diagrama de arquitetura usando Gemini Vision.

    Usa um modelo econômico (configurável via GEMINI_VALIDATOR_MODEL no .env)
    para classificar a imagem com structured output. Se a imagem for inválida,
    retorna ``is_valid_diagram=False`` e o grafo encerra sem executar a análise STRIDE.
    """
    image_path = Path(state["image_path"])
    mime = state.get("mime_type", DEFAULT_MIME_TYPE)
    logger.info("[validate_diagram] Iniciando validação: %s", image_path.name)

    result = await _classify_image(image_path, mime)

    if result is None:
        return _error_result("Gemini não retornou resultado de classificação")

    is_valid = (
        result.is_architecture_diagram
        and result.confidence >= VALIDATOR_GEMINI_MIN_CONFIDENCE
    )

    if is_valid:
        return _valid_result(result.detected_type)

    reason = result.rejection_reason or (
        "Não foram identificados componentes de arquitetura de software."
    )
    suggestion = result.suggestion or (
        "Envie um diagrama criado em draw.io, Lucidchart, PlantUML ou similar, "
        "mostrando servidores, APIs, bancos de dados e as conexões entre eles."
    )
    return _invalid_result(result.detected_type, reason, suggestion)
