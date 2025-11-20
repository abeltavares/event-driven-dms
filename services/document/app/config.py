from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str

    redis_url: str
    redis_cache_ttl: int = 300  # 5 minutes

    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool = False
    minio_bucket_documents: str = "documents"

    service_name: str = "document-service"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings():
    return Settings()
