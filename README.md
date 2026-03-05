# STRIDE Threat Modeler

MVP de Modelagem de Ameaças com Inteligência Artificial — FIAP Tech Challenge Fase 5 (Hackathon 2025)

## Visão Geral

Esta aplicação web analisa automaticamente **diagramas de arquitetura de software** (imagens) e gera um **Relatório de Modelagem de Ameaças** seguindo a metodologia **STRIDE**, utilizando **LangGraph** com **Google Gemini** (gemini-2.0-flash) e suporte a visão computacional.

A solução inclui também um **chat agêntico** (ReAct agent) para consultas sobre STRIDE e segurança de aplicações.

### Metodologia STRIDE

| Letra | Categoria | Descrição |
|-------|-----------|-----------|
| **S** | Spoofing | Falsificação de identidade de usuários ou componentes |
| **T** | Tampering | Adulteração de dados em trânsito ou em repouso |
| **R** | Repudiation | Negação de ter realizado uma ação (falta de auditoria) |
| **I** | Information Disclosure | Exposição indevida de informações confidenciais |
| **D** | Denial of Service | Tornar um serviço indisponível |
| **E** | Elevation of Privilege | Obter acesso não autorizado a recursos privilegiados |

## Fluxo da Solução (LangGraph Pipeline)

```
Usuário
  │
  ├─ Faz upload do diagrama de arquitetura (PNG/JPEG)
  │
  ▼
[FastAPI] ─► [LangGraph Analysis Pipeline]
               │
               ├─ detect_shapes (OpenCV + YOLO-World + EasyOCR) *opcional
               │  
               ├─ has_yolo_detections?
               │   ├─ True  → map_components  (texto enriquecido, -60% tokens)
               │   └─ False → vision_fallback (Gemini Vision com imagem base64)
               │
               ├─ analyze_stride (structured output com Pydantic)
               │   │  Gemini (gemini-2.0-flash)
               │   │  Aplica STRIDE para cada componente
               │   │  Gera ameaças + contramedidas + severidade
               │
               └─ compile_report
                    │
                    ▼
              [ThreatReport JSON + HTML]
                    │  Exibe relatório com filtros por categoria STRIDE
                    ▼
                 Usuário
```

**Chat Agêntico**: Além da análise de diagramas, a aplicação oferece um ReAct agent (LangChain) para responder perguntas sobre STRIDE, segurança e interpretação do relatório gerado.

## Pré-requisitos

