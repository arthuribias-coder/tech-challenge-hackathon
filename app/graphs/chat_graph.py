"""
Grafo LangGraph de chat agêntico com ReAct pattern.

Diferenças em relação ao chat_service.py original:
- ReAct Agent: o modelo pode chamar tools antes de responder
- MemorySaver: histórico da conversa persistido por thread_id (sessão)
- Streaming: suporta astream_events para tokens individuais
- Tools disponíveis: explain_stride, calculate_risk, map_to_mitre, get_owasp

Uso:
    result = await chat_graph.ainvoke(
        {"messages": [HumanMessage(content=user_message)]},
        config={"configurable": {"thread_id": session_id}},
    )

Streaming:
    async for event in chat_graph.astream_events(
        {"messages": [HumanMessage(content=user_message)]},
        config={"configurable": {"thread_id": session_id}},
        version="v2",
    ):
        ...
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from app.tools.stride_tools import STRIDE_TOOLS
from app.utils.llm import create_chat_llm

# ---------------------------------------------------------------------------
# System prompt do especialista STRIDE
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "Você é um especialista sênior em segurança de sistemas e modelagem de ameaças (Threat Modeling). "
    "Seu papel é auxiliar arquitetos e desenvolvedores a identificar e mitigar vulnerabilidades "
    "usando a metodologia STRIDE.\n\n"
    "Você possui domínio em:\n"
    "- Metodologia STRIDE e todas as suas categorias\n"
    "- OWASP Top 10, SANS Top 25 e Secure by Design\n"
    "- Arquiteturas modernas: microserviços, serverless, cloud-native, containers\n"
    "- Padrões de segurança: Zero Trust, Defense in Depth, Least Privilege\n"
    "- MITRE ATT&CK, CVEs, CWEs\n"
    "- Ferramentas: OWASP Threat Dragon, Microsoft Threat Modeling Tool\n\n"
    "Ao responder:\n"
    "- Use as ferramentas disponíveis para fornecer informações precisas e atualizadas\n"
    "- Seja objetivo e prático, com exemplos concretos\n"
    "- Identifique sempre a categoria STRIDE relevante\n"
    "- Sugira contramedidas específicas e implementáveis\n"
    "- Responda SEMPRE em português brasileiro\n"
    "- Quando usar uma ferramenta, explique o que está fazendo\n"
)

# ---------------------------------------------------------------------------
# Construção do grafo
# ---------------------------------------------------------------------------


def _build_chat_graph():
    """Constrói o agente ReAct com memória e ferramentas STRIDE."""
    llm = create_chat_llm()

    memory = MemorySaver()

    return create_react_agent(
        model=llm,
        tools=STRIDE_TOOLS,
        checkpointer=memory,
        prompt=_SYSTEM_PROMPT,
    )


# Instância singleton — memória compartilhada entre requests (por thread_id)
chat_graph = _build_chat_graph()
