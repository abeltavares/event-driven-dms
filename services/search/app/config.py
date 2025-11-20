from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    elasticsearch_url: str = "http://elasticsearch:9200"
    elasticsearch_index: str = "documents"
    service_name: str = "search"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()
