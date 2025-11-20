from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    kafka_bootstrap_servers: str
    kafka_consumer_group: str = "event-processor-group"
    elasticsearch_url: str = "http://elasticsearch:9200"
    elasticsearch_index_documents: str = "documents"
    cdc_documents_topic: str = "cdc.documents"
    service_name: str = "event"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings():
    return Settings()
