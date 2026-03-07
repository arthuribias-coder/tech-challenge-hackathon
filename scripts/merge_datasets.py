#!/usr/bin/env python3
"""
Script de Merge de Datasets — STRIDE Threat Modeler

Baixa datasets complementares do Roboflow Universe e os mescla com o dataset
existente, remapeando classes para o schema canônico do projeto.

Datasets adicionados:
  - network-components (cybersecurityproject): Client, Database, Firewall, Router, Server, WebServer
  - azure-components   (janani-b-k2d2e)      : Web Application, Oracle DB, PostgreSQL DB, File Share, Firewall
  - three-tier-architecture (janani-b-k2d2e) : Client, Database, Server, WebServer

Schema canônico (classes do projeto):
  0: API
  1: Database
  2: ExternalSystem
  3: Queue
  4: Service
  5: Storage
  6: User
  7: WebServer

Uso:
  python scripts/merge_datasets.py [--dry-run]
"""

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

# Adiciona raiz do projeto ao path para importar config
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "app" / "data" / "training"
DEST_TRAIN_IMAGES = DATA_DIR / "images" / "train"
DEST_TRAIN_LABELS = DATA_DIR / "labels" / "train"
DEST_VAL_IMAGES   = DATA_DIR / "images" / "val"
DEST_VAL_LABELS   = DATA_DIR / "labels" / "val"
DOWNLOADS_DIR     = DATA_DIR / "extra_downloads"

# Classes canônicas do projeto
CANONICAL_CLASSES = [
    "API",           # 0
    "Database",      # 1
    "ExternalSystem",# 2
    "Queue",         # 3
    "Service",       # 4
    "Storage",       # 5
    "User",          # 6
    "WebServer",     # 7
]

CANONICAL_INDEX = {c.lower(): i for i, c in enumerate(CANONICAL_CLASSES)}

# ---------------------------------------------------------------------------
# Mapeamento de classes por dataset
# Formato: { "nome_da_classe_original": "nome_canônico" | None }
# None = ignorar (não incluir a anotação)
# ---------------------------------------------------------------------------

DATASET_CLASS_MAP: dict = {
    "network-components": {
        "client":    "User",
        "database":  "Database",
        "firewall":  "Service",
        "router":    "Service",
        "server":    "Service",
        "webserver": "WebServer",
    },
    "network-components-2": {
        "client":    "User",
        "database":  "Database",
        "firewall":  "Service",
        "router":    "Service",
        "server":    "Service",
        "webserver": "WebServer",
    },
    "azure-components": {
        "application gateway":        "WebServer",
        "azure active directory":     "Service",
        "azure key vault":            "Storage",
        "azure monitor":              "Service",
        "azure v-net":                "Service",
        "file share":                 "Storage",
        "firewall":                   "Service",
        "microsoftazure":             None,         # logo genérico — ignorar
        "oracle db":                  "Database",
        "postgresql db":              "Database",
        "vm scale set":               "Service",
        "web application":            "WebServer",
    },
    "three-tier-architecture": {
        "client":         "User",
        "database":       "Database",
        "server":         "Service",
        "internetserver": "ExternalSystem",
        "three-tier":     None,
        "webserver":      "WebServer",
    },
}

# Configuração dos datasets a baixar
# workspace/project/version  (versão mais recente disponível publicamente)
DATASETS_TO_DOWNLOAD = [
    {
        "workspace": "cybersecurityproject",
        "project":   "network-components",
        "version":   12,
        "map_key":   "network-components",
    },
    {
        "workspace": "cybersecurityproject",
        "project":   "network-components-2",
        "version":   12,
        "map_key":   "network-components-2",
    },
    {
        "workspace": "janani-b-k2d2e",
        "project":   "azure-components",
        "version":   25,
        "map_key":   "azure-components",
    },
    {
        "workspace": "janani-b-k2d2e",
        "project":   "three-tier-architecture",
        "version":   1,
        "map_key":   "three-tier-architecture",
    },
]

# ---------------------------------------------------------------------------
# Cores para output
# ---------------------------------------------------------------------------

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def log_ok(msg: str)   -> None: print(f"{GREEN}✓{RESET} {msg}")
def log_err(msg: str)  -> None: print(f"{RED}✗{RESET} {msg}")
def log_warn(msg: str) -> None: print(f"{YELLOW}⚠{RESET} {msg}")
def log_info(msg: str) -> None: print(f"{BLUE}→{RESET} {msg}")


# ---------------------------------------------------------------------------
# Funções utilitárias
# ---------------------------------------------------------------------------

def load_yaml_classes(yaml_path: Path) -> list[str]:
    """Lê a lista de classes de um data.yaml sem depender de PyYAML."""
    classes: list[str] = []
    inside_names = False
    with open(yaml_path) as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("names:"):
                inside_names = True
                continue
            if inside_names:
                if stripped.startswith("- "):
                    classes.append(stripped[2:].strip())
                elif stripped and not stripped.startswith("#"):
                    inside_names = False
    return classes


