"""
Serviço de Fine-tuning YOLOv8.

Pipeline:
  1. Preparar dataset (Roboflow → HuggingFace → sintético local)
  2. Fine-tuning YOLOv8 com streaming de progresso por época via async generator
  3. Salvar modelo em app/models/finetuned/

Dependências opcionais:
  - ultralytics  : necessário para o treinamento
  - datasets     : necessário para download via HuggingFace
  - roboflow     : necessário para download via Roboflow Universe
"""

import asyncio
import logging
import random
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_ULTRALYTICS_AVAILABLE = False
_HF_DATASETS_AVAILABLE = False
_ROBOFLOW_AVAILABLE = False

try:
    from ultralytics import YOLO
    _ULTRALYTICS_AVAILABLE = True
except ImportError:
    logger.warning("ultralytics não instalado. Fine-tuning desabilitado.")

try:
    from datasets import load_dataset
    _HF_DATASETS_AVAILABLE = True
except ImportError:
    logger.warning("datasets (HF) não instalado. Download HF desabilitado.")

try:
    from roboflow import Roboflow
    _ROBOFLOW_AVAILABLE = True
except ImportError:
    logger.warning("roboflow não instalado. Download Roboflow desabilitado.")

# ---------------------------------------------------------------------------
# Constantes do dataset sintético
# ---------------------------------------------------------------------------

_SYNTHETIC_CLASS_NAMES: list[str] = [
    "user", "server", "database", "api",
    "firewall", "cache", "storage", "network",
]

_SYNTHETIC_CLASS_COLORS: list[tuple[int, int, int]] = [
    (70, 130, 180),   # user     — azul aço
    (46, 139, 87),    # server   — verde
    (178, 34, 34),    # database — vermelho
    (255, 165, 0),    # api      — laranja
    (128, 0, 128),    # firewall — roxo
    (0, 139, 139),    # cache    — ciano escuro
    (139, 90, 43),    # storage  — marrom
    (72, 61, 139),    # network  — violeta escuro
]

_SYNTHETIC_IMG_SIZE: int = 640


# ---------------------------------------------------------------------------
# Helpers de dataset sintético (nível de módulo — facilita teste isolado)
# ---------------------------------------------------------------------------


