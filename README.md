# STRIDE Threat Modeler

MVP de Modelagem de Ameaças com Inteligência Artificial — FIAP Tech Challenge Fase 5 (Hackathon 2025)

## Visão Geral

Esta aplicação web analisa automaticamente **diagramas de arquitetura de software** (imagens) e gera um **Relatório de Modelagem de Ameaças** seguindo a metodologia **STRIDE**, utilizando o Google Gemini (gemini-2.0-flash) com suporte a visão computacional.

### Metodologia STRIDE

| Letra | Categoria | Descrição |
|-------|-----------|-----------|
| **S** | Spoofing | Falsificação de identidade de usuários ou componentes |
| **T** | Tampering | Adulteração de dados em trânsito ou em repouso |
| **R** | Repudiation | Negação de ter realizado uma ação (falta de auditoria) |
| **I** | Information Disclosure | Exposição indevida de informações confidenciais |
| **D** | Denial of Service | Tornar um serviço indisponível |
| **E** | Elevation of Privilege | Obter acesso não autorizado a recursos privilegiados |

## Fluxo da Solução

```
Usuário
  │
  ├─ Faz upload do diagrama de arquitetura (PNG/JPEG)
  │
  ▼
[FastAPI] ─► [Diagram Analyzer]
               │  Gemini Vision (gemini-2.0-flash)
               │  Identifica componentes: servidores, DBs, APIs, usuários...
               ▼
         [STRIDE Analyzer]
               │  Gemini (gemini-2.0-flash)
               │  Aplica STRIDE para cada componente
               │  Gera ameaças + contramedidas + severidade
               ▼
         [ThreatReport]
               │
               ▼
         [Template HTML]
               │  Exibe relatório com filtros por categoria STRIDE
               ▼
            Usuário
```

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

# Configure as variáveis de ambiente
cp .env.example .env
# Edite o .env e adicione sua GEMINI_API_KEY
```

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
│   ├── models/
│   │   └── schemas.py              # Modelos Pydantic (Threat, ThreatReport, etc.)
│   ├── routers/
│   │   └── analysis.py             # Rotas HTTP (upload + análise)
│   ├── services/
│   │   ├── diagram_analyzer.py     # Extração de componentes via GPT-4o Vision
│   │   ├── stride_analyzer.py      # Geração de ameaças STRIDE via GPT-4o
│   │   └── report_generator.py     # Orquestração do fluxo completo
│   └── templates/
│       ├── base.html               # Layout base
│       ├── index.html              # Página de upload
│       └── report.html             # Relatório de ameaças
├── static/
│   ├── css/style.css               # Estilos (tema dark)
│   └── js/app.js                   # Interações (dropzone, loading)
├── tests/
│   ├── test_schemas.py             # Testes dos modelos Pydantic
│   ├── test_api.py                 # Testes de integração da API
│   └── test_stride_analyzer.py     # Testes unitários do serviço STRIDE
├── docs/
│   └── IADT - Fase 5 - Hackaton.pdf
├── .env.example
├── .gitignore
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

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

## Tecnologias Utilizadas

- **FastAPI** — Framework web assíncrono
- **Google Gemini (gemini-2.0-flash)** — Análise de imagens de diagramas e geração de ameaças STRIDE
- **Pydantic v2** — Validação de dados e schemas
- **Jinja2** — Templates HTML
- **pytest + pytest-asyncio** — Testes automatizados
- **Ruff + mypy** — Linting e tipagem estática

## Equipe

FIAP — Pós-Graduação em Inteligência Artificial para Desenvolvedores  
Tech Challenge — Fase 5 — Hackathon 2025
