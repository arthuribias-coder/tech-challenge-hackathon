"""
Nó de detecção visual do LangGraph.

Pipeline:
  1. OpenCV — detecta formas geométricas (retângulos, cilindros, etc.)
  2. EasyOCR — extrai texto de toda a imagem
  3. Associação espacial — vincula texto às formas mais próximas
  4. YOLO-World (opcional) — enriquece com classificação semântica de ícones

Todas as libs de ML são importadas de forma lazy (try/except) para que o
sistema funcione mesmo quando ainda não estão instaladas — nesse caso o grafo
encaminha automaticamente para o nó de fallback via Gemini Vision.
"""

from __future__ import annotations

import importlib.util
import logging
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.constants import (
    DIAGRAM_CLASSES,
    MAX_DETECTED_SHAPES,
    OCR_CONFIDENCE_THRESHOLD,
    SHAPE_MIN_AREA_RATIO,
    TEXT_ASSOCIATION_MAX_DISTANCE_PX,
    YOLO_CONFIDENCE_THRESHOLD,
    YOLO_MODEL_PATH,
)
from app.models.schemas import AnalysisState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Disponibilidade opcional das libs pesadas (PyTorch-based)
# ---------------------------------------------------------------------------

_EASYOCR_AVAILABLE = importlib.util.find_spec("easyocr") is not None
_ULTRALYTICS_AVAILABLE = importlib.util.find_spec("ultralytics") is not None


