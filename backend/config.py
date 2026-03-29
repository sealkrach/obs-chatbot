from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        case_sensitive=False, extra="ignore",
    )
    obs_api_url:          str = "http://localhost:8000"
    obs_api_key:          str = ""
    victoriametrics_url:  str = "http://localhost:8428"
    ollama_base_url:      str = "http://localhost:11434"
    ollama_model:         str = "llama3.1"
    chatbot_host:         str = "0.0.0.0"
    chatbot_port:         int = 8001
    chatbot_secret_key:   str = "changeme"
    teams_app_id:         str = ""
    teams_app_password:   str = ""
    cors_origins:         str = "http://localhost:5173,http://localhost:3000"
    # LLM provider: "ollama" or "openai"
    llm_provider:         str = "ollama"
    openai_api_key:       str = ""
    openai_model:         str = "gpt-4o-mini"
    openai_base_url:      str = "https://api.openai.com/v1"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def obs_headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.obs_api_key:
            h["Authorization"] = f"Bearer {self.obs_api_key}"
        return h


@lru_cache
def get_settings() -> Settings:
    return Settings()
