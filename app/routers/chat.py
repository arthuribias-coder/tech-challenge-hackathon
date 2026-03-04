import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from google.genai.errors import ClientError, ServerError
from pydantic import BaseModel, Field

from app.services.chat_service import send_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])
templates = Jinja2Templates(directory="app/templates")


class ChatMessage(BaseModel):
    role: str = Field(description="'user' ou 'assistant'")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str


@router.get("/", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    """Página do chat com o assistente Gemini especialista em STRIDE."""
    return templates.TemplateResponse("chat.html", {"request": request})


@router.post("/message", response_model=ChatResponse)
async def chat_message(body: ChatRequest) -> ChatResponse:
    """
    Recebe uma mensagem do usuário e retorna a resposta do Gemini.
    O histórico é mantido no frontend e enviado a cada requisição.
    """
    try:
        history = [msg.model_dump() for msg in body.history]
        reply = await send_message(body.message, history)
        return ChatResponse(reply=reply)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ClientError as exc:
        http_status = exc.status_code or 400
        if http_status == 429:
            detail = "Cota da API Gemini esgotada ou limite de requisições atingido. Tente novamente em alguns instantes."
        elif http_status in (401, 403):
            detail = "Chave de API Gemini inválida ou sem permissão. Verifique a variável GEMINI_API_KEY."
        else:
            detail = f"Erro da API Gemini: {exc}"
        raise HTTPException(status_code=http_status, detail=detail) from exc
    except ServerError as exc:
        logger.error("Erro no servidor Gemini: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="O servidor da API Gemini retornou um erro. Tente novamente.",
        ) from exc
    except Exception as exc:
        logger.exception("Erro inesperado no chat: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao processar a mensagem. Tente novamente.",
        ) from exc
