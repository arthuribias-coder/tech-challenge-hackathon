#!/usr/bin/env python3
"""
Script de Verificação: Fine-tuning System Health Check

Valida se todos os componentes necessários estão instalados e funcionando.
Execute antes de usar o sistema de fine-tuning.

Uso:
  python scripts/check_finetuning.py
"""

import sys
from pathlib import Path

# Cores para output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def check_module(module_name: str, package_name: str = None, optional: bool = False) -> bool:
    """Verifica se módulo está instalado."""
    pkg = package_name or module_name
    try:
        __import__(module_name)
        status = f"{GREEN}✓{RESET}"
        print(f"{status} {pkg:<25} instalado")
        return True
    except ImportError:
        status = f"{RED}✗{RESET}" if not optional else f"{YELLOW}⚠{RESET}"
        level = "ERRO" if not optional else "AVISO"
        print(f"{status} {pkg:<25} {level}: não instalado")
        return optional


def check_directory(path: str, create: bool = False) -> bool:
    """Verifica/cria diretório."""
    p = Path(path)
    if p.exists():
        print(f"{GREEN}✓{RESET} {path:<40} existe")
        return True
    elif create:
        try:
            p.mkdir(parents=True, exist_ok=True)
            print(f"{GREEN}✓{RESET} {path:<40} criado")
            return True
        except Exception as e:
            print(f"{RED}✗{RESET} {path:<40} erro ao criar: {e}")
            return False
    else:
        print(f"{YELLOW}⚠{RESET} {path:<40} não existe")
        return False


def main():
    print(f"\n{BOLD}=== STRIDE Threat Modeler - Fine-tuning Health Check ==={RESET}\n")

    all_ok = True

    # ========================================================================
    # 1. Verificar Módulos Obrigatórios
    # ========================================================================
    print(f"{BOLD}1. Módulos Obrigatórios:{RESET}")
    obrigatorios = [
        ("fastapi", "FastAPI"),
        ("uvicorn", "Uvicorn"),
        ("pydantic", "Pydantic"),
        ("langchain_core", "LangChain"),
    ]
    for mod, name in obrigatorios:
        if not check_module(mod, name):
            all_ok = False

    # ========================================================================
    # 2. Verificar Módulos Opcionais (Fine-tuning)
    # ========================================================================
    print(f"\n{BOLD}2. Módulos de Fine-tuning:{RESET}")
    opcionais = [
        ("ultralytics", "ultralytics (YOLO)"),
        ("datasets", "Hugging Face datasets"),
        ("pyarrow", "PyArrow"),
    ]
    for mod, name in opcionais:
        check_module(mod, name, optional=True)

    # ========================================================================
    # 3. Verificar Diretórios
    # ========================================================================
    print(f"\n{BOLD}3. Estrutura de Diretórios:{RESET}")
    dirs_to_check = [
        ("app", False),
        ("app/models", True),
        ("app/models/finetuned", True),
        ("app/data/training", True),
        ("static", False),
        ("uploads", True),
    ]
    for d, create in dirs_to_check:
        if not check_directory(d, create):
            if not create:
                all_ok = False

    # ========================================================================
    # 4. Verificar Arquivos Críticos
    # ========================================================================
    print(f"\n{BOLD}4. Arquivos Críticos:{RESET}")
    files_to_check = [
        "app/main.py",
        "app/config.py",
        "app/services/finetuning_service.py",
        "app/routers/training.py",
        "app/templates/training.html",
        "app/nodes/yolo_detector.py",
        "static/js/training.js",
        "requirements.txt",
    ]
    for f in files_to_check:
        p = Path(f)
        if p.exists():
            print(f"{GREEN}✓{RESET} {f:<50} existe")
        else:
            print(f"{RED}✗{RESET} {f:<50} não encontrado")
            all_ok = False

    # ========================================================================
    # 5. Verificar Configuração
    # ========================================================================
    print(f"\n{BOLD}5. Configuração:{RESET}")
    try:
        from app.config import settings
        
        print(f"{GREEN}✓{RESET} Settings carregado")
        print(f"  - Debug: {settings.debug}")
        print(f"  - Models dir: {settings.finetuned_models_dir}")
        print(f"  - Training data dir: {settings.training_data_dir}")
        print(f"  - YOLO epochs padrão: {settings.yolo_default_epochs}")
    except Exception as e:
        print(f"{RED}✗{RESET} Erro ao carregar settings: {e}")
        all_ok = False

    # ========================================================================
    # 6. Verificar Importações Críticas
    # ========================================================================
    print(f"\n{BOLD}6. Importações Críticas:{RESET}")
    imports_to_check = [
        ("app.services.finetuning_service", "FineTuningService"),
        ("app.routers.training", "router"),
        ("app.nodes.yolo_detector", "_load_finetuned_model"),
    ]
    for module, attr in imports_to_check:
        try:
            mod = __import__(module, fromlist=[attr])
            getattr(mod, attr)
            print(f"{GREEN}✓{RESET} {module}.{attr}")
        except Exception as e:
            print(f"{RED}✗{RESET} {module}.{attr}: {e}")
            all_ok = False

    # ========================================================================
    # 7. Resumo
    # ========================================================================
    print(f"\n{BOLD}=== Resumo ==={RESET}\n")
    if all_ok:
        print(f"{GREEN}{BOLD}✓ Sistema pronto para fine-tuning!{RESET}")
        print("\nPróximos passos:")
        print("  1. Instale dependências opcionais se necessário:")
        print("     pip install 'ultralytics>=8.3.0' 'datasets>=2.16.0' 'pyarrow>=14.0.0'")
        print("  2. Inicie o servidor: uvicorn app.main:app --reload")
        print("  3. Acesse: http://localhost:8000/training/")
        return 0
    else:
        print(f"{RED}{BOLD}✗ Alguns componentes estão faltando.{RESET}")
        print("\nInstale as dependências:")
        print("  pip install -r requirements.txt")
        print("  pip install 'ultralytics>=8.3.0' 'datasets>=2.16.0' 'pyarrow>=14.0.0'")
        return 1


if __name__ == "__main__":
    sys.exit(main())
