from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "websocket-service"

    kafka_bootstrap_servers: str
    kafka_consumer_group: str = "websocket-consumer-group"
    cdc_documents_topic: str = "cdc.documents"
    cdc_signatures_topic: str = "cdc.signatures"

    jwt_secret_key: str = "secret-key"
    jwt_algorithm: str = "HS256"

    websocket_ping_interval: int = 30  # seconds
    websocket_ping_timeout: int = 10  # seconds

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()
