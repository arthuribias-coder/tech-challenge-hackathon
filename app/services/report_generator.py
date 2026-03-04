"""
Serviço de orquestração: coordena a análise de diagrama e a geração do relatório STRIDE.
"""

import logging
from pathlib import Path

from app.models.schemas import ThreatReport
from app.services.diagram_analyzer import extract_components
from app.services.stride_analyzer import generate_stride_threats

logger = logging.getLogger(__name__)


async def generate_threat_report(image_path: Path) -> ThreatReport:
    """
    Orquestra o fluxo completo:
    1. Extrai componentes do diagrama via visão computacional (Gemini Vision)
    2. Aplica a metodologia STRIDE sobre os componentes identificados
    3. Retorna um ThreatReport completo
    """
    logger.info("Iniciando análise de ameaças para: %s", image_path.name)

    components = await extract_components(image_path)

    if not components:
        logger.warning("Nenhum componente identificado no diagrama.")
        return ThreatReport(
            components=[],
            threats=[],
            summary="Não foi possível identificar componentes de arquitetura no diagrama fornecido.",
        )

    threats, summary = await generate_stride_threats(components)

    report = ThreatReport(components=components, threats=threats, summary=summary)

    logger.info(
        "Relatório gerado: %d componentes, %d ameaças",
        len(report.components),
        len(report.threats),
    )
    return report
