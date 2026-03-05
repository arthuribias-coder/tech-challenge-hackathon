# STRIDE Threat Modeler — Copilot Instructions

FastAPI + LangGraph MVP que analisa diagramas de arquitetura (imagens) e gera relatórios de ameaças seguindo a metodologia STRIDE com Google Gemini.

## Comandos Essenciais

SEMPRE USE O VENV DO PROJETO PARA GARANTIR AS DEPENDÊNCIAS CORRETAS. No terminal, navegue até a raiz do projeto e ative o ambiente virtual.

```bash
uvicorn app.main:app --reload   # servidor de desenvolvimento
pytest                          # testes com cobertura (pyproject.toml configura --cov=app)
ruff check app tests            # linting
mypy app                        # type checking (strict mode)
```

Copiar `.env.example → .env` e preencher `GEMINI_API_KEY` antes de rodar.

## Arquitetura: LangGraph Pipeline de Análise

O fluxo principal está em `app/graphs/analysis_graph.py`. O estado compartilhado é `AnalysisState` (TypedDict em `app/models/schemas.py`).

```
detect_shapes
     │
     ├── has_yolo_detections=True  → map_components  (texto enriquecido por YOLO+OCR)
     └── has_yolo_detections=False → vision_fallback  (Gemini Vision analisa a imagem)
              │
         analyze_stride  (LangChain com structured output Pydantic)
              │
         compile_report
```

- **`detect_shapes`** (`app/nodes/yolo_detector.py`): OpenCV + EasyOCR + YOLO-World. As libs `easyocr` e `ultralytics` são **lazy imports** — o app inicia sem elas e encaminha automaticamente para `vision_fallback`.
- **`map_components`** (`app/nodes/component_mapper.py`): recebe JSON de texto das detecções (sem imagem), reduzindo ~60% de tokens.
- **`vision_fallback`** (`app/nodes/component_mapper.py`): envia a imagem em base64 ao Gemini quando YOLO não detectou nada.
- **`analyze_stride`** (`app/nodes/stride_node.py`): usa `with_structured_output(_StrideAnalysis)` via LangChain para garantir schema correto sem parsing manual.
- `yolov8s-world.pt` deve estar na raiz para o nó YOLO funcionar.

## Chat Agêntico

`app/graphs/chat_graph.py` é um ReAct agent criado com `create_react_agent`. Usa `MemorySaver` por `thread_id` para histórico de sessão. As tools (`app/tools/stride_tools.py`) são baseadas em conhecimento embutido — sem chamadas externas, garantindo baixa latência.

## Padrões de Código

**Nós LangGraph**: funções `async def <name>_node(state: AnalysisState) -> dict` que retornam apenas as chaves que foram modificadas.

**Structured output com Pydantic**: todos os nós que chamam o LLM definem um schema Pydantic privado (`_NomeDoSchema`) e usam `llm.with_structured_output(Schema)` — nunca `json.loads` manual.

**Configuração**: sempre via `from app.config import settings` (singleton `pydantic-settings`). Variáveis de ambiente mapeadas em `app/config.py`.

**Streaming SSE** (router `analysis.py`): `graph.astream(state, stream_mode="updates")` com helper `_sse(payload)` formata cada atualização como evento SSE. Labels de progresso para o frontend estão em `analysis_graph.NODE_LABELS`.

## Testes

```python
# padrão em tests/test_nodes.py
def _base_state(**kwargs) -> AnalysisState:
    state = { "image_path": "/tmp/test.png", "has_yolo_detections": False, ... }
    state.update(kwargs)
    return state

# nós são assíncronos mas pytest-asyncio não é necessário explicitamente —
# asyncio_mode = "auto" está ativo via pyproject.toml
```

Mock de LLM com `unittest.mock.patch` — os testes de nós não fazem chamadas reais ao Gemini.

## Dependências Opcionais (CV)

`ultralytics` e `easyocr` estão **comentados** em `requirements.txt`. Para habilitar detecção visual completa:

```bash
pip install "ultralytics>=8.3.0" "easyocr>=1.7.0"
```

Sem elas, `has_yolo_detections` sempre será `False` e o pipeline usa Gemini Vision diretamente.

## Observabilidade (LangSmith)

Adicionar ao `.env` para habilitar tracing:

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_PROJECT=stride-threat-modeler
```

## Diretório `app/services/`

Contém código legado da versão pré-LangGraph (`diagram_analyzer.py`, `stride_analyzer.py`, `report_generator.py`). A lógica ativa está em `app/nodes/` e `app/graphs/`. Não adicionar nova lógica de pipeline em `services/`.
