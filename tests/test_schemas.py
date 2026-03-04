"""Testes para os schemas Pydantic e lógica de modelos."""

import pytest

from app.models.schemas import (
    ArchitectureComponent,
    StrideCategory,
    Threat,
    ThreatReport,
)


def test_architecture_component_creation():
    component = ArchitectureComponent(
        name="API Gateway",
        component_type="API",
        description="Ponto de entrada da plataforma",
    )
    assert component.name == "API Gateway"
    assert component.component_type == "API"


def test_threat_creation_with_valid_stride():
    threat = Threat(
        stride_category=StrideCategory.SPOOFING,
        title="Falsificação de sessão",
        description="Um atacante pode forjar tokens JWT expirados.",
        affected_component="API Gateway",
        severity="Alta",
        countermeasures=["Verificar assinatura JWT", "Utilizar tempo de expiração curto"],
    )
    assert threat.stride_category == StrideCategory.SPOOFING
    assert len(threat.countermeasures) == 2


def test_threat_report_defaults():
    report = ThreatReport()
    assert report.components == []
    assert report.threats == []
    assert report.summary == ""


def test_stride_categories_coverage():
    categories = list(StrideCategory)
    expected = {
        "Spoofing",
        "Tampering",
        "Repudiation",
        "Information Disclosure",
        "Denial of Service",
        "Elevation of Privilege",
    }
    assert {c.value for c in categories} == expected


def test_threat_report_with_data():
    component = ArchitectureComponent(
        name="Database",
        component_type="banco de dados",
        description="Armazena dados sensíveis dos usuários",
    )
    threat = Threat(
        stride_category=StrideCategory.INFORMATION_DISCLOSURE,
        title="Exposição de dados sensíveis",
        description="Banco de dados sem criptografia em repouso.",
        affected_component="Database",
        severity="Alta",
        countermeasures=["Criptografar dados em repouso", "Controle de acesso rigoroso"],
    )
    report = ThreatReport(
        components=[component],
        threats=[threat],
        summary="Sistema com risco alto de exposição de dados.",
    )
    assert len(report.components) == 1
    assert len(report.threats) == 1
    assert "risco alto" in report.summary
