import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"          # análise de diagramas (suporta visão)
    gemini_chat_model: str = "gemini-2.0-flash"     # chat multiturno com tools (sem thinking obrigatório)
    gemini_validator_model: str = "gemini-2.0-flash-lite"  # validação de diagrama (modelo econômico)

    # App
    debug: bool = False
    max_upload_size_mb: int = 10
    upload_dir: str = "uploads"

    # Fine-Tuning
    models_dir: str = "app/models"
    finetuned_models_dir: str = "app/models/finetuned"
    training_data_dir: str = "app/data/training"
    yolo_training_enabled: bool = True
    yolo_default_epochs: int = 50
    yolo_default_batch_size: int = 16
    yolo_default_img_size: int = 640
    yolo_default_patience: int = 20

    # Roboflow — API key para download de datasets públicos/privados do Universe
    # Obtenha gratuitamente em: https://roboflow.com/
    roboflow_api_key: str = ""

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
