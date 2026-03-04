import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # App
    debug: bool = False
    max_upload_size_mb: int = 10
    upload_dir: str = "uploads"

    # LangSmith — observabilidade opcional (deixe em branco para desabilitar)
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "stride-threat-modeler"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


settings = Settings()

# Ativa o tracing do LangSmith se configurado
if settings.langchain_tracing_v2 and settings.langchain_api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