def _make_synthetic_sample(img_path: Path, lbl_path: Path) -> None:
    """
    Gera uma imagem sintética de diagrama de arquitetura com anotações YOLO.

    Cada imagem contém 3-6 retângulos coloridos (componentes) com text labels.
    Anotações no formato YOLO: ``class_id cx cy w h`` (valores normalizados 0-1).
    """
    import cv2
    import numpy as np

    img = np.ones((_SYNTHETIC_IMG_SIZE, _SYNTHETIC_IMG_SIZE, 3), dtype=np.uint8) * 30

    n_boxes = random.randint(3, 6)
    annotations: list[str] = []
    occupied: list[tuple[int, int, int, int]] = []

    for _ in range(n_boxes):
        cls_id = random.randint(0, len(_SYNTHETIC_CLASS_NAMES) - 1)
        w = random.randint(80, 180)
        h = random.randint(50, 120)

        # Tenta posicionar sem sobreposição excessiva (até 20 tentativas)
        x1, y1, x2, y2 = 10, 10, 10 + w, 10 + h
        for _ in range(20):
            cx_try = random.randint(10, _SYNTHETIC_IMG_SIZE - w - 10)
            cy_try = random.randint(10, _SYNTHETIC_IMG_SIZE - h - 10)
            x2_try, y2_try = cx_try + w, cy_try + h
            if not any(
                not (x2_try < ox1 or cx_try > ox2 or y2_try < oy1 or cy_try > oy2)
                for ox1, oy1, ox2, oy2 in occupied
            ):
                x1, y1, x2, y2 = cx_try, cy_try, x2_try, y2_try
                break

        occupied.append((x1, y1, x2, y2))
        color = _SYNTHETIC_CLASS_COLORS[cls_id]
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            img, _SYNTHETIC_CLASS_NAMES[cls_id],
            (x1 + 4, y1 + 18),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA,
        )

        # Anotação YOLO normalizada
        cx_n = (x1 + x2) / 2 / _SYNTHETIC_IMG_SIZE
        cy_n = (y1 + y2) / 2 / _SYNTHETIC_IMG_SIZE
        nw = (x2 - x1) / _SYNTHETIC_IMG_SIZE
        nh = (y2 - y1) / _SYNTHETIC_IMG_SIZE
        annotations.append(f"{cls_id} {cx_n:.6f} {cy_n:.6f} {nw:.6f} {nh:.6f}")

    # Setas de conexão entre componentes vizinhos
    for i in range(len(occupied) - 1):
        x1a, y1a, x2a, y2a = occupied[i]
        x1b, y1b, x2b, y2b = occupied[i + 1]
        pt_a = ((x1a + x2a) // 2, (y1a + y2a) // 2)
        pt_b = ((x1b + x2b) // 2, (y1b + y2b) // 2)
        cv2.arrowedLine(img, pt_a, pt_b, (150, 150, 150), 1, tipLength=0.02)

    cv2.imwrite(str(img_path), img)
    lbl_path.write_text("\n".join(annotations))


class TrainingState:
    """Estado persistente e thread-safe do treinamento."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.is_training: bool = False
        self.current_epoch: int = 0
        self.total_epochs: int = 0
        self.loss: float = 0.0
        self.val_map: float = 0.0
        self.eta_seconds: float = 0.0
        self.status: str = "idle"
        self.error: Optional[str] = None
        self.model_path: Optional[str] = None
        self.progress_percent: float = 0.0
        self.metrics: dict = {}

    def to_dict(self) -> dict:
        return {
            "is_training": self.is_training,
            "current_epoch": self.current_epoch,
            "total_epochs": self.total_epochs,
            "loss": round(self.loss, 5),
            "val_map": round(self.val_map, 5),
            "eta_seconds": int(self.eta_seconds),
            "status": self.status,
            "error": self.error,
            "model_path": self.model_path,
            "progress_percent": round(self.progress_percent, 1),
            "metrics": self.metrics,
        }


training_state = TrainingState()


class FineTuningService:
    """Orquestração de fine-tuning YOLOv8."""

    _DEMO_DATA_YAML = "coco128.yaml"  # embutido no ultralytics, download automático

    # Datasets Roboflow Universe (workspace, project, version)
    # Requerem ROBOFLOW_API_KEY configurada. Tentados em ordem de preferência.
    _ROBOFLOW_DATASETS: list[tuple[str, str, int]] = [
        ("marcelos-workspace-1mzme", "threat-modeling-architecture", 1),
        ("cybersecurityproject", "network-components-2", 3),   # v1 inexistente
        ("architecture-communication-symbols-dataset", "architecture-symbols-dataset", 1),
    ]

    # Datasets HuggingFace como segundo fallback (formato YOLO nativo).
    # Cada entrada deve ser um repo HF do tipo "dataset" com estrutura YOLO:
    #   train/images/, train/labels/, valid/images/, valid/labels/, data.yaml
    # Candidatos confirmados com estrutura YOLO nativa:
    _HF_DATASET_CANDIDATES: list[str] = [
        # Adicionar repos HF verificados aqui quando disponíveis
    ]

    def __init__(self):
        self.models_dir = Path(settings.finetuned_models_dir)
        self.data_dir = Path(settings.training_data_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._demo_mode: bool = False
        self.dataset_source: str = ""  # "roboflow", "huggingface", "synthetic", "demo"
        self._cancel_requested: bool = False
        self._current_trainer = None  # referência ao ultralytics Trainer ativo

    # ------------------------------------------------------------------
    # Dataset — público
    # ------------------------------------------------------------------

    def use_demo_mode(self) -> None:
        """Configura modo demo (COCO128 — sem download externo necessário)."""
        self._demo_mode = True
        self.dataset_source = "demo"
        training_state.status = "idle"
        training_state.error = None
        logger.info("Modo demo ativado: COCO128")

    def use_local_dataset(self) -> bool:
        """
        Usa o dataset mergeado permanente em app/data/training.

        Retorna True se o data.yaml e as imagens existirem.
        """
        data_yaml = self.data_dir / "data.yaml"
        train_images = self.data_dir / "images" / "train"

        if not data_yaml.exists():
            training_state.error = "data.yaml não encontrado em app/data/training."
            return False

        n_train = sum(1 for _ in train_images.glob("*")) if train_images.exists() else 0
        if n_train == 0:
            training_state.error = "Nenhuma imagem de treino encontrada em app/data/training/images/train."
            return False

        self._demo_mode = False
        self.dataset_source = "local"
        training_state.status = "idle"
        training_state.error = None
        logger.info("Dataset local pronto: %d imagens de treino", n_train)
        return True

    async def download_dataset(self) -> bool:
        """
        Prepara dataset para treinamento usando cascata de fontes:

          1. Dataset local mergeado (app/data/training) — preferencial
          2. Roboflow Universe (se ``ROBOFLOW_API_KEY`` estiver configurada)
          3. HuggingFace Datasets (se ``datasets`` estiver instalado)
          4. Dataset sintético local gerado com OpenCV (fallback sempre disponível)

        Retorna True em caso de sucesso.
        """
        # Prioridade máxima: dataset local já mergeado
        if self.use_local_dataset():
            return True

        training_state.status = "download"

        if await self._try_roboflow_download():
            self.dataset_source = "roboflow"
            return True

        if await self._try_hf_download():
            self.dataset_source = "huggingface"
            return True

        logger.info("Todos os downloads falharam. Gerando dataset sintético local...")
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self._generate_synthetic_dataset
            )
            self._demo_mode = False
            self.dataset_source = "synthetic"
            training_state.error = None
            logger.info("Dataset sintético gerado com sucesso.")
            return True
        except Exception as exc:
            training_state.error = f"Erro ao gerar dataset sintético: {exc}"
            logger.error(training_state.error)
            return False

    async def download_and_merge_datasets(self) -> bool:
        """
        Baixa múltiplos datasets do Roboflow Universe e os mescla no dataset
        unificado usando o pipeline definido em ``scripts/merge_datasets.py``.

        Requer:
          - ``ROBOFLOW_API_KEY`` configurada no .env
          - Pacote ``roboflow`` instalado (``pip install roboflow``)

        Retorna True em caso de sucesso; popula ``training_state.error`` em caso
        de falha.
        """
        if not _ROBOFLOW_AVAILABLE:
            training_state.error = (
                "Pacote 'roboflow' não instalado. Execute: pip install roboflow"
            )
            logger.error(training_state.error)
            return False

        if not settings.roboflow_api_key:
            training_state.error = (
                "ROBOFLOW_API_KEY não configurada. "
                "Adicione a chave no arquivo .env para baixar os datasets."
            )
            logger.error(training_state.error)
            return False

        training_state.status = "download"
        training_state.error = None

        try:
            from scripts.merge_datasets import build_unified_dataset  # lazy import

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: build_unified_dataset(
                    api_key=settings.roboflow_api_key,
                    dry_run=False,
                ),
            )
        except Exception as exc:
            training_state.error = f"Erro no merge de datasets: {exc}"
            logger.error("download_and_merge_datasets falhou: %s", exc)
            return False

        if self.use_local_dataset():
            self.dataset_source = "local"
            return True

        training_state.error = (
            "Merge concluído, mas nenhuma imagem foi encontrada em images/train."
        )
        logger.error(training_state.error)
        return False

    # Alias para compatibilidade com chamadas existentes no router
    async def download_coco_architecture_dataset(self) -> bool:
        return await self.download_dataset()

    # ------------------------------------------------------------------
    # Dataset — privado
    # ------------------------------------------------------------------

    async def _try_roboflow_download(self) -> bool:
        """
        Tenta baixar um dataset Roboflow Universe em formato YOLOv8.

        Requer que ``roboflow`` esteja instalado e ``ROBOFLOW_API_KEY`` configurada.
        O data.yaml gerado pelo SDK é copiado para ``self.data_dir/data.yaml``
        para que o pipeline de treinamento possa utilizá-lo diretamente.
        """
        if not _ROBOFLOW_AVAILABLE:
            logger.debug("roboflow não instalado. Pulando Roboflow.")
            return False

        if not settings.roboflow_api_key:
            logger.info("ROBOFLOW_API_KEY não configurada. Pulando Roboflow.")
            return False

        try:
            rf = Roboflow(api_key=settings.roboflow_api_key)
        except Exception as exc:
            logger.warning("Falha ao inicializar Roboflow SDK: %s", exc)
            return False

        for workspace_slug, project_slug, version_num in self._ROBOFLOW_DATASETS:
            try:
                logger.info(
                    "Tentando Roboflow: %s/%s v%d", workspace_slug, project_slug, version_num
                )
                # IMPORTANTE: NÃO criar o diretório antes do download.
                # O SDK Roboflow verifica se a pasta já existe e, se estiver vazia,
                # pula o download silenciosamente (bug do SDK).
                download_dir = (self.data_dir / "roboflow_download").resolve()
                if download_dir.exists():
                    shutil.rmtree(download_dir)  # garante download limpo

                project = rf.workspace(workspace_slug).project(project_slug)
                version = project.version(version_num)
                version.download("yolov8", location=str(download_dir), overwrite=True)

                # SDK cria data.yaml diretamente em download_dir (não em subdiretório)
                yaml_path = download_dir / "data.yaml"
                if not yaml_path.exists():
                    yaml_candidates = list(download_dir.rglob("*.yaml"))
                    if yaml_candidates:
                        yaml_path = yaml_candidates[0]
                    else:
                        all_files = list(download_dir.rglob("*"))
                        logger.warning(
                            "Nenhum .yaml encontrado em %s. Arquivos: %s",
                            download_dir,
                            [str(f.relative_to(download_dir)) for f in all_files[:20]] or "(vazio)",
                        )
                        continue

                # O SDK gera paths relativos (../train/images) que só funcionam
                # se o yaml estiver dentro do download_dir. Reescrevemos com
                # caminhos absolutos para que o yaml possa ser copiado livremente.
                yaml_content = yaml_path.read_text()
                train_path = download_dir / "train" / "images"
                val_path = (
                    download_dir / "valid" / "images"       # Roboflow usa "valid"
                    if (download_dir / "valid").exists()
                    else download_dir / "val" / "images"
                )
                test_path = (
                    download_dir / "test" / "images"
                    if (download_dir / "test").exists()
                    else val_path
                )
                yaml_content = re.sub(r"^train:.*$", f"train: {train_path}", yaml_content, flags=re.MULTILINE)
                yaml_content = re.sub(r"^val:.*$",   f"val: {val_path}",   yaml_content, flags=re.MULTILINE)
                yaml_content = re.sub(r"^test:.*$",  f"test: {test_path}",  yaml_content, flags=re.MULTILINE)
                # Remove ou substitui a chave "path:" se presente (evita conflito)
                yaml_content = re.sub(r"^path:.*\n?", "", yaml_content, flags=re.MULTILINE)

                (self.data_dir / "data.yaml").write_text(yaml_content)
                self._demo_mode = False

                n_train = sum(1 for _ in train_path.glob("*") if train_path.exists())
                logger.info(
                    "Roboflow: %s/%s baixado (%d imagens de treino)",
                    workspace_slug, project_slug, n_train,
                )
                return True

            except Exception as exc:
                logger.warning(
                    "Roboflow '%s/%s' falhou: %s", workspace_slug, project_slug, exc
                )

        return False

    async def _try_hf_download(self) -> bool:
        """
        Tenta baixar datasets do HuggingFace Hub no formato YOLO nativo.

        Usa ``huggingface_hub.snapshot_download`` para obter os arquivos de imagem
        e anotações diretamente no disco, ao contrário de ``load_dataset`` que retorna
        apenas objetos Python sem criar os arquivos necessários para treinamento YOLO.

        Os candidatos em ``_HF_DATASET_CANDIDATES`` devem ser repositórios HF do tipo
        ``dataset`` com estrutura YOLO (train/images, train/labels, data.yaml).
        """
        try:
            from huggingface_hub import snapshot_download as hf_snapshot
        except ImportError:
            logger.warning("huggingface_hub não instalado; pulando fallback HF.")
            return False

        for dataset_id in self._HF_DATASET_CANDIDATES:
            try:
                logger.info("Tentando download HF (snapshot): %s", dataset_id)
                hf_dir = Path(
                    hf_snapshot(
                        repo_id=dataset_id,
                        repo_type="dataset",
                        local_dir=str(self.data_dir / "hf_download"),
                        ignore_patterns=["*.parquet", "*.arrow", "*.json", "*.csv"],
                    )
                )

                yaml_candidates = list(hf_dir.rglob("data.yaml"))
                if not yaml_candidates:
                    logger.warning("HF '%s': nenhum data.yaml encontrado.", dataset_id)
                    continue

                yaml_content = yaml_candidates[0].read_text()
                # Reescreve paths relativos com caminhos absolutos (mesmo padrão Roboflow)
                for split_key, folder in [("train", "train"), ("val", "valid"), ("val", "val"), ("test", "test")]:
                    split_dir = hf_dir / folder / "images"
                    if split_dir.exists():
                        yaml_content = re.sub(
                            rf"^{split_key}:.*$", f"{split_key}: {split_dir}",
                            yaml_content, flags=re.MULTILINE,
                        )
                yaml_content = re.sub(r"^path:.*\n?", "", yaml_content, flags=re.MULTILINE)
                (self.data_dir / "data.yaml").write_text(yaml_content)
                self._demo_mode = False
                logger.info("Dataset HF baixado: %s", dataset_id)
                return True
            except Exception as exc:
                logger.warning("Dataset HF '%s' indisponível: %s", dataset_id, exc)

        return False

    def _generate_synthetic_dataset(self, n_train: int = 60, n_val: int = 15) -> None:
        """
        Gera dataset sintético local no formato YOLO com anotações automáticas.

        Usa :func:`_make_synthetic_sample` para cada imagem e cria o data.yaml
        correspondente com as 8 classes de componentes de arquitetura.
        """
        splits = {"train": n_train, "val": n_val}
        for split, n in splits.items():
            img_dir = self.data_dir / "images" / split
            lbl_dir = self.data_dir / "labels" / split
            img_dir.mkdir(parents=True, exist_ok=True)
            lbl_dir.mkdir(parents=True, exist_ok=True)
            for i in range(n):
                _make_synthetic_sample(
                    img_dir / f"synth_{i:04d}.jpg",
                    lbl_dir / f"synth_{i:04d}.txt",
                )

        logger.info(
            "Dataset sintético: %d treino + %d validação em %s",
            n_train, n_val, self.data_dir,
        )

    async def prepare_dataset_structure(self) -> bool:
        """
        Cria estrutura de diretórios YOLO e data.yaml para treinamento.

        Se ``data.yaml`` já existir (ex: gerado por download Roboflow/HF),
        apenas garante que os diretórios estão presentes.
        """
        try:
            training_state.status = "preparing"
            dirs = [
                self.data_dir / "images" / "train",
                self.data_dir / "images" / "val",
                self.data_dir / "images" / "test",
                self.data_dir / "labels" / "train",
                self.data_dir / "labels" / "val",
                self.data_dir / "labels" / "test",
            ]
            for d in dirs:
                d.mkdir(parents=True, exist_ok=True)

            data_yaml = self.data_dir / "data.yaml"
            if not data_yaml.exists():
                # data.yaml padrão para dataset sintético (8 classes)
                names_block = "\n".join(
                    f"  {i}: {name}" for i, name in enumerate(_SYNTHETIC_CLASS_NAMES)
                )
                data_yaml.write_text(
                    f"path: {self.data_dir.absolute()}\n"
                    "train: images/train\n"
                    "val: images/val\n"
                    "test: images/test\n\n"
                    f"nc: {len(_SYNTHETIC_CLASS_NAMES)}\n"
                    f"names:\n{names_block}\n"
                )
                logger.info("data.yaml criado com classes sintéticas padrão em %s", data_yaml)
            else:
                logger.info("data.yaml existente preservado em %s", data_yaml)

            return True

        except Exception as exc:
            training_state.error = f"Erro ao preparar dataset: {exc}"
            logger.error(training_state.error)
            return False

    # ------------------------------------------------------------------
    # Fine-tuning com streaming real por época
    # ------------------------------------------------------------------

    def get_resumable_checkpoint(self) -> Optional[Path]:
        """
        Retorna o ``last.pt`` mais recente de um run anterior, ou None.

        Busca recursivamente em ``models_dir/runs/**/weights/last.pt``
        e ordena por data de modificação (mais recente primeiro).
        """
        runs_dir = self.models_dir / "runs"
        if not runs_dir.exists():
            return None
        checkpoints = sorted(
            runs_dir.rglob("weights/last.pt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return checkpoints[0] if checkpoints else None

    async def start_finetuning(
        self,
        epochs: int = 100,
        batch_size: int = 8,
        img_size: int = 640,
        patience: int = 20,
        workers: int = 4,
        demo: bool = False,
        resume: bool = False,
    ) -> AsyncIterator[dict]:
        """
        Inicia fine-tuning do YOLOv8 e emite atualizações por época via async generator.

        Usa ThreadPoolExecutor para não bloquear o event loop.
        Usa callbacks YOLO para capturar métricas por época.
        """
        if not _ULTRALYTICS_AVAILABLE:
            training_state.error = (
                "ultralytics não instalado. Execute: pip install 'ultralytics>=8.3.0'"
            )
            training_state.status = "error"
            yield training_state.to_dict()
            return

        if training_state.is_training:
            training_state.error = "Treinamento já em andamento"
            yield training_state.to_dict()
            return

        # Para resume: localizar checkpoint antes de qualquer outra verificação
        resume_checkpoint: Optional[Path] = None
        if resume:
            resume_checkpoint = self.get_resumable_checkpoint()
            if resume_checkpoint is None:
                training_state.error = (
                    "Nenhum checkpoint de retomada encontrado. "
                    "Inicie um novo treinamento primeiro."
                )
                training_state.status = "error"
                yield training_state.to_dict()
                return
            logger.info("Retomando treinamento a partir de: %s", resume_checkpoint)

        # Decidir qual dataset usar (apenas necessário para novos treinamentos)
        use_demo = demo or self._demo_mode
        data_yaml: str

        if not resume:
            if use_demo:
                data_yaml = self._DEMO_DATA_YAML  # ultralytics baixa automaticamente
                logger.info("Usando dataset demo (COCO128)")
            else:
                custom_yaml = self.data_dir / "data.yaml"
                if not custom_yaml.exists():
                    training_state.error = (
                        "data.yaml não encontrado. "
                        "Baixe o dataset ou use o Modo Demo (COCO128)."
                    )
                    training_state.status = "error"
                    yield training_state.to_dict()
                    return
                data_yaml = str(custom_yaml)
        else:
            data_yaml = ""  # YOLO lê do args.yaml salvo no checkpoint

        # Preparar estado inicial
        self._cancel_requested = False
        self._current_trainer = None
        training_state.is_training = True
        training_state.status = "training"
        training_state.total_epochs = epochs
        training_state.current_epoch = 0
        training_state.loss = 0.0
        training_state.val_map = 0.0
        training_state.eta_seconds = 0.0
        training_state.progress_percent = 0.0
        training_state.error = None
        training_state.model_path = None
        training_state.metrics = {}

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        start_time = time.monotonic()
        start_epoch_ref: list[int] = [0]  # época inicial (>0 quando retomando)

        # --- Callback: captura referência ao trainer ao iniciar ---
        def on_train_start(trainer) -> None:
            self._current_trainer = trainer
            start_epoch_ref[0] = getattr(trainer, "epoch", 0)  # epoch pode não existir ainda em on_train_start
            # Atualiza total de épocas a partir do trainer (preciso em resume)
            t_total = getattr(getattr(trainer, "args", None), "epochs", None)
            if t_total:
                training_state.total_epochs = int(t_total)

        # --- Callback executado na thread de treinamento ---
        def on_epoch_end(trainer) -> None:
            # Verificar se cancelamento foi solicitado
            if self._cancel_requested:
                trainer.stop = True
                return

            epoch_1 = trainer.epoch + 1  # epoch é 0-indexed no ultralytics
            t_total = int(getattr(getattr(trainer, "args", None), "epochs", None) or training_state.total_epochs)

            # Detecta época de início na primeira chamada (resume começa em epoch > 1)
            if start_epoch_ref[0] == 0 and epoch_1 > 1:
                start_epoch_ref[0] = epoch_1 - 1

            # Loss: em ultralytics recentes tloss é tensor multi-elemento [box, cls, dfl]
            # Usar .mean() para obter um escalar antes de converter para float
            try:
                t = trainer.tloss
                if t is None:
                    loss_val = 0.0
                elif hasattr(t, "mean"):
                    loss_val = float(t.mean())
                else:
                    loss_val = float(t)
            except (TypeError, RuntimeError, ValueError):
                loss_val = 0.0

            # mAP: primeira chave disponível no dict de métricas
            val_map_val = 0.0
            if trainer.metrics:
                for key in ("metrics/mAP50(B)", "metrics/mAP50", "mAP50(B)", "mAP50"):
                    if key in trainer.metrics:
                        val_map_val = float(trainer.metrics[key])
                        break

            # ETA estimado — usa apenas épocas desta sessão para cálculo preciso em resume
            elapsed = time.monotonic() - start_time
            epoch_in_session = epoch_1 - start_epoch_ref[0]
            if epoch_in_session > 0:
                time_per_epoch = elapsed / epoch_in_session
                remaining = max(0, t_total - epoch_1)
                eta = remaining * time_per_epoch
            else:
                eta = 0.0

            training_state.total_epochs = t_total
            training_state.current_epoch = epoch_1
            training_state.loss = loss_val
            training_state.val_map = val_map_val
            training_state.eta_seconds = eta
            training_state.progress_percent = (epoch_1 / t_total) * 100 if t_total > 0 else 0.0
            training_state.metrics = {k: float(v) for k, v in (trainer.metrics or {}).items()}

            # Enviar snapshot para a fila de forma thread-safe
            loop.call_soon_threadsafe(queue.put_nowait, training_state.to_dict())

        # --- Função executada no executor ---
        training_error: list[Optional[Exception]] = [None]
        best_model_path: list[Optional[Path]] = [None]

        def run_training() -> None:
            try:
                if resume and resume_checkpoint is not None:
                    # Retomar treinamento: YOLO lê hiperparâmetros do args.yaml salvo
                    model = YOLO(str(resume_checkpoint))
                    model.add_callback("on_train_start", on_train_start)
                    model.add_callback("on_train_epoch_end", on_epoch_end)
                    results = model.train(resume=True)
                else:
                    model = YOLO("yolov8n.pt")
                    model.add_callback("on_train_start", on_train_start)
                    model.add_callback("on_train_epoch_end", on_epoch_end)

                    run_name = f"stride_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    results = model.train(
                        data=data_yaml,
                        epochs=epochs,
                        imgsz=img_size,
                        batch=batch_size,
                        patience=patience,
                        workers=workers,  # limitar workers para evitar OOM
                        device="",        # auto-detect GPU/CPU
                        amp=True,         # mixed precision FP16 — ~2x speedup em GPU
                        save=True,
                        save_period=-1,   # salvar apenas best/last
                        val=True,
                        verbose=False,    # quieto — métricas chegam via callback
                        project=str(self.models_dir.resolve() / "runs"),
                        name=run_name,
                        exist_ok=True,
                    )

                # Localizar best.pt usando o save_dir real do trainer
                save_dir: Path | None = None
                if hasattr(model, "trainer") and model.trainer is not None:
                    save_dir = Path(model.trainer.save_dir)
                elif hasattr(results, "save_dir"):
                    save_dir = Path(str(results.save_dir))

                if save_dir:
                    best = save_dir / "weights" / "best.pt"
                    if best.exists():
                        best_model_path[0] = best
                    else:
                        # Fallback: last.pt se best não existir
                        last = save_dir / "weights" / "last.pt"
                        if last.exists():
                            best_model_path[0] = last
                elif hasattr(results, "best") and results.best:
                    best_model_path[0] = Path(str(results.best))

            except Exception as exc:
                training_error[0] = exc
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinela

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yolo_train")
        future = loop.run_in_executor(executor, run_training)

        # Emitir estado inicial imediatamente
        yield training_state.to_dict()

        # Consumir atualizações da fila até o sentinela
        try:
            while True:
                item = await queue.get()
                if item is None:  # sentinela: treinamento terminou
                    break
                yield item
        finally:
            training_state.is_training = False
            self._current_trainer = None
            executor.shutdown(wait=False)

        # Propagar exceção do thread se houver
        await asyncio.shield(future)
        if training_error[0]:
            training_state.status = "error"
            training_state.error = str(training_error[0])
            logger.error("Erro durante treinamento: %s", training_error[0], exc_info=True)
            yield training_state.to_dict()
            return

        # Se cancelamento foi solicitado, não sobrescrever status com "completed"
        if self._cancel_requested:
            training_state.status = "cancelled"
            training_state.error = "Treinamento cancelado pelo usuário"
            yield training_state.to_dict()
            return

        # Copiar modelo treinado para models_dir com nome padronizado
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_name = f"yolov8_stride_{timestamp}.pt"
        dest_path = self.models_dir / dest_name

        if best_model_path[0] and best_model_path[0].exists():
            shutil.copy2(best_model_path[0], dest_path)
            training_state.model_path = str(dest_path)
            logger.info("Modelo salvo em %s", dest_path)
        else:
            logger.warning("best.pt não encontrado; modelo pode estar em runs/")

        training_state.status = "completed"
        training_state.current_epoch = training_state.total_epochs
        training_state.progress_percent = 100.0
        yield training_state.to_dict()

    # ------------------------------------------------------------------
    # Gerenciamento de modelos
    # ------------------------------------------------------------------

    def get_training_status(self) -> dict:
        return training_state.to_dict()

    def cancel_training(self) -> dict:
        if training_state.is_training:
            self._cancel_requested = True
            training_state.is_training = False
            training_state.status = "cancelled"
            training_state.error = "Treinamento cancelado pelo usuário"
            # Para o trainer diretamente se já estiver ativo
            if self._current_trainer is not None:
                try:
                    self._current_trainer.stop = True
                except Exception:
                    pass
            logger.info("Treinamento cancelado")
        return training_state.to_dict()

    def get_available_models(self) -> list[dict]:
        models = []
        for f in sorted(self.models_dir.glob("*.pt"), key=lambda p: p.stat().st_ctime, reverse=True):
            models.append({
                "filename": f.name,
                "path": str(f),
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                "created": datetime.fromtimestamp(f.stat().st_ctime).isoformat(),
            })
        return models

    def load_finetuned_model(self, model_filename: str):
        if not _ULTRALYTICS_AVAILABLE:
            return None
        model_path = self.models_dir / model_filename
        if not model_path.exists():
            logger.error("Modelo não encontrado: %s", model_path)
            return None
        try:
            return YOLO(str(model_path))
        except Exception as e:
            logger.error("Erro ao carregar modelo: %s", e)
            return None

    def delete_model(self, model_filename: str) -> bool:
        model_path = self.models_dir / model_filename
        if not model_path.exists():
            return False
        try:
            model_path.unlink()
            logger.info("Modelo deletado: %s", model_path)
            return True
        except Exception as e:
            logger.error("Erro ao deletar: %s", e)
            return False


finetuning_service = FineTuningService()
