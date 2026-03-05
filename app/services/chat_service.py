"""
Serviço de chat com Google Gemini.
Mantém histórico de conversa e atua como assistente especialista em STRIDE e segurança de sistemas.

.. deprecated::
    Lógica legada da versão pré-LangGraph. A lógica ativa está em
    ``app/graphs/chat_graph.py`` (ReAct agent com MemorySaver).
    Este módulo será removido em uma versão futura.
"""

import logging

from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTION = """
Você é um especialista sênior em segurança de sistemas e modelagem de ameaças (Threat Modeling).
Seu papel é auxiliar arquitetos de software e desenvolvedores a identificar e mitigar 
vulnerabilidades em seus sistemas utilizando a metodologia STRIDE.

Você possui profundo conhecimento em:
- Metodologia STRIDE (Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege)
- OWASP Top 10 e práticas de segurança por design (Secure by Design)
- Arquiteturas de software (microserviços, monolíticos, serverless, cloud-native)
- Padrões de segurança: Zero Trust, Defense in Depth, Least Privilege
- Ferramentas de threat modeling: Microsoft Threat Modeling Tool, OWASP Threat Dragon
- CVEs, CWEs e frameworks como MITRE ATT&CK

Ao responder:
- Seja objetivo e prático, com exemplos concretos quando útil
- Identifique sempre a categoria STRIDE relevante quando discutir ameaças
- Sugira contramedidas específicas e implementáveis
- Use linguagem técnica mas acessível
- Responda sempre em português brasileiro
"""


def build_gemini_history(
    history: list[dict[str, str]],
) -> list[types.Content]:
    """Converte o histórico de mensagens do frontend para o formato do Gemini."""
    contents: list[types.Content] = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(
            types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])])
        )
    return contents


async def send_message(
    user_message: str,
    history: list[dict[str, str]],
) -> str:
    """
    Envia uma mensagem ao Gemini com o histórico da conversa.
    Retorna a resposta em texto.
    """
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY não configurada. Defina a variável de ambiente.")

    client = genai.Client(api_key=settings.gemini_api_key)

    gemini_history = build_gemini_history(history)

    chat = client.aio.chats.create(
        model=settings.gemini_model,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            temperature=0.7,
            max_output_tokens=2048,
        ),
        history=gemini_history,
    )

    logger.info("Enviando mensagem ao Gemini (histórico: %d msgs)", len(history))
    response = await chat.send_message(user_message)

    return response.text or ""
