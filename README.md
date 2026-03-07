# STRIDE Threat Modeler

**Automatização de Modelagem de Ameaças com IA Generativa**  
*FIAP Tech Challenge Fase 5 — Hackathon 2025*

## 🎯 Objetivo

Desenvolver um MVP que interprete automaticamente **diagramas de arquitetura de software** (imagens) e gere **análises de segurança estruturadas** seguindo a metodologia **STRIDE**, reduzindo o tempo e especialização necessários para modelagem de ameaças.

## ✨ Características Principais

- **Análise Visual Automática**: Extrai componentes de diagramas usando Visão Computacional (YOLO-World) + OCR
- **Geração de Ameaças com IA**: Aplica STRIDE com Google Gemini (LLM generativo)
- **Relatório Estruturado**: HTML interativo com filtros por categoria STRIDE
- **Chat Agêntico**: ReAct agent para consultas sobre STRIDE e interpretação de resultados
- **Pipeline Resiliente**: Fallback automático entre CV e Gemini Vision

## 📐 Metodologia STRIDE

Framework de ameaças que categoriza vulnerabilidades em 6 dimensões:

| Categoria | Descrição | Exemplos de Ameaça |
|-----------|-----------|---|
| **S**poofing | Falsificação de identidade | Acesso não autorizado, bypass de auth |
| **T**ampering | Adulteração de dados | Injection attacks, MITM, data corruption |
| **R**epudiation | Negação de ações | Falta de logs, auditoria incompleta |
| **I**nformation Disclosure | Exposição de dados | SQL Injection, data leaks, XSS |
| **D**enial of Service | Indisponibilidade | DDoS, resource exhaustion |
| **E**levation of Privilege | Acesso privilegiado | Privilege escalation, insecure deserialization |

## 🏗️ Arquitetura e Pipeline de Processamento

### Fluxo End-to-End

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    STRIDE Threat Modeler Pipeline                        │
└─────────────────────────────────────────────────────────────────────────┘

User Upload (PNG/JPEG)
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ STAGE 0: Validação de Diagrama                                       │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Gemini 2.0-Flash-Lite: é realmente um diagrama de arq.?      │  │
│  │ → Se não → encerra pipeline com mensagem de erro             │  │
│  │ → Se sim → prossegue para Stage 1                            │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ STAGE 1: Extração de Componentes (Hybrid Approach)                   │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────────────┐                                           │
│  │ YOLO-World Detector  │ Detecta formas/caixas no diagrama         │
│  │ (CV pré-treinado)    │ → Coordenadas, tipos de componentes      │
│  └──────────┬───────────┘                                           │
│             │                                                        │
│             ├─ EasyOCR: Extrai labels/textos                        │
│             │                                                        │
│             ├─> has_yolo_detections? ──┐                           │
│                                         │                           │
│                         True (60% de redução em tokens)             │
│                         └──> JSON textual enriquecido               │
│                                         │                           │
│                         False (imagem complexa)                     │
│                         └──> Gemini Vision + Base64                 │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ STAGE 2: Análise de Ameaças (LLM + Structured Output)               │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌────────────────────────────────────┐                             │
│  │ Google Gemini 2.5-Flash            │ LLM Generativo             │
│  │ + Pydantic Structured Output      │ IA para análise STRIDE     │
│  └────────────────┬───────────────────┘                             │
│                    │                                                  │
│  Processa: "Diagrama X contém [componentes]"                        │
│  │                                                                    │
│  └─> Para cada componente × STRIDE categoria:                       │
│      ├─ Identifica ameaças potenciais                              │
│      ├─ Estima severidade (CRÍTICA/ALTA/MÉDIA/BAIXA)              │
│      └─ Recomenda contramedidas específicas                        │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ STAGE 3: Geração de Relatório                                        │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  JSON Estruturado (OpenAPI Schema) → HTML + CSS interativo          │
│  │                                                                    │
│  ├─ Componentes identificados                                        │
│  ├─ Matriz STRIDE (6 categorias × N componentes)                    │
│  ├─ Filtros por severidade e categoria                             │
│  └─ Export para relatórios de conformidade                         │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### Chat Agêntico Opcional

Além da análise automática, a aplicação oferece um **ReAct agent** (LangChain) para:

- Responder dúvidas sobre STRIDE e cada categoria
- Interpretação contextual do relatório gerado
- Sugestões de mitigation baseadas em padrões conhecidos

## 🤖 Modelos e Técnicas de IA

### 1. **Visão Computacional (Extração de Componentes)**

#### YOLO-World

