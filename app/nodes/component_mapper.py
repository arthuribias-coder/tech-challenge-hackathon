"""
Nó LangGraph: mapeia detecções brutas (YOLO + OpenCV) em ArchitectureComponents.

Usa LangChain com saída estruturada via ``with_structured_output``.
Recebe apenas JSON de texto — sem imagem — o que reduz ~60% do custo de tokens
em comparação com enviar a imagem inteira ao Gemini Vision.

Se não houver detecções suficientes (has_yolo_detections=False), este nó não é
chamado: o grafo encaminha para ``vision_fallback_node``.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from app.config import settings
from app.models.schemas import AnalysisState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output Schema (Pydantic) — LangChain infere o JSON schema automaticamente
# ---------------------------------------------------------------------------


class _Component(BaseModel):
    name: str = Field(description="Nome único e descritivo do componente")
    component_type: str = Field(
        description=(
            "Tipo: usuário, servidor web, banco de dados, API, serviço externo, "
            "firewall, balanceador de carga, fila de mensagens, cache, etc."
        )
    )
    description: str = Field(description="Papel deste componente na arquitetura")


class _ComponentList(BaseModel):
    components: list[_Component] = Field(description="Lista de todos os componentes identificados")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_MAPPER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        (
            "Você é um especialista em arquitetura de software. "
            "Receberá uma lista de formas geométricas e textos extraídos de um diagrama de arquitetura. "
            "Interprete esses dados e identifique os componentes da arquitetura. "
            "Consolide formas relacionadas em um único componente quando fizer sentido. "
            "Retorne SOMENTE os componentes relevantes para a análise de segurança."
        ),
    ),
    (
        "human",
        (
            "Formas detectadas no diagrama:\n{detections_text}\n\n"
            "Observações do usuário: {notes}\n\n"
            "Identifique os componentes de arquitetura presentes."
        ),
    ),
])

_VISION_PROMPT = (
    "Você é um especialista em arquitetura de software e segurança de sistemas. "
    "Analise o diagrama de arquitetura de software fornecido e identifique TODOS os componentes presentes. "
    "Seja detalhado: inclua conexões, zonas de confiança, protocolos e elementos de segurança visíveis."
)


def _format_detections_for_llm(detections: list[dict]) -> str:
    """Serializa as detecções para texto legível pelo LLM."""
    lines: list[str] = []
    for d in detections:
        text = d.get("text", "").strip()
        shape = d.get("shape_type", "unknown")
        label = d.get("label", "")
        bbox = d.get("bbox", [])

        parts = [f"- Forma: {shape}"]
        if label and label != text:
            parts.append(f"Classe YOLO: {label}")
        if text:
            parts.append(f"Texto: '{text}'")
        if bbox:
            x1, y1, x2, y2 = bbox
            parts.append(f"Posição: ({x1},{y1})-({x2},{y2})")

        lines.append(" | ".join(parts))

    return "\n".join(lines) if lines else "(nenhuma detecção)"


def _get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.1,
    )


async def map_components_node(state: AnalysisState) -> dict:
    """
    Nó LangGraph: converte detecções brutas em ArchitectureComponents via LLM text-only.
    Custo reduzido: sem imagem na requisição.
    """
    logger.info("[map_components] Mapeando %d detecções", len(state.get("detections", [])))

    try:
        llm = _get_llm()
        chain = _MAPPER_PROMPT | llm.with_structured_output(_ComponentList)

        detections_text = _format_detections_for_llm(state.get("detections", []))
        result: _ComponentList = await chain.ainvoke(
            {
                "detections_text": detections_text,
                "notes": state.get("notes") or "(sem observações)",
            }
        )

        components = [c.model_dump() for c in result.components]
        logger.info("[map_components] %d componentes mapeados", len(components))
        return {"components": components, "step": "mapping_done"}

    except Exception as exc:
        logger.error("[map_components] Erro: %s", exc, exc_info=True)
        return {"components": [], "step": "mapping_failed", "error": str(exc)}


async def vision_fallback_node(state: AnalysisState) -> dict:
    """
    Nó LangGraph: extrai componentes diretamente via Gemini Vision (fallback quando
    YOLO/OCR não detectou elementos suficientes).
    Envia a imagem completa em base64 — mais tokens, mas mais preciso.
    """
    image_path = Path(state["image_path"])
    logger.info("[vision_fallback] Usando Gemini Vision para: %s", image_path.name)

    try:
        image_b64 = base64.b64encode(image_path.read_bytes()).decode()
        mime = state.get("mime_type", "image/png")

        llm = _get_llm()
        chain = llm.with_structured_output(_ComponentList)

        message = HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                },
                {"type": "text", "text": _VISION_PROMPT},
            ]
        )

        result: _ComponentList = await chain.ainvoke([message])
        components = [c.model_dump() for c in result.components]
        logger.info("[vision_fallback] %d componentes identificados via Vision", len(components))
        return {"components": components, "step": "vision_done"}

    except Exception as exc:
        logger.error("[vision_fallback] Erro: %s", exc, exc_info=True)
        return {"components": [], "step": "vision_failed", "error": str(exc)}
