"""
Grafo LangGraph de análise de ameaças STRIDE.

Fluxo:
      START
        │
   detect_shapes          ← OpenCV + OCR + YOLO-World (opcional)
        │
   ┌────▼────────────────────────────────────────────┐
   │ has_yolo_detections?                            │
   │   True  → map_components (text-only LLM)       │
   │   False → vision_fallback (Gemini Vision)       │
   └────────────────────────────────────────────────┘
        │
   analyze_stride          ← LangChain STRIDE chain
        │
   compile_report          ← monta ThreatReport
        │
       END

Streaming: use ``graph.astream(state, stream_mode="updates")`` no router
para receber os updates de cada nó em tempo real.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.models.schemas import AnalysisState
from app.nodes.component_mapper import map_components_node, vision_fallback_node
from app.nodes.diagram_validator import validate_diagram_node
from app.nodes.report_compiler import compile_report_node
from app.nodes.stride_node import analyze_stride_node
from app.nodes.yolo_detector import detect_shapes_node


def _route_after_validation(state: AnalysisState) -> Literal["detect_shapes", "__end__"]:
    """Encerra o pipeline se a imagem não for um diagrama válido."""
    if state.get("is_valid_diagram", True):
        return "detect_shapes"
    return "__end__"


def _route_after_detection(state: AnalysisState) -> Literal["map_components", "vision_fallback"]:
    """Decide qual caminho seguir baseado na qualidade das detecções visuais."""
    if state.get("has_yolo_detections"):
        return "map_components"
    return "vision_fallback"


def build_analysis_graph() -> StateGraph:
    """Constrói e compila o grafo de análise. Chamado uma vez na inicialização."""
    builder = StateGraph(AnalysisState)

    # Nós
    builder.add_node("validate_diagram", validate_diagram_node)
    builder.add_node("detect_shapes", detect_shapes_node)
    builder.add_node("map_components", map_components_node)
    builder.add_node("vision_fallback", vision_fallback_node)
    builder.add_node("analyze_stride", analyze_stride_node)
    builder.add_node("compile_report", compile_report_node)

    # Arestas
    builder.add_edge(START, "validate_diagram")
    builder.add_conditional_edges(
        "validate_diagram",
        _route_after_validation,
        {"detect_shapes": "detect_shapes", "__end__": END},
    )
    builder.add_conditional_edges(
        "detect_shapes",
        _route_after_detection,
        {"map_components": "map_components", "vision_fallback": "vision_fallback"},
    )
    builder.add_edge("map_components", "analyze_stride")
    builder.add_edge("vision_fallback", "analyze_stride")
    builder.add_edge("analyze_stride", "compile_report")
    builder.add_edge("compile_report", END)

    return builder.compile()


# Instância singleton compilada na inicialização do módulo
analysis_graph = build_analysis_graph()


# ---------------------------------------------------------------------------
# Labels de progresso para o frontend (SSE)
# ---------------------------------------------------------------------------

NODE_LABELS: dict[str, str] = {
    "validate_diagram": "Verificando se é um diagrama de arquitetura...",
    "detect_shapes": "Detectando elementos visuais (OpenCV + OCR)...",
    "map_components": "Identificando componentes (análise de texto)...",
    "vision_fallback": "Analisando diagrama com IA Vision...",
    "analyze_stride": "Aplicando metodologia STRIDE...",
    "compile_report": "Compilando relatório de ameaças...",
}