- **Modelo**: YOLOv8s-World (Segment Anything meets YOLO)
- **Propósito**: Detecção de objetos zero-shot em diagramas
- **Vantagem**: Reconhece caixas/formas sem necessidade de retreinamento
- **Saída**: Coordenadas (bbox), confiança, labels textuais
- **Status**: Opcional (requer `ultralytics` + modelo `yolov8s-world.pt`)

#### EasyOCR

- **Tecnologia**: Deep Learning para Optical Character Recognition
- **Propósito**: Extrair textos/labels dos componentes detectados
- **Acurácia**: ~95% para diagramas com texto legível
- **Saída**: Texto + confiança por palavra
- **Status**: Opcional (requer `easyocr`)

### 2. **Análise Generativa (Modelagem de Ameaças)**

#### Google Gemini (multi-modelo)

A aplicação usa três instâncias distintas do Gemini, otimizadas por custo e capacidade:

| Uso | Modelo | Configuração |
|---|---|---|
| Análise STRIDE principal | `gemini-2.5-flash` | `GEMINI_MODEL` |
| Chat agêntico (multiturno) | `gemini-2.0-flash` | `GEMINI_CHAT_MODEL` |
| Validação de diagrama | `gemini-2.0-flash-lite` | `GEMINI_VALIDATOR_MODEL` |

- **Tipo**: Large Language Model (LLM) Generativo
- **Capacidade**: Análise contextual de texto + visão (multimodal)
- **Aplicação**:
  - Validação se a imagem é um diagrama de arquitetura (antes do pipeline)
  - Processamento de texto extraído (YOLO + OCR)
  - Fallback direto em Gemini Vision se YOLO não detectar
  - Análise STRIDE com structured output
- **Structured Output**: Usa Pydantic para garantir respostas em formato JSON validado
- **Custo de Tokens**: ~60% redução usando YOLO+OCR vs enviar imagem raw

### 3. **Orquestração (LangGraph)**

#### LangGraph

- **Padrão**: State machine com nós reutilizáveis
- **Benefício**: Composição de workflows complexos
- **Uso**:
  - Orquestração do pipeline análise (validate → detect → map/vision → analyze → compile)
  - Chat agêntico com context aware
  - Fácil adicionar novos nós/branches

#### LangChain

- **Função**: Integration layer com LLMs
- **Uso**:
  - `with_structured_output()` para Pydantic validation
  - ReAct agent (agent + tools)
  - Memory management por thread_id

### 4. **Persistência e Validação**

#### Pydantic v2

- **Schemas Críticos**:
  - `AnalysisState`: TypedDict com estado do pipeline
  - `ThreatReport`: JSON Schema com componentes + ameaças
  - `Threat`: Categoria STRIDE + descrição + severidade
- **Vantagem**: Type hints + validação automática + JSON Schema geração

---

## 📦 Pré-requisitos e Instalação

### Requisitos do Sistema

