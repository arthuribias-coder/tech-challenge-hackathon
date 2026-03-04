from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class StrideCategory(str, Enum):
    SPOOFING = "Spoofing"
    TAMPERING = "Tampering"
    REPUDIATION = "Repudiation"
    INFORMATION_DISCLOSURE = "Information Disclosure"
    DENIAL_OF_SERVICE = "Denial of Service"
    ELEVATION_OF_PRIVILEGE = "Elevation of Privilege"


class ArchitectureComponent(BaseModel):
    name: str = Field(description="Nome do componente identificado")
    component_type: str = Field(description="Tipo: usuário, servidor, banco de dados, API, etc.")
    description: str = Field(description="Descrição breve do papel do componente")


class Threat(BaseModel):
    stride_category: StrideCategory
    title: str = Field(description="Título curto da ameaça")
    description: str = Field(description="Descrição detalhada da ameaça")
    affected_component: str = Field(description="Componente afetado")
    severity: str = Field(description="Alta, Média ou Baixa")
    countermeasures: list[str] = Field(description="Lista de contramedidas recomendadas")


class ThreatReport(BaseModel):
    components: list[ArchitectureComponent] = Field(default_factory=list)
    threats: list[Threat] = Field(default_factory=list)
    summary: str = Field(default="", description="Resumo executivo da análise")


class AnalysisRequest(BaseModel):
    notes: str = Field(default="", description="Observações adicionais sobre a arquitetura")


class AnalysisResponse(BaseModel):
    report: ThreatReport
    image_filename: str


# ---------------------------------------------------------------------------
# LangGraph state — TypedDict com todos os campos do pipeline de análise
# ---------------------------------------------------------------------------

class AnalysisState(TypedDict):
    """Estado compartilhado entre os nós do grafo de análise de ameaças."""

    image_path: str          # Caminho absoluto da imagem
    notes: str               # Notas adicionais do usuário
    mime_type: str           # MIME type da imagem

    # Saída do nó de detecção visual (YOLO + OpenCV + OCR)
    detections: list[dict]
    has_yolo_detections: bool

    # Saída do nó de mapeamento de componentes
    components: list[dict]

    # Saída do nó de análise STRIDE
    threats: list[dict]
    summary: str

    # Relatório final compilado
    report: dict

    # Controle de fluxo e progresso
    step: str
    error: Optional[str]
