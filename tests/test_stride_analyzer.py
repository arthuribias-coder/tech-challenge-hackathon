"""Testes unitários para o serviço de análise STRIDE."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import ArchitectureComponent, StrideCategory
from app.services.stride_analyzer import generate_stride_threats


def _make_mock_response(threats_data: list[dict], summary: str) -> MagicMock:
    """Constrói um mock que simula a resposta do Google Gemini."""
    mock_response = MagicMock()
    mock_response.text = json.dumps(
        {"threats": threats_data, "summary": summary}
    )
    return mock_response


@pytest.fixture
def sample_components() -> list[ArchitectureComponent]:
    return [
        ArchitectureComponent(
            name="Web App",
            component_type="servidor web",
            description="Aplicação web principal",
        ),
        ArchitectureComponent(
            name="MySQL",
            component_type="banco de dados",
            description="Banco de dados relacional",
        ),
    ]


@pytest.mark.asyncio
async def test_generate_stride_threats_happy_path(
    sample_components: list[ArchitectureComponent],
):
    threats_data = [
        {
            "stride_category": "Spoofing",
            "title": "Falsificação de identidade",
            "description": "Atacante se passa por usuário legítimo.",
            "affected_component": "Web App",
            "severity": "Alta",
            "countermeasures": ["MFA", "Certificados TLS mútuos"],
        },
        {
            "stride_category": "Tampering",
            "title": "Injeção de SQL",
            "description": "Modificação de consultas ao banco.",
            "affected_component": "MySQL",
            "severity": "Alta",
            "countermeasures": ["Prepared statements", "ORM"],
        },
    ]

    mock_response = _make_mock_response(threats_data, "Sistema apresenta riscos críticos.")

    with patch("app.services.stride_analyzer.genai") as mock_genai:
        mock_client = AsyncMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        mock_genai.Client.return_value = mock_client

        with patch("app.services.stride_analyzer.settings") as mock_settings:
            mock_settings.gemini_api_key = "AIza-test"
            mock_settings.gemini_model = "gemini-2.0-flash"

            threats, summary = await generate_stride_threats(sample_components)

    assert len(threats) == 2
    assert threats[0].stride_category == StrideCategory.SPOOFING
    assert threats[1].stride_category == StrideCategory.TAMPERING
    assert "críticos" in summary


@pytest.mark.asyncio
async def test_generate_stride_threats_ignores_invalid_category(
    sample_components: list[ArchitectureComponent],
):
    threats_data = [
        {
            "stride_category": "Unknown Category",
            "title": "Ameaça inválida",
            "description": "Categoria inexistente no STRIDE.",
            "affected_component": "Web App",
            "severity": "Alta",
            "countermeasures": [],
        },
        {
            "stride_category": "Spoofing",
            "title": "Ameaça válida",
            "description": "Descrição válida.",
            "affected_component": "Web App",
            "severity": "Média",
            "countermeasures": ["HTTPS"],
        },
    ]

    mock_response = _make_mock_response(threats_data, "Sumário de teste.")

    with patch("app.services.stride_analyzer.genai") as mock_genai:
        mock_client = AsyncMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        mock_genai.Client.return_value = mock_client

        with patch("app.services.stride_analyzer.settings") as mock_settings:
            mock_settings.gemini_api_key = "AIza-test"
            mock_settings.gemini_model = "gemini-2.0-flash"

            threats, _ = await generate_stride_threats(sample_components)

    assert len(threats) == 1
    assert threats[0].stride_category == StrideCategory.SPOOFING


@pytest.mark.asyncio
async def test_generate_stride_threats_raises_when_no_api_key(
    sample_components: list[ArchitectureComponent],
):
    with patch("app.services.stride_analyzer.settings") as mock_settings:
        mock_settings.gemini_api_key = ""

        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            await generate_stride_threats(sample_components)