- **Python**: 3.11+ (recomendado 3.12)
- **API Key**: Google Gemini (gratuita em [aistudio.google.com/apikey](https://aistudio.google.com/apikey))
- **Dependências Opcionais** (para CV avançada):
  - `ultralytics` (YOLO-World)
  - `easyocr` (OCR de texto)
  - Modelo `yolov8s-world.pt`

### Setup Passo-a-Passo

```bash
# 1. Clone e navegue
git clone https://github.com/arthuribias-coder/tech-challenge-hackathon.git
cd tech-challenge-hackathon

# 2. Ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 3. Dependências obrigatórias
pip install -r requirements.txt

# 4. (OPCIONAL) Habilitar CV avançada
pip install "ultralytics>=8.3.0" "easyocr>=1.7.0"
wget -O yolov8s-world.pt \
  https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8s-world.pt

# 5. Configuração
cp .env.example .env
# Edite .env: adicione sua GEMINI_API_KEY
```

### Modo Fallback (Sem CV)

Sem `ultralytics`/`easyocr`, o pipeline automaticamente usa **Gemini Vision** diretamente (sem perda de funcionalidade, apenas maior custo de tokens).

---

## ⚙️ Configuração

Edite `.env`:

```env
GEMINI_API_KEY=AIza...                       # Obrigatório (Google AI Studio)
GEMINI_MODEL=gemini-2.5-flash                # Modelo principal — análise STRIDE
GEMINI_CHAT_MODEL=gemini-2.0-flash           # Modelo do chat agêntico
GEMINI_VALIDATOR_MODEL=gemini-2.0-flash-lite # Modelo de validação de diagrama (econômico)
DEBUG=false                                  # Enable detailed logging
MAX_UPLOAD_SIZE_MB=10                        # Limiar de tamanho de imagem
ROBOFLOW_API_KEY=rf_...                      # Opcional — para download de datasets do Roboflow Universe
```

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

## 📂 Estrutura do Projeto e Componentes

### Arquitetura em Camadas

```
CAMADA DE APRESENTAÇÃO
├─ FastAPI + Jinja2 Templates
└─ Static assets (CSS/JS SSE)

      ↓

CAMADA DE ORQUESTRAÇÃO (LangGraph)
├─ analysis_graph.py     → Nós: validate → detect → map/vision → analyze → compile
├─ chat_graph.py         → ReAct agent com tools (standalone)
└─ report_chat_graph.py  → Chat contextual sobre relatório gerado

      ↓

CAMADA DE PROCESSAMENTO (Nodes)
├─ yolo_detector        → CV: detecção de formas
├─ component_mapper     → Extração de texto (OCR)
├─ stride_node          → Análise STRIDE com Gemini
├─ report_compiler      → Formatação final
└─ diagram_validator    → Validação de entrada

      ↓

CAMADA DE UTILITÁRIOS
├─ llm.py              → Factory para Gemini
├─ sse.py              → Server-Sent Events streaming
├─ config.py           → Gestão de configurações
└─ log_buffer.py       → Buffer de logs para /status/
```

### Estrutura de Arquivos

```
app/
├── graphs/
│   ├── analysis_graph.py       # [PRINCIPAL] Pipeline de análise STRIDE
│   ├── chat_graph.py           # ReAct agent para Q&A sobre STRIDE (standalone)
│   ├── report_chat_graph.py    # Chat contextual com contexto do relatório
│   └── __init__.py
│
├── nodes/
│   ├── diagram_validator.py    # [1º] Validação Gemini Vision (é um diagrama?)
│   ├── yolo_detector.py        # [2º] Detecção de formas (YOLO-World + OpenCV + EasyOCR)
│   ├── component_mapper.py     # [3º] map_components (JSON-only) e vision_fallback (Gemini Vision)
│   ├── stride_node.py          # [4º] Análise STRIDE com Pydantic structured output
│   └── report_compiler.py      # [5º] Compilação do ThreatReport final
│
├── routers/
│   ├── analysis.py             # Upload + SSE streaming + report chat
│   ├── chat.py                 # Chat agêntico standalone (gemini-2.0-flash)
│   ├── report_chat.py          # Chat contextual sobre relatório gerado
│   ├── status.py               # Página de status e stream de logs
│   └── training.py             # Fine-tuning YOLOv8 (download + treinamento SSE)
│
├── services/
│   └── finetuning_service.py   # Orquestração do fine-tuning YOLOv8
│
├── models/
│   └── schemas.py              # Pydantic: AnalysisState, ThreatReport, Threat
│
├── tools/
│   └── stride_tools.py         # Conhecimento STRIDE embarcado para ReAct agent
│
├── utils/
│   ├── llm.py                  # Factory centralizada para instâncias ChatGoogleGenerativeAI
│   ├── sse.py                  # Helpers para Server-Sent Events
│   └── log_buffer.py           # Buffer circular de logs para exibição em /status/
│
├── constants.py                # Constantes compartilhadas (limiares, paths, SSE)
├── config.py                   # Settings Pydantic (lê .env)
└── templates/
    ├── base.html
    ├── index.html              # Upload de diagrama
    ├── report.html             # Relatório interativo com filtros STRIDE
    ├── chat.html               # Interface do agente
    └── training.html           # Interface de fine-tuning YOLOv8
```

---

## 🤖 Fine-tuning YOLOv8 (Sistema de Treinamento Supervisionado)

A aplicação inclui um pipeline completo de fine-tuning do YOLOv8 para detecção de componentes de diagramas de arquitetura. O treinamento é feito com streaming SSE em tempo real.

### Acessar a Interface

```
GET /training/
```

### Cascata de Datasets

O sistema tenta datasets em ordem de qualidade, com fallback automático:

| Prioridade | Fonte | Datasets | Requisito |
|:---:|---|---|---|
| 1º | **Roboflow Universe** | Threat Modeling Architecture, Network Components 2, Architecture Symbols | `ROBOFLOW_API_KEY` |
| 2º | **HuggingFace** | `LibreYOLO/activity-diagrams-qdobr` | `datasets` instalado |
| 3º | **Sintético local** | Gerado com OpenCV + anotações automáticas | Apenas `opencv-python` |

### Datasets Roboflow Configurados

| Dataset | Classes | Imagens | Workspace |
|---|---|:---:|---|
| Threat Modeling Architecture | Client, Server, Database, Firewall... | ~36 | `marcelos-workspace-1mzme` |
| Network Components 2 | Client, Database, Firewall, Router, Server, WebServer | ~186 | `cybersecurityproject` |
| Architecture Symbols Dataset | API, Database, ExternalSystem, Queue, Service, Storage, User | ~138 | `architecture-communication-symbols-dataset` |

### Instalar Dependências de Treinamento

```bash
# Obrigatório para fine-tuning
pip install "ultralytics>=8.3.0"

# Para download via Roboflow (recomendado)
pip install roboflow

# Para download via HuggingFace
pip install "datasets>=2.19"
```

### Configurar Roboflow

1. Crie conta gratuita em [roboflow.com](https://roboflow.com)
2. Obtenha sua API key em **Settings → Roboflow API**
3. Adicione ao `.env`:

```env
ROBOFLOW_API_KEY=rf_...
```

### Parâmetros de Treinamento

| Parâmetro | Padrão | Descrição |
|---|:---:|---|
| `epochs` | 300 | Número de épocas |
| `batch_size` | 8 | Imagens por batch |
| `img_size` | 1280 | Resolução de entrada |
| `patience` | 50 | Early stopping |
| `resume` | false | Retomar de checkpoint anterior |
| `demo` | false | Usar COCO128 (sem download) |

### Dataset Sintético

Quando nenhum download externo está disponível, o sistema gera automaticamente 60 imagens de treino + 15 de validação com:

- 3–6 componentes por imagem com bounding boxes anotados
- 8 classes: `user`, `server`, `database`, `api`, `firewall`, `cache`, `storage`, `network`
- Setas de conexão entre componentes
- Fundo escuro simulando diagramas reais

---

## 🚀 Executar a Aplicação

```bash
# Desenvolvimento
uvicorn app.main:app --reload

# Produção (com gunicorn)
gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app
```

Acesse: [http://localhost:8000](http://localhost:8000)

## 🧪 Testes

```bash
# Instale ferramentas de teste
pip install -r requirements-dev.txt

# Execute com cobertura
pytest --cov=app

# Linting e type checking
ruff check app
mypy app --strict
```

## 📡 Endpoints da API

### Análise

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/` | Redireciona para `/analysis/` |
| `GET` | `/analysis/` | Página de upload do diagrama (HTML) |
| `POST` | `/analysis/upload` | Salva imagem e retorna `upload_id` (passo 1) |
| `GET` | `/analysis/stream/{upload_id}` | Executa pipeline STRIDE + SSE streaming (passo 2) |
| `GET` | `/health` | Health check da aplicação (200 OK) |

### Chat sobre Relatório

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/analysis/{upload_id}/chat/ping` | Verifica se o relatório está disponível para chat |
| `POST` | `/analysis/{upload_id}/chat/stream` | Chat contextual sobre relatório (SSE streaming) |

### Chat Agêntico STRIDE

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/chat/` | Interface do chat agêntico (HTML) |
| `POST` | `/chat/message/stream` | Envia pergunta ao ReAct agent (SSE streaming) |

### Status e Monitoramento

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/status/` | Página de status e logs em tempo real (HTML) |
| `GET` | `/status/logs/stream` | Stream SSE de logs em tempo real |
| `GET` | `/status/logs` | Últimas N entradas do buffer de log (JSON) |

### Fine-tuning YOLOv8

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/training/` | Interface de fine-tuning YOLOv8 (HTML) |
| `POST` | `/training/download` | Baixa dataset (Roboflow → HF → sintético) |
| `POST` | `/training/use-demo` | Configura modo demo (COCO128) |
| `GET` | `/training/checkpoint` | Verifica checkpoint disponível para retomada |
| `GET` | `/training/start` | Inicia fine-tuning com progresso SSE |
| `GET` | `/training/status` | Status atual do treinamento |
| `POST` | `/training/cancel` | Cancela treinamento em andamento |
| `GET` | `/training/models` | Lista modelos fine-tuned disponíveis |
| `POST` | `/training/delete/{filename}` | Deleta modelo fine-tuned |

---

## 📚 Stack Tecnológico

### Backend & Orquestração

- **FastAPI** — Framework web assíncrono com suporte SSE
- **LangGraph** — State machine para pipelines de IA
- **LangChain** — Integration layer com LLMs (structured output)

### IA & Modelos

- **Google Gemini 2.5-Flash** — LLM generativo (análise STRIDE principal)
- **Google Gemini 2.0-Flash** — Chat agêntico multiturno
- **Google Gemini 2.0-Flash-Lite** — Validação rápida de diagrama
- **YOLO-World** *(opcional)* — Detecção zero-shot de objetos
- **EasyOCR** *(opcional)* — OCR com deep learning

### Validação & Dados

- **Pydantic v2** — Type hints + validação automática
- **JSON Schema** — OpenAPI para structured output

### Frontend

- **Jinja2** — Templates HTML lado do servidor
- **Fetch API + SSE** — Streaming de análise em tempo real
- **CSS customizado** — Tema dark otimizado para leitura

### DevOps & Qualidade

- **pytest + pytest-asyncio** — Testes automatizados
- **Ruff** — Linting rápido (Rust-based)
- **mypy** — Type checking estático (strict mode)
- **GitHub Actions** *(sugerido)* — CI/CD

---

## ✏️ Notas de Implementação

### Decisões Arquiteturais

**1. Hybrid Vision (CV + LLM)**

- Combinação de YOLO-World (detecção) + Gemini Vision (fallback)
- Reduz tokens em ~60% quando YOLO detecta componentes
- Mantém funcionalidade mesmo sem CV avançada instalada

**2. Structured Output com Pydantic**

- Garante schema JSON consistente da análise STRIDE
- Evita parsing manual de LLM output
- Facilita serialização e validação

**3. LangGraph para Orquestração**

- Nós reutilizáveis e componíveis
- Fácil adicionar observabilidade (LangSmith)
- State-based ao invés de call sequences

**4. Lazy Imports para CV**

- `ultralytics` e `easyocr` são opcionais
- App inicia sem elas, fallback automático ativado
- Reduz tempo de startup em produção

### Limitações Conhecidas

- **Imagens Muito Grandes**: Limite de 10MB (configurável via `MAX_UPLOAD_SIZE_MB`)
- **OCR Multilíngue**: EasyOCR suporta ~80 idiomas, mas acurácia varia
- **Componentes Estilizados**: Melhor performance em diagramas simples (boxes + labels)

---

## 📋 Status de Implementação vs Requisitos

### Requisitos Funcionais

| ID | Requisito | Status | Implementação |
|----|-----------| :---: |---|
| **RF1** | Receber diagrama em formato imagem | ✅ | `POST /analysis/upload` com validação MIME |
| **RF2** | Extrair e identificar componentes | ✅ | YOLO-World + EasyOCR (ou Gemini Vision) |
| **RF3** | Aplicar metodologia STRIDE | ✅ | Análise estruturada em 6 categorias |
| **RF4** | Gerar relatório com vulnerabilidades e contramedidas | ✅ | JSON Schema + HTML interativo |
| **RF5** | Treinar modelo supervisionado | ✅ | Fine-tuning YOLOv8 com datasets Roboflow/HF/sintético (`GET /training/`) |
| **RF6** | Classificar ameaças por tipo STRIDE | ✅ | Mapeamento automático Threat → Categoria |

### Requisitos Não-Funcionais

| ID | Requisito | Status | Observação |
|----|-----------| :---: |---|
| **RNF1** | Detecção supervisionada | ✅ | CV pré-treinada + fine-tuning YOLOv8 + LLM generativo (abordagem híbrida) |
| **RNF2** | Automatização completa | ✅ | Sem intervenção manual no pipeline |
| **RNF3** | Viabilidade do MVP | ✅ | Code + testes + docs completos |
| **RNF4** | Escalabilidade | ✅ | Suporta múltiplas arquiteturas e diagramas |

### 📌 Nota: RF5 (Treinamento Supervisionado)

O projeto implementa **dois níveis de detecção**:

1. **CV pré-treinada** (YOLO-World zero-shot + EasyOCR) — sem treinamento, funciona de imediato
2. **Fine-tuning supervisionado** (`GET /training/`) — treina YOLOv8 em datasets de diagramas de arquitetura

A abordagem híbrida garante funcionalidade imediata enquanto o fine-tuning melhora a precisão progressivamente conforme mais dados são disponibilizados.

**Trade-offs:**

- ✅ Funcionalidade completa sem fine-tuning (YOLO-World + Gemini Vision)
- ✅ Melhora progressiva com fine-tuning em datasets especializados
- ✅ Pipeline resiliente: Roboflow → HuggingFace → dataset sintético local
- ❌ Acurácia do fine-tuning limitada pelo tamanho dos datasets públicos disponíveis

---

## 🎓 Equipe

FIAP — Pós-Graduação em Inteligência Artificial para Desenvolvedores  
Tech Challenge — Fase 5 — Hackathon 2025
