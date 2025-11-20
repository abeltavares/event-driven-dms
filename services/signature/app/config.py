from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str

    redis_url: str

    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool = False

    service_name: str = "signature"

    document_service_url: str = "http://document-service:8000"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()