- Python 3.11+
- Chave de API do Google Gemini (obtenha em [aistudio.google.com](https://aistudio.google.com/apikey))

## Instalação

```bash
# Clone o repositório
git clone https://github.com/arthuribias-coder/tech-challenge-hackathon.git
cd tech-challenge-hackathon

# Crie e ative o ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Instale as dependências
pip install -r requirements.txt

# (Opcional) Para habilitar detecção visual avançada com YOLO + OCR:
# pip install "ultralytics>=8.3.0" "easyocr>=1.7.0"
# Baixe o modelo: wget https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8s-world.pt

# Configure as variáveis de ambiente
cp .env.example .env
# Edite o .env e adicione sua GEMINI_API_KEY
```

> **Nota**: Sem `ultralytics` e `easyocr`, o pipeline usa Gemini Vision diretamente (fallback automático).

## Configuração

Edite o arquivo `.env`:

```env
GEMINI_API_KEY=AIza...         # Obrigatório
GEMINI_MODEL=gemini-2.0-flash  # Modelo (padrão: gemini-2.0-flash)
DEBUG=false                    # Modo debug
MAX_UPLOAD_SIZE_MB=10          # Tamanho máximo do upload
```

## Executando a Aplicação

```bash
uvicorn app.main:app --reload
```

Acesse: [http://localhost:8000](http://localhost:8000)

## Executando os Testes

```bash
# Instale as dependências de desenvolvimento
pip install -r requirements-dev.txt

# Execute os testes com cobertura
pytest
```

## Estrutura do Projeto

```
.
├── app/
│   ├── main.py                     # Entrada da aplicação FastAPI
│   ├── config.py                   # Configurações via pydantic-settings
│   ├── constants.py                # Constantes (STRIDE_CATEGORIES, NODE_LABELS)
│   ├── graphs/
│   │   ├── analysis_graph.py       # [PRINCIPAL] Pipeline LangGraph de análise
│   │   ├── chat_graph.py           # ReAct agent para chat STRIDE
│   │   └── report_chat_graph.py    # Chat contextual sobre relatório gerado
│   ├── nodes/
│   │   ├── yolo_detector.py        # Detecção de shapes com YOLO + OCR
│   │   ├── component_mapper.py     # map_components + vision_fallback
│   │   ├── stride_node.py          # Análise STRIDE com structured output
│   │   ├── report_compiler.py      # Geração final do relatório
│   │   └── diagram_validator.py    # Validação de imagem
│   ├── models/
│   │   └── schemas.py              # Modelos Pydantic (AnalysisState, ThreatReport)
│   ├── routers/
│   │   ├── analysis.py             # Rotas HTTP (upload + análise SSE)
│   │   ├── chat.py                 # Endpoint de chat agêntico
│   │   └── report_chat.py          # Chat sobre relatório específico
│   ├── services/                   # [LEGADO] Código pré-LangGraph
│   │   ├── diagram_analyzer.py
│   │   ├── stride_analyzer.py
│   │   └── report_generator.py
│   ├── tools/
│   │   └── stride_tools.py         # Ferramentas para ReAct agent
│   ├── utils/
│   │   ├── llm.py                  # Factory de LLM Gemini
│   │   └── sse.py                  # Helper para Server-Sent Events
│   └── templates/
│       ├── base.html               # Layout base
│       ├── index.html              # Página de upload
│       ├── report.html             # Relatório de ameaças
│       └── chat.html               # Interface de chat
├── static/
│   ├── css/style.css               # Estilos (tema dark)
│   └── js/
│       ├── analysis.js   **[SSE]** Processa diagrama via LangGraph (streaming) |
| `GET` | `/chat/` | Interface do chat agêntico STRIDE |
| `POST` | `/chat/message` | Envia mensagem ao ReAct agent |
| `POST` | `/report-chat/message` | Chat contextual sobre relatório específicupload)
│       ├── chat.js                 # Chat agêntico
│       └── report-chat.js          # Chat sobre relatório
├── tests/
│   ├── test_schemas.py             # Testes dos modelos Pydantic
│   ├── test_api.py                 # Testes de integração da API
│   ├── test_nodes.py               # Testes dos nós LangGraph
│   └── test_tools.py               # Testes das tools do agent
├── docs/
│   └── IADT - Fase 5 - Hackaton.pdf
├── .env.example
├── .gitignore
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

> **Nota**: `app/services/` contém código legado. A lógica ativa está em `app/nodes/` e `app/graphs/`.

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/` | Redireciona para `/analysis/` |
| `GET` | `/analysis/` | Página de upload do diagrama |
| `POST` | `/analysis/` | Processa o diagrama e retorna o relatório |
| `GET` | `/health` | Health check da aplicação |

## Entregáveis do Hackathon

- [x] Código-fonte no GitHub
- [x] Documentação do fluxo de desenvolvimento (este README)
- [ ] Vídeo de até 15 minutos explicando a solução

## TLangGraph** — Orquestração de workflows com LLM (pipeline de análise)

- **LangChain** — Structured output e ReAct agent
- **Google Gemini (gemini-2.0-flash)** — LLM para análise de diagramas e STRIDE
- **Pydantic v2** — Validação de dados e schemas
- **OpenCV + EasyOCR + YOLO-World** *(opcional)* — Detecção visual de componente
- **FastAPI** — Framework web assíncrono
- **Google Gemini (gemini-2.0-flash)** — Análise de imagens de diagramas e geração de ameaças STRIDE
- **Pydantic v2** — Validação de dados e schemas
- **Jinja2** — Templates HTML
- **pytest + pytest-asyncio** — Testes automatizados
- **Ruff + mypy** — Linting e tipagem estática

## Equipe

FIAP — Pós-Graduação em Inteligência Artificial para Desenvolvedores  
Tech Challenge — Fase 5 — Hackathon 2025
