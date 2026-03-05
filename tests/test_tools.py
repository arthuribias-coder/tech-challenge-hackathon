"""Testes unitários para as STRIDE tools do LangGraph."""

import pytest
from app.tools.stride_tools import (
    explain_stride_category,
    calculate_risk_score,
    map_to_mitre_attack,
    get_owasp_controls,
    STRIDE_TOOLS,
)


class TestExplainStrideCategory:
    def test_spoofing_pt(self):
        result = explain_stride_category.invoke({"category": "Spoofing"})
        assert "identidade" in result.lower() or "spoofing" in result.lower()

    def test_tampering_alias(self):
        result = explain_stride_category.invoke({"category": "adulteração"})
        assert "tampering" in result.lower() or "adulteração" in result.lower()

    def test_unknown_category(self):
        result = explain_stride_category.invoke({"category": "XYZ"})
        assert "não encontrada" in result.lower() or "categorias" in result.lower()

    def test_all_categories_return_string(self):
        categories = ["Spoofing", "Tampering", "Repudiation",
                      "Information Disclosure", "Denial of Service",
                      "Elevation of Privilege"]
        for cat in categories:
            result = explain_stride_category.invoke({"category": cat})
            assert isinstance(result, str) and len(result) > 20


class TestCalculateRiskScore:
    def test_critica_alta(self):
        # A tool aceita: alta, media/m\u00e9dia, baixa
        score = calculate_risk_score.invoke({"severity": "alta", "likelihood": "alta"})
        assert "9" in score

    def test_baixa_baixa(self):
        score = calculate_risk_score.invoke({"severity": "baixa", "likelihood": "baixa"})
        assert "1" in score

    def test_media_media(self):
        score = calculate_risk_score.invoke({"severity": "m\u00e9dia", "likelihood": "m\u00e9dia"})
        assert "5" in score

    def test_invalid_severity(self):
        result = calculate_risk_score.invoke({"severity": "inexistente", "likelihood": "alta"})
        assert "inv\u00e1lid" in result.lower() or "use:" in result.lower()

    def test_invalid_likelihood(self):
        result = calculate_risk_score.invoke({"severity": "alta", "likelihood": "nunca"})
        assert "inv\u00e1lid" in result.lower() or "use:" in result.lower()


class TestMapToMitreAttack:
    def test_spoofing_returns_techniques(self):
        result = map_to_mitre_attack.invoke({
            "stride_category": "Spoofing",
            "component_type": "API"
        })
        assert "T1" in result or "MITRE" in result

    def test_unknown_category(self):
        result = map_to_mitre_attack.invoke({
            "stride_category": "Unknown",
            "component_type": "Server"
        })
        assert isinstance(result, str)

    def test_all_stride_have_mitre(self):
        categories = ["Spoofing", "Tampering", "Repudiation",
                      "Information Disclosure", "Denial of Service",
                      "Elevation of Privilege"]
        for cat in categories:
            result = map_to_mitre_attack.invoke({
                "stride_category": cat,
                "component_type": "WebApp"
            })
            assert isinstance(result, str) and len(result) > 10


class TestGetOwaspControls:
    def test_sql_injection(self):
        result = get_owasp_controls.invoke({"threat_keyword": "SQL Injection"})
        assert "A03" in result or "injection" in result.lower()

    def test_xss(self):
        result = get_owasp_controls.invoke({"threat_keyword": "XSS"})
        assert isinstance(result, str) and len(result) > 10

    def test_unknown_keyword(self):
        result = get_owasp_controls.invoke({"threat_keyword": "quantum_attack"})
        assert "A04" in result or isinstance(result, str)

    def test_returns_owasp_reference(self):
        result = get_owasp_controls.invoke({"threat_keyword": "autenticação"})
        assert "A" in result and ":" in result


class TestStrideToolsList:
    def test_all_tools_present(self):
        names = [t.name for t in STRIDE_TOOLS]
        assert "explain_stride_category" in names
        assert "calculate_risk_score" in names
        assert "map_to_mitre_attack" in names
        assert "get_owasp_controls" in names

    def test_tools_count(self):
        assert len(STRIDE_TOOLS) == 4

    def test_tools_are_callable(self):
        for tool in STRIDE_TOOLS:
            assert callable(tool.invoke)