def _detect_shapes(image: np.ndarray) -> list[dict[str, Any]]:
    """Detecta formas geométricas via OpenCV e retorna lista de bounding boxes."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)

    # Dilata as arestas para fechar contornos abertos
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    dilated = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    shapes: list[dict[str, Any]] = []
    h, w = image.shape[:2]
    min_area = (w * h) * SHAPE_MIN_AREA_RATIO  # ignora ruídos muito pequenos

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue

        x, y, bw, bh = cv2.boundingRect(contour)

        # Classifica o tipo geométrico pela aproximação do contorno
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
        n_vertices = len(approx)

        # Detecta cilindros (DB) pela razão altura/largura + elipse
        aspect = bh / bw if bw > 0 else 1
        shape_type = "unknown"
        if n_vertices == 4:
            shape_type = "rectangle"
        elif n_vertices > 8:
            shape_type = "circle" if 0.8 < aspect < 1.2 else "ellipse"
        elif n_vertices == 3:
            shape_type = "triangle"
        elif aspect > 1.5 and n_vertices <= 8:
            shape_type = "cylinder"  # heurística para bancos de dados

        shapes.append({
            "id": len(shapes),
            "shape_type": shape_type,
            "bbox": [int(x), int(y), int(x + bw), int(y + bh)],
            "area": float(area),
            "text": "",  # preenchido pela etapa de OCR
        })

    # Ordena por área decrescente (componentes maiores primeiro)
    shapes.sort(key=lambda s: s["area"], reverse=True)
    return shapes[:MAX_DETECTED_SHAPES]  # limita formas para não poluir o contexto


def _extract_text_easyocr(image_path: Path) -> list[dict[str, Any]]:
    """Extrai texto com localizações usando EasyOCR."""
    import easyocr  # noqa: PLC0415 — lazy import intencional

    reader = easyocr.Reader(["pt", "en"], verbose=False)
    results = reader.readtext(str(image_path))

    texts: list[dict[str, Any]] = []
    for bbox_points, text, confidence in results:
        if confidence < OCR_CONFIDENCE_THRESHOLD or not text.strip():
            continue
        # bbox_points = [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
        xs = [p[0] for p in bbox_points]
        ys = [p[1] for p in bbox_points]
        texts.append({
            "text": text.strip(),
            "confidence": float(confidence),
            "cx": float(sum(xs) / 4),
            "cy": float(sum(ys) / 4),
        })

    return texts


def _extract_text_opencv(gray: np.ndarray) -> list[dict[str, Any]]:
    """
    Fallback de OCR via OpenCV (EAST não disponível neste build, mas extraímos
    regiões de texto por threshold e retornamos metadados mínimos para que o
    mapeador LLM entenda a estrutura do diagrama).
    Retorna lista mínima — sem texto real, só estrutura de caixas.
    """
    return []  # OpenCV puro sem EAST: retorna vazio, LLM MapperNode usará layout


def _associate_text_to_shapes(
    shapes: list[dict], texts: list[dict]
) -> list[dict]:
    """Vincula cada texto à forma de menor distância do centroide."""
    if not texts:
        return shapes

    updated = [dict(s) for s in shapes]

    for text_item in texts:
        tx, ty = text_item["cx"], text_item["cy"]
        best_idx = -1
        best_dist = float("inf")

        for i, shape in enumerate(updated):
            x1, y1, x2, y2 = shape["bbox"]
            sx, sy = (x1 + x2) / 2, (y1 + y2) / 2
            dist = math.sqrt((tx - sx) ** 2 + (ty - sy) ** 2)

            # Prefere formas que contenham o texto (distância interna)
            inside = x1 <= tx <= x2 and y1 <= ty <= y2
            effective = dist * 0.1 if inside else dist

            if effective < best_dist:
                best_dist = effective
                best_idx = i

        if best_idx >= 0 and best_dist < TEXT_ASSOCIATION_MAX_DISTANCE_PX:  # limiar espacial
            prev = updated[best_idx]["text"]
            sep = " | " if prev else ""
            updated[best_idx]["text"] = prev + sep + text_item["text"]

    return updated


def _run_yolo_world(image_path: Path) -> list[dict[str, Any]]:
    """Enriquece detecções com YOLO-World (classificação semântica de ícones)."""
    from ultralytics import YOLOWorld  # noqa: PLC0415 — lazy import intencional

    model = YOLOWorld(YOLO_MODEL_PATH)
    model.set_classes(DIAGRAM_CLASSES)
    results = model.predict(str(image_path), verbose=False, conf=YOLO_CONFIDENCE_THRESHOLD)

    detections: list[dict[str, Any]] = []
    for result in results:
        for box in result.boxes:
            cls_id = int(box.cls[0])
            label = DIAGRAM_CLASSES[cls_id] if cls_id < len(DIAGRAM_CLASSES) else "unknown"
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
            detections.append({
                "id": len(detections),
                "shape_type": "yolo_detection",
                "label": label,
                "confidence": float(box.conf[0]),
                "bbox": [x1, y1, x2, y2],
                "area": float((x2 - x1) * (y2 - y1)),
                "text": label,
            })

    return detections


async def detect_shapes_node(state: AnalysisState) -> dict:
    """
    Nó LangGraph: detecta elementos visuais no diagrama.
    Usa OpenCV + OCR (obrigatório) e YOLO-World (opcional).
    """
    image_path = Path(state["image_path"])
    logger.info("[detect_shapes] Processando: %s", image_path.name)

    try:
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"Não foi possível carregar a imagem: {image_path}")

        # 1. Detecção de formas geométricas
        shapes = _detect_shapes(image)
        logger.info("[detect_shapes] %d formas detectadas via OpenCV", len(shapes))

        # 2. OCR — EasyOCR preferido, fallback para OpenCV
        if _EASYOCR_AVAILABLE:
            try:
                texts = _extract_text_easyocr(image_path)
                logger.info("[detect_shapes] %d textos extraídos via EasyOCR", len(texts))
            except Exception as exc:
                logger.warning("[detect_shapes] EasyOCR falhou: %s — sem texto", exc)
                texts = []
        else:
            logger.info("[detect_shapes] EasyOCR não disponível — sem OCR")
            texts = []

        # 3. Associação texto ↔ forma
        shapes = _associate_text_to_shapes(shapes, texts)

        # 4. YOLO-World (enriquecimento opcional)
        yolo_detections: list[dict] = []
        if _ULTRALYTICS_AVAILABLE:
            try:
                yolo_detections = _run_yolo_world(image_path)
                logger.info("[detect_shapes] %d ícones detectados via YOLO-World", len(yolo_detections))
            except Exception as exc:
                logger.warning("[detect_shapes] YOLO-World falhou: %s — ignorando", exc)

        # Merge: YOLO detections + OpenCV shapes (deduplicação por sobreposição futura)
        all_detections = yolo_detections + shapes

        # Considera que temos detecções úteis se há textos associados às formas
        shapes_with_text = [s for s in shapes if s.get("text")]
        has_useful_detections = len(shapes_with_text) >= 2

        return {
            "detections": all_detections,
            "has_yolo_detections": has_useful_detections,
            "step": "detection_done",
        }

    except Exception as exc:
        logger.error("[detect_shapes] Erro: %s", exc, exc_info=True)
        return {
            "detections": [],
            "has_yolo_detections": False,
            "step": "detection_failed",
            "error": str(exc),
        }
