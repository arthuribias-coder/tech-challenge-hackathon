"""
Grafo LangGraph para chat contextual sobre o resultado de uma análise STRIDE.

Fluxo:
  START
    │
    ├── (1ª mensagem da sessão) → inject_context_node  → guardrail_node
    └── (sessões seguintes)     ──────────────────────→ guardrail_node
                                                              │
                                                    ALLOW ───┤─── BLOCK
                                                              │          │
                                                        respond_node  refuse_node
                                                              │
                                               (tool_calls?) │
                                                    yes ──── ┤ ──── no
                                                             │         │
                                                        tools_node    END
                                                             │
                                                       (volta ao respond_node)

Guardrails:
  - Layer 1: fast LLM call (temperature=0) com prompt binário ALLOW/BLOCK
  - Layer 2: o system prompt do respond_node reforça o escopo da análise

Contexto injetado:
  - Sumário executivo
  - Lista completa de componentes
  - Lista completa de ameaças com severidade e contramedidas
  - Imagem do diagrama (multimodal, na 1ª mensagem da sessão)
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from app.constants import DEFAULT_MIME_TYPE
from app.tools.stride_tools import STRIDE_TOOLS
from app.utils.llm import create_chat_llm

logger = logging.getLogger(__name__)

try:
    from langchain_google_genai import ChatGoogleGenerativeAI  # noqa: F401 — type hint
except ImportError as exc:
    raise ImportError("Instale langchain-google-genai: pip install langchain-google-genai") from exc

# LangGraph usa um reducer para acumular mensagens
try:
    from langgraph.graph.message import add_messages
except ImportError:
    from operator import add as add_messages  # fallback (não deve ocorrer)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class ReportChatState(TypedDict):
    """Estado do grafo de chat contextual sobre um relatório de análise."""
    messages: Annotated[list, add_messages]

    # Dados do relatório — carregados pelo endpoint e persistidos no checkpoint
    analysis_context: dict

    # Controle de sessão
    session_initialized: bool  # True após a 1ª mensagem injetar o contexto
    guardrail_passed: bool
    refusal_reason: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_llm(temperature: float = 0.7) -> "ChatGoogleGenerativeAI":
    return create_chat_llm(temperature=temperature)


def _format_context_for_prompt(context: dict) -> str:
    """Serializa o relatório como texto rico para o system prompt."""
    report = context.get("report", {})
    components = report.get("components", [])
    threats = report.get("threats", [])
    summary = report.get("summary", "")
    notes = context.get("notes", "")

    lines: list[str] = [
        "=== RELATÓRIO DE ANÁLISE STRIDE ===",
        "",
    ]

    if summary:
        lines += ["**Sumário Executivo:**", summary, ""]

    if notes:
        lines += ["**Observações do analista:**", notes, ""]

    if components:
        lines += [f"**Componentes identificados ({len(components)}):**"]
        for c in components:
            lines.append(
                f"  • {c.get('name', '?')} [{c.get('component_type', '?')}]: "
                f"{c.get('description', '')}"
            )
        lines.append("")

    if threats:
        lines += [f"**Ameaças identificadas ({len(threats)}):**"]
        for t in threats:
            severity = t.get("severity", "?")
            category = t.get("stride_category", "?")
            component = t.get("affected_component", "?")
            title = t.get("title", "?")
            desc = t.get("description", "")
            countermeasures = t.get("countermeasures", [])
            lines.append(f"  • [{severity}] {category} → {component}: {title}")
            if desc:
                lines.append(f"    Descrição: {desc}")
            if countermeasures:
                lines.append(f"    Contramedidas: {'; '.join(countermeasures[:3])}")
        lines.append("")

    return "\n".join(lines)


def _build_system_prompt(context: dict) -> str:
    """Retorna o system prompt completo com o contexto da análise embutido."""
    context_text = _format_context_for_prompt(context)
    return (
        "Você é um especialista em segurança de sistemas e modelagem de ameaças (Threat Modeling) "
        "atuando como consultor exclusivo para uma análise já realizada.\n\n"
        f"{context_text}\n"
        "=== ESCOPO E RESTRIÇÕES ===\n"
        "Você SOMENTE pode responder sobre:\n"
        "  1. Os componentes desta arquitetura e suas interações\n"
        "  2. As ameaças identificadas nesta análise e suas mitigações\n"
        "  3. A metodologia STRIDE aplicada a este contexto específico\n"
        "  4. Scores de risco, priorização e roadmap de correções para estas ameaças\n"
        "  5. Padrões de segurança (OWASP, MITRE ATT&CK, NIST) aplicáveis a esta arquitetura\n\n"
        "Ao responder:\n"
        "  - Referencie sempre os componentes e ameaças específicas desta análise\n"
        "  - Seja objetivo, com exemplos concretos e implementáveis\n"
        "  - Use as ferramentas disponíveis para enriquecer a resposta quando relevante\n"
        "  - Responda SEMPRE em português brasileiro\n"
    )


# ---------------------------------------------------------------------------
# Nós do grafo
# ---------------------------------------------------------------------------


async def inject_context_node(state: ReportChatState) -> dict:
    """
    Executado apenas na primeira mensagem da sessão.
    Injeta o contexto da análise como SystemMessage + AIMessage de confirmação.
    Se a imagem estiver disponível, a inclui como mensagem multimodal.

    IMPORTANTE: a mensagem do usuário já está no estado (inserida pelo router).
    Para garantir a ordem correta (SystemMessage → imagem → ACK → query do usuário),
    removemos a mensagem original com RemoveMessage e a reinserimos ao final.
    """
    context = state.get("analysis_context", {})
    system_prompt = _build_system_prompt(context)

    # Localiza a última mensagem do usuário para reposicioná-la após o contexto
    original_messages = state.get("messages", [])
    last_human = next(
        (m for m in reversed(original_messages) if isinstance(m, HumanMessage)),
        None,
    )

    messages_to_add: list = []

    # Remove a mensagem original para reconstruir na ordem correta
    if last_human:
        messages_to_add.append(RemoveMessage(id=last_human.id))

    messages_to_add.append(SystemMessage(content=system_prompt))

    image_path_str = context.get("image_path", "")
    mime_type = context.get("mime_type", DEFAULT_MIME_TYPE)

    if image_path_str:
        image_path = Path(image_path_str)
        if image_path.exists():
            try:
                image_b64 = base64.b64encode(image_path.read_bytes()).decode()
                image_msg = HumanMessage(content=[
                    {
                        "type": "text",
                        "text": (
                            "Este é o diagrama de arquitetura analisado. "
                            "Use-o como referência visual para responder perguntas sobre a topologia, "
                            "fluxos de dados e componentes identificados."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                    },
                ])
                ack_msg = AIMessage(
                    content=(
                        "Contexto carregado. Recebi o diagrama de arquitetura e o relatório completo da análise STRIDE. "
                        "Pode fazer suas perguntas sobre os componentes identificados, as ameaças encontradas "
                        "e as recomendações de segurança."
                    )
                )
                messages_to_add.extend([image_msg, ack_msg])
                logger.debug("Contexto injetado com imagem: %s", image_path)
            except Exception as exc:
                logger.warning("Falha ao incluir imagem no contexto: %s", exc)

    # Reinsere a mensagem do usuário no final (após o contexto do sistema)
    if last_human:
        messages_to_add.append(HumanMessage(content=last_human.content))

    return {"messages": messages_to_add, "session_initialized": True}


async def guardrail_node(state: ReportChatState) -> dict:
    """
    Verifica se a última mensagem do usuário é relevante ao escopo da análise.
    Usa um LLM com temperature=0 para classificação binária ALLOW/BLOCK.
    """
    # Extrai a última mensagem humana
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )

    if not last_human:
        return {"guardrail_passed": True, "refusal_reason": ""}

    # Se o conteúdo for multimodal (list), pega só o texto
    if isinstance(last_human.content, list):
        user_text = " ".join(
            p.get("text", "") for p in last_human.content if isinstance(p, dict)
        )
    else:
        user_text = str(last_human.content)

    context = state.get("analysis_context", {})
    report = context.get("report", {})
    components = [c.get("name", "") for c in report.get("components", [])]
    categories = list({t.get("stride_category", "") for t in report.get("threats", [])})

    guard_prompt = (
        "Você é um filtro de conteúdo para um assistente especializado em análise de segurança.\n\n"
        "O assistente SOMENTE atende perguntas sobre:\n"
        f"  - Componentes desta arquitetura: {', '.join(components) if components else 'não identificados'}\n"
        f"  - Categorias STRIDE presentes: {', '.join(categories) if categories else 'nenhuma'}\n"
        "  - Ameaças, mitigações, scores de risco e STRIDE aplicado a este sistema\n"
        "  - Segurança, criptografia, autenticação, autorização, monitoramento\n"
        "  - Padrões de segurança como OWASP, MITRE ATT&CK, NIST, CWE\n\n"
        f'Pergunta do usuário: "{user_text}"\n\n'
        "Classifique a pergunta:\n"
        "  ALLOW — se for sobre segurança, STRIDE, os componentes/ameaças desta análise "
        "ou qualquer tópico de segurança de sistemas em geral\n"
        "  BLOCK: <motivo curto> — SOMENTE se for claramente fora do domínio de segurança "
        "(ex: culinária, esportes, política, entretenimento)\n\n"
        "Responda com UMA linha: ALLOW ou BLOCK: <motivo>. Seja permissivo com tópicos de segurança."
    )

    try:
        llm_guard = _build_llm(temperature=0)
        response = await llm_guard.ainvoke([HumanMessage(content=guard_prompt)])
        result = response.content.strip()

        if result.upper().startswith("ALLOW"):
            return {"guardrail_passed": True, "refusal_reason": ""}

        reason = result.split(":", 1)[1].strip() if ":" in result else "Tópico fora do escopo"
        logger.info("Guardrail BLOCK: %s | user_text: %.80s", reason, user_text)
        return {"guardrail_passed": False, "refusal_reason": reason}

    except Exception as exc:
        # Em caso de falha no guardrail, passa para não bloquear o usuário
        logger.warning("Guardrail falhou, passando por padrão: %s", exc)
        return {"guardrail_passed": True, "refusal_reason": ""}


async def respond_node(state: ReportChatState) -> dict:
    """
    Nó de resposta: LLM com ferramentas STRIDE, usando o histórico completo de mensagens.
    """
    llm = _build_llm(temperature=0.7)
    llm_with_tools = llm.bind_tools(STRIDE_TOOLS)
    response = await llm_with_tools.ainvoke(state["messages"])
    return {"messages": [response]}


async def tools_node_fn(state: ReportChatState) -> dict:
    """Executa as ferramentas chamadas pelo LLM."""
    tool_executor = ToolNode(STRIDE_TOOLS)
    result = await tool_executor.ainvoke(state)
    return result


async def refuse_node(state: ReportChatState) -> dict:
    """
    Retorna uma recusa gentil com sugestões de perguntas relevantes.
    """
    reason = state.get("refusal_reason", "tópico fora do escopo")
    context = state.get("analysis_context", {})
    report = context.get("report", {})
    threats = report.get("threats", [])

    # Sugere uma pergunta baseada numa ameaça real do relatório, se disponível
    suggestion = ""
    if threats:
        first_threat = threats[0]
        suggestion = (
            f' Que tal perguntar sobre a ameaça '
            f'"{first_threat.get("title", "identificada")}" '
            f'ou como mitigar riscos de '
            f'{first_threat.get("stride_category", "segurança")}?'
        )

    refusal_text = (
        f"Desculpe, não posso responder sobre esse assunto ({reason}). "
        "Meu escopo se limita à análise de segurança desta arquitetura específica: "
        "ameaças identificadas, componentes, mitigações, scores de risco e padrões de segurança."
        f"{suggestion}"
    )

    return {"messages": [AIMessage(content=refusal_text)]}


# ---------------------------------------------------------------------------
# Funções de roteamento
# ---------------------------------------------------------------------------


def _route_entry(state: ReportChatState) -> str:
    return "inject_context" if not state.get("session_initialized") else "guardrail"


def _route_guardrail(state: ReportChatState) -> str:
    return "respond" if state.get("guardrail_passed", True) else "refuse"


def _route_respond(state: ReportChatState) -> str:
    """Se o LLM retornou tool_calls, vai para o nó de ferramentas; senão encerra."""
    last_msg = state["messages"][-1] if state["messages"] else None
    if last_msg and hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return END


# ---------------------------------------------------------------------------
# Construção do grafo
# ---------------------------------------------------------------------------


def build_report_chat_graph():
    """Compila o StateGraph com guardrail, injeção de contexto e ReAct loop."""
    builder = StateGraph(ReportChatState)

    builder.add_node("inject_context", inject_context_node)
    builder.add_node("guardrail", guardrail_node)
    builder.add_node("respond", respond_node)
    builder.add_node("tools", ToolNode(STRIDE_TOOLS))
    builder.add_node("refuse", refuse_node)

    # Roteamento de entrada
    builder.add_conditional_edges(
        START,
        _route_entry,
        {"inject_context": "inject_context", "guardrail": "guardrail"},
    )
    builder.add_edge("inject_context", "guardrail")

    # Após o guardrail
    builder.add_conditional_edges(
        "guardrail",
        _route_guardrail,
        {"respond": "respond", "refuse": "refuse"},
    )

    # ReAct loop: respond → tools → respond (ou END)
    builder.add_conditional_edges(
        "respond",
        _route_respond,
        {"tools": "tools", END: END},
    )
    builder.add_edge("tools", "respond")
    builder.add_edge("refuse", END)

    memory = MemorySaver()
    return builder.compile(checkpointer=memory)


# Singleton — memória compartilhada por session_id (thread_id)
report_chat_graph = build_report_chat_graph()