def remap_label_file(
    src_label: Path,
    dst_label: Path,
    src_classes: list,
    class_map: dict,
    dry_run: bool = False,
) -> tuple:
    """
    Lê src_label (YOLO format), remapeia class_ids e grava em dst_label.

    Retorna (linhas_mantidas, linhas_ignoradas).
    """
    kept = 0
    skipped = 0
    out_lines: list[str] = []

    with open(src_label) as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            old_id = int(parts[0])
            if old_id >= len(src_classes):
                skipped += 1
                continue

            original_name    = src_classes[old_id].lower()
            canonical_name   = class_map.get(original_name)

            if canonical_name is None:
                skipped += 1
                continue

            new_id = CANONICAL_INDEX.get(canonical_name.lower())
            if new_id is None:
                skipped += 1
                continue

            out_lines.append(f"{new_id} " + " ".join(parts[1:]))
            kept += 1

    if not dry_run and out_lines:
        dst_label.parent.mkdir(parents=True, exist_ok=True)
        with open(dst_label, "w") as f:
            f.write("\n".join(out_lines) + "\n")

    return kept, skipped


def copy_with_remap(
    src_images_dir: Path,
    src_labels_dir: Path,
    dst_images_dir: Path,
    dst_labels_dir: Path,
    src_classes: list,
    class_map: dict,
    prefix: str,
    dry_run: bool = False,
) -> tuple:
    """Copia imagens e labels remapeados para os diretórios de destino."""
    images_copied = 0
    labels_with_annotations = 0

    if not src_images_dir.exists():
        log_warn(f"Diretório não encontrado: {src_images_dir}")
        return 0, 0

    dst_images_dir.mkdir(parents=True, exist_ok=True)
    dst_labels_dir.mkdir(parents=True, exist_ok=True)

    for img_path in src_images_dir.iterdir():
        if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp"}:
            continue

        label_path = src_labels_dir / (img_path.stem + ".txt")
        if not label_path.exists():
            continue

        dst_img  = dst_images_dir / f"{prefix}_{img_path.name}"
        dst_lbl  = dst_labels_dir / f"{prefix}_{img_path.stem}.txt"

        kept, _ = remap_label_file(label_path, dst_lbl, src_classes, class_map, dry_run)

        if kept > 0:
            if not dry_run:
                shutil.copy2(img_path, dst_img)
            images_copied += 1
            labels_with_annotations += 1

    return images_copied, labels_with_annotations


def copy_existing_dataset(dry_run: bool = False) -> int:
    """Copia o dataset já baixado (roboflow_download) para a estrutura unificada."""
    src_base = DATA_DIR / "roboflow_download"
    yaml_path = src_base / "data.yaml"

    if not yaml_path.exists():
        log_warn("Dataset existente não encontrado, pulando.")
        return 0

    src_classes = load_yaml_classes(yaml_path)
    # Dataset existente usa exatamente o schema canônico — mapeamento 1:1
    identity_map = {c.lower(): c for c in src_classes}

    total = 0
    for split, dst_img, dst_lbl in [
        ("train", DEST_TRAIN_IMAGES, DEST_TRAIN_LABELS),
        ("valid", DEST_VAL_IMAGES,   DEST_VAL_LABELS),
    ]:
        src_imgs  = src_base / split / "images"
        src_lbls  = src_base / split / "labels"
        copied, _ = copy_with_remap(
            src_imgs, src_lbls, dst_img, dst_lbl,
            src_classes, identity_map, prefix=f"orig_{split}",
            dry_run=dry_run,
        )
        total += copied
        log_ok(f"Dataset existente [{split}]: {copied} imagens copiadas")

    return total


# ---------------------------------------------------------------------------
# Download via Roboflow SDK
# ---------------------------------------------------------------------------

