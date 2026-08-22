from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SentinelLoop API"
    app_env: str = "development"
    database_url: str = "sqlite:///./data/sentinelloop.db"
    frontend_origin: str = "http://localhost:3000"
    authorized_target_hosts: str = "fake-target"
    target_registration_mode: Literal["attested", "allowlisted"] = "attested"
    ai_mode: str = "deterministic"
    investigator_base_url: str = "https://api.openai.com/v1"
    investigator_api_key: str = ""
    investigator_model: str = "gpt-5-mini"
    critic_base_url: str = "https://api.openai.com/v1"
    critic_api_key: str = ""
    critic_model: str = "gpt-5-mini"
    model_timeout_seconds: float = 45.0
    model_retry_attempts: int = 3
    model_retry_max_delay_seconds: float = 8.0
    tool_timeout_seconds: float = 10.0
    max_investigator_calls: int = 8
    max_critic_calls: int = 5
    max_tool_calls: int = 10
    debug_failures_enabled: bool = True

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
