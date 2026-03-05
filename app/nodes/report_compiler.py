"""
Nó LangGraph: compila o relatório final de ameaças STRIDE.

Converte os dados acumulados no estado para um ThreatReport Pydantic,
serializa para dict e armazena em state["report"].
"""

from __future__ import annotations

import logging

from app.models.schemas import AnalysisState, ArchitectureComponent, Threat, ThreatReport

logger = logging.getLogger(__name__)


async def compile_report_node(state: AnalysisState) -> dict:
    """
    Nó LangGraph: constrói o ThreatReport a partir do estado acumulado.
    Valida via Pydantic e descarta itens malformados silenciosamente.
    """
    logger.info(
        "[compile_report] Compilando: %d componentes, %d ameaças",
        len(state.get("components", [])),
        len(state.get("threats", [])),
    )

    components: list[ArchitectureComponent] = []
    for raw in state.get("components", []):
        try:
            components.append(ArchitectureComponent(**raw))
        except Exception as exc:
            logger.warning("[compile_report] Componente inválido ignorado: %s", exc)

    threats: list[Threat] = []
    for raw in state.get("threats", []):
        try:
            threats.append(Threat(**raw))
        except Exception as exc:
            logger.warning("[compile_report] Ameaça inválida ignorada: %s", exc)

    report = ThreatReport(
        components=components,
        threats=threats,
        summary=state.get("summary", ""),
    )

    logger.info("[compile_report] Relatório compilado com sucesso")
    return {"report": report.model_dump(mode="json"), "step": "done"}
