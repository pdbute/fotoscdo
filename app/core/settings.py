from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    PG_HOST: str = "localhost"
    PG_PORT: int = 5432
    PG_DB: str = "fotoscdo"
    PG_USER: str = "postgres"
    PG_PASSWORD: str = "postgres"

    SFTP_HOST: str = "localhost"
    SFTP_PORT: int = 2222
    SFTP_USER: str = "pablo"
    SFTP_PASSWORD: str = "pablo"
    SFTP_BASE_PATH: str = "/upload"

    MAX_IMAGE_SIZE_BYTES: int = 1_048_576
    DEFAULT_SEARCH_RADIUS_M: int = 200

    ENABLE_OTEL: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    OTEL_SERVICE_NAME: str = "fotoscdo-api"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

@lru_cache
def get_settings() -> Settings:
    return Settings()