def download_dataset(
    workspace: str,
    project: str,
    version: int,
    dest_dir: Path,
    api_key: str,
    dry_run: bool = False,
) -> Optional[Path]:
    """Baixa um dataset do Roboflow Universe em formato YOLOv8."""
    try:
        from roboflow import Roboflow  # lazy import
    except ImportError:
        log_err("Pacote 'roboflow' não instalado. Execute: pip install roboflow")
        return None

    target_dir = dest_dir / f"{workspace}__{project}_v{version}"
    if target_dir.exists():
        log_warn(f"Já baixado anteriormente: {target_dir.name}")
        return target_dir

    if dry_run:
        log_info(f"[DRY RUN] Baixaria {workspace}/{project} v{version}")
        return None

    log_info(f"Baixando {workspace}/{project} v{version} ...")
    try:
        rf       = Roboflow(api_key=api_key)
        proj     = rf.workspace(workspace).project(project)
        dataset  = proj.version(version).download("yolov8", location=str(target_dir))
        log_ok(f"Download concluído: {target_dir.name}")
        return target_dir
    except Exception as e:
        log_err(f"Falha ao baixar {workspace}/{project}: {e}")
        return None


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def build_unified_dataset(api_key: str, dry_run: bool = False) -> None:
    print(f"\n{BOLD}=== Merge de Datasets — STRIDE Threat Modeler ==={RESET}\n")

    if dry_run:
        print(f"{YELLOW}[DRY RUN] Nenhum arquivo será alterado.{RESET}\n")

    # 1. Cria diretórios de destino
    for d in [DEST_TRAIN_IMAGES, DEST_TRAIN_LABELS, DEST_VAL_IMAGES, DEST_VAL_LABELS]:
        if not dry_run:
            d.mkdir(parents=True, exist_ok=True)

    total_images = 0

    # 2. Copia dataset original
    log_info("Processando dataset existente (threat-modeling-architecture)...")
    total_images += copy_existing_dataset(dry_run)

    # 3. Baixa e mescla datasets adicionais
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    for ds in DATASETS_TO_DOWNLOAD:
        print()
        log_info(f"Processando {ds['workspace']}/{ds['project']} ...")

        dl_path = download_dataset(
            workspace=ds["workspace"],
            project=ds["project"],
            version=ds["version"],
            dest_dir=DOWNLOADS_DIR,
            api_key=api_key,
            dry_run=dry_run,
        )

        if dl_path is None:
            continue

        yaml_path = dl_path / "data.yaml"
        if not yaml_path.exists():
            # Tenta encontrar yaml em subdiretório
            yamlfiles = list(dl_path.rglob("data.yaml"))
            if yamlfiles:
                yaml_path = yamlfiles[0]
            else:
                log_err(f"data.yaml não encontrado em {dl_path}")
                continue

        src_classes = load_yaml_classes(yaml_path)
        class_map   = DATASET_CLASS_MAP[ds["map_key"]]
        prefix      = ds["project"].replace("-", "_")

        # Detecta estrutura train/valid ou train/test/val
        for split, dst_img, dst_lbl in [
            ("train", DEST_TRAIN_IMAGES, DEST_TRAIN_LABELS),
            ("valid", DEST_VAL_IMAGES,   DEST_VAL_LABELS),
            ("val",   DEST_VAL_IMAGES,   DEST_VAL_LABELS),
        ]:
            base_candidates = [
                dl_path / split,
                yaml_path.parent / split,
            ]
            for base in base_candidates:
                src_imgs = base / "images"
                src_lbls = base / "labels"
                if src_imgs.exists():
                    copied, _ = copy_with_remap(
                        src_imgs, src_lbls, dst_img, dst_lbl,
                        src_classes, class_map,
                        prefix=f"{prefix}_{split}",
                        dry_run=dry_run,
                    )
                    if copied:
                        total_images += copied
                        log_ok(f"  [{split}] {copied} imagens incorporadas")
                    break

    # 4. Gera data.yaml unificado
    unified_yaml = DATA_DIR / "data.yaml"
    yaml_content = (
        f"path: {DATA_DIR}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: {len(CANONICAL_CLASSES)}\n"
        "names:\n"
        + "".join(f"  - {c}\n" for c in CANONICAL_CLASSES)
    )

    if not dry_run:
        unified_yaml.write_text(yaml_content)
        log_ok(f"data.yaml unificado gravado em {unified_yaml}")
    else:
        log_info("[DRY RUN] data.yaml que seria gravado:")
        print(yaml_content)

    # 5. Resumo final
    print(f"\n{BOLD}{'=' * 50}{RESET}")
    print(f"{BOLD}Total de imagens no dataset unificado: {total_images}{RESET}")
    if not dry_run:
        train_count = len(list(DEST_TRAIN_IMAGES.glob("*.*"))) if DEST_TRAIN_IMAGES.exists() else 0
        val_count   = len(list(DEST_VAL_IMAGES.glob("*.*")))   if DEST_VAL_IMAGES.exists()   else 0
        print(f"  Treino:   {train_count} imagens")
        print(f"  Validação: {val_count} imagens")
        print(f"\n{GREEN}Dataset unificado pronto em: {DATA_DIR}{RESET}")
        print(f"\nPróximo passo — retreinar com o novo dataset:")
        print(f"  data:       {unified_yaml}")
        print(f"  img size:   1280")
        print(f"  epochs:     300")
        print(f"  patience:   50")
    print(f"{BOLD}{'=' * 50}{RESET}\n")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Merge de datasets do Roboflow Universe")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem gravar arquivos")
    parser.add_argument("--api-key", help="Roboflow API key (padrão: variável ROBOFLOW_API_KEY)")
    args = parser.parse_args()

    api_key = args.api_key or os.getenv("ROBOFLOW_API_KEY")
    if not api_key:
        log_err("ROBOFLOW_API_KEY não definida. Use --api-key ou defina a variável de ambiente.")
        sys.exit(1)

    build_unified_dataset(api_key=api_key, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
