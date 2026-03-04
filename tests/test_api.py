"""Testes para os endpoints da API FastAPI."""

import io
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.schemas import ArchitectureComponent, StrideCategory, Threat, ThreatReport


@pytest.fixture
def mock_report() -> ThreatReport:
    return ThreatReport(
        components=[
            ArchitectureComponent(
                name="Web Server",
                component_type="servidor web",
                description="Serve as requisições HTTP",
            ),
            ArchitectureComponent(
                name="Database",
                component_type="banco de dados",
                description="Armazena dados dos usuários",
            ),
        ],
        threats=[
            Threat(
                stride_category=StrideCategory.SPOOFING,
                title="Falsificação de sessão",
                description="Tokens de sessão podem ser forjados.",
                affected_component="Web Server",
                severity="Alta",
                countermeasures=["Usar HTTPS", "Validar tokens JWT"],
            ),
            Threat(
                stride_category=StrideCategory.INFORMATION_DISCLOSURE,
                title="Exposição de credenciais",
                description="Credenciais do banco podem vazar em logs.",
                affected_component="Database",
                severity="Alta",
                countermeasures=["Sanitizar logs", "Usar variáveis de ambiente"],
            ),
        ],
        summary="Análise identificou 2 ameaças de alta severidade.",
    )


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_root_redirects_to_analysis():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as client:
        response = await client.get("/")
    assert response.status_code in (301, 302, 307, 308)
    assert "/analysis/" in response.headers.get("location", "")


@pytest.mark.asyncio
async def test_analysis_form_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/analysis/")
    assert response.status_code == 200
    assert b"STRIDE" in response.content


@pytest.mark.asyncio
async def test_analysis_upload_invalid_file_type():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/analysis/",
            files={"diagram": ("test.pdf", b"%PDF content", "application/pdf")},
            data={"notes": ""},
        )
    assert response.status_code == 415


@pytest.mark.asyncio
async def test_analysis_upload_file_too_large():
    large_content = b"x" * (11 * 1024 * 1024)  # 11MB
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/analysis/",
            files={"diagram": ("large.png", large_content, "image/png")},
            data={"notes": ""},
        )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_analysis_upload_success(mock_report: ThreatReport):
    small_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
        b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
        b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    with patch(
        "app.routers.analysis.generate_threat_report",
        new_callable=lambda: lambda: AsyncMock(return_value=mock_report),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/analysis/",
                files={"diagram": ("architecture.png", small_png, "image/png")},
                data={"notes": "sistema de teste"},
            )
    assert response.status_code == 200
    assert b"Relatório" in response.content or b"STRIDE" in response.content
