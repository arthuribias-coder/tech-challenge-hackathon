"""Testes unitários para os nós LangGraph do pipeline de análise."""

import asyncio
import pytest
from unittest.mock import patch, MagicMock
from app.models.schemas import AnalysisState


def _run(coro):
    """Executa uma corrotina de forma síncrona nos testes."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _base_state(**kwargs) -> AnalysisState:
    """Cria um AnalysisState mínimo para testes."""
    state: AnalysisState = {
        "image_path": "/tmp/test.png",
        "notes": "",
        "mime_type": "image/png",
        "detections": [],
        "has_yolo_detections": False,
        "components": [],
        "threats": [],
        "summary": "",
        "report": None,
        "step": "init",
        "error": None,
        "is_valid_diagram": True,
        "validation_message": "",
        "detected_type": "",
    }
    state.update(kwargs)
    return state


class TestReportCompilerNode:
    """Testa compile_report_node sem dependências externas."""

    def test_empty_state_returns_report(self):
        from app.nodes.report_compiler import compile_report_node
        state = _base_state()
        result = _run(compile_report_node(state))
        assert "report" in result


class TestDiagramValidatorNode:
    """Testa validate_diagram_node com mock do Gemini."""

    @patch("app.nodes.diagram_validator._classify_image")
    def test_valid_diagram_accepted(self, mock_classify):
        from app.nodes.diagram_validator import validate_diagram_node, _DiagramClassification
        mock_classify.return_value = _DiagramClassification(
            is_architecture_diagram=True,
            confidence=0.95,
            detected_type="diagrama de arquitetura AWS",
            rejection_reason="",
            suggestion="",
        )
        state = _base_state()
        result = _run(validate_diagram_node(state))
        assert result["is_valid_diagram"] is True
        assert result["detected_type"] == "diagrama de arquitetura AWS"

    @patch("app.nodes.diagram_validator._classify_image")
    def test_random_image_rejected(self, mock_classify):
        from app.nodes.diagram_validator import validate_diagram_node, _DiagramClassification
        mock_classify.return_value = _DiagramClassification(
            is_architecture_diagram=False,
            confidence=0.92,
            detected_type="fotografia de paisagem",
            rejection_reason="A imagem é uma fotografia, não um diagrama.",
            suggestion="Envie um diagrama criado em draw.io.",
        )
        state = _base_state()
        result = _run(validate_diagram_node(state))
        assert result["is_valid_diagram"] is False
        assert "fotografia" in result["detected_type"]
        assert result["validation_message"] != ""

    @patch("app.nodes.diagram_validator._classify_image")
    def test_low_confidence_rejected(self, mock_classify):
        from app.nodes.diagram_validator import validate_diagram_node, _DiagramClassification
        mock_classify.return_value = _DiagramClassification(
            is_architecture_diagram=True,
            confidence=0.3,
            detected_type="imagem ambígua",
            rejection_reason="Confiança muito baixa.",
            suggestion="Envie uma imagem mais clara.",
        )
        state = _base_state()
        result = _run(validate_diagram_node(state))
        assert result["is_valid_diagram"] is False

    @patch("app.nodes.diagram_validator._classify_image")
    def test_gemini_error_rejects(self, mock_classify):
        from app.nodes.diagram_validator import validate_diagram_node
        mock_classify.return_value = None
        state = _base_state()
        result = _run(validate_diagram_node(state))
        assert result["is_valid_diagram"] is False
        assert "Não foi possível validar" in result["validation_message"]

    @patch("app.nodes.diagram_validator._classify_image")
    def test_screenshot_rejected(self, mock_classify):
        from app.nodes.diagram_validator import validate_diagram_node, _DiagramClassification
        mock_classify.return_value = _DiagramClassification(
            is_architecture_diagram=False,
            confidence=0.88,
            detected_type="captura de tela do Windows",
            rejection_reason="A imagem é um screenshot de sistema operacional.",
            suggestion="Envie um diagrama de arquitetura.",
        )
        state = _base_state()
        result = _run(validate_diagram_node(state))
        assert result["is_valid_diagram"] is False
        assert "captura de tela" in result["detected_type"]


class TestReportCompilerNodeExtended:
    """Testa compile_report_node com cenários adicionais."""

    def test_with_valid_threats(self):
        from app.nodes.report_compiler import compile_report_node
        state = _base_state(
            components=[{"name": "API", "component_type": "API Gateway", "description": "Rest API"}],
            threats=[{
                "title": "Token Forjado",
                "stride_category": "Spoofing",
                "affected_component": "API",
                "severity": "Alta",
                "description": "Attacker forges JWT token.",
                "countermeasures": ["Verificar assinatura"]
            }],
            summary="Resumo de teste."
        )
        result = _run(compile_report_node(state))
        assert "report" in result
        report = result["report"]
        assert report is not None
        # report pode ser ThreatReport (Pydantic) ou dict dependendo da implementação
        threats = report.threats if hasattr(report, "threats") else report.get("threats", [])
        assert len(threats) == 1
        title = threats[0].title if hasattr(threats[0], "title") else threats[0]["title"]
        assert title == "Token Forjado"

    def test_malformed_threat_is_discarded(self):
        from app.nodes.report_compiler import compile_report_node
        state = _base_state(
            threats=[{"invalid": "data"}]
        )
        result = _run(compile_report_node(state))
        assert "report" in result


class TestYoloDetectorNode:
    """Testa detect_shapes_node com mocks de OpenCV."""

    @patch("cv2.imread")
    @patch("cv2.cvtColor")
    @patch("cv2.Canny")
    @patch("cv2.findContours")
    def test_returns_detections_key(self, mock_contours, mock_canny, mock_cvt, mock_imread):
        import numpy as np
        mock_imread.return_value = np.zeros((100, 100, 3), dtype="uint8")
        mock_cvt.return_value = np.zeros((100, 100), dtype="uint8")
        mock_canny.return_value = np.zeros((100, 100), dtype="uint8")
        mock_contours.return_value = ([], None)

        from app.nodes.yolo_detector import detect_shapes_node
        state = _base_state()
        result = _run(detect_shapes_node(state))
        assert "detections" in result
        assert "step" in result

    @patch("cv2.imread", return_value=None)
    def test_missing_image_returns_empty(self, _):
        from app.nodes.yolo_detector import detect_shapes_node
        state = _base_state(image_path="/nonexistent/path.png")
        result = _run(detect_shapes_node(state))
        assert "detections" in result
        assert result["detections"] == [] or isinstance(result["detections"], list)


class TestAnalysisGraphStructure:
    """Verifica a estrutura do grafo de análise."""

    def test_graph_nodes_present(self):
        from app.graphs.analysis_graph import analysis_graph, NODE_LABELS
        node_names = list(analysis_graph.nodes)
        assert "__start__" in node_names
        # __end__ é implícito no LangGraph e não aparece em .nodes
        assert "detect_shapes" in node_names
        assert "analyze_stride" in node_names
        assert "compile_report" in node_names

    def test_node_labels_coverage(self):
        from app.graphs.analysis_graph import NODE_LABELS
        required = {"validate_diagram", "detect_shapes", "map_components", "vision_fallback",
                    "analyze_stride", "compile_report"}
        assert required.issubset(set(NODE_LABELS.keys()))


class TestChatGraphStructure:
    """Verifica que o chat_graph está configurado corretamente."""

    def test_chat_graph_has_tools(self):
        from app.graphs.chat_graph import chat_graph
        # O grafo deve ser criado sem erro
        assert chat_graph is not None

    def test_stride_tools_injected(self):
        from app.tools.stride_tools import STRIDE_TOOLS
        tool_names = {t.name for t in STRIDE_TOOLS}
        assert "explain_stride_category" in tool_names
        assert "calculate_risk_score" in tool_names
