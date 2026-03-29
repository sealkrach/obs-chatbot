"""Runtime LLM configuration — shared between main and agents."""
from backend.config import get_settings

cfg = get_settings()

_llm_config = {
    "provider": cfg.llm_provider,
    "openai_api_key": cfg.openai_api_key,
    "openai_model": cfg.openai_model,
    "openai_base_url": cfg.openai_base_url,
    "ollama_model": cfg.ollama_model,
}


def get_llm_config() -> dict:
    return _llm_config


def update_llm_config(
    provider: str,
    openai_api_key: str,
    openai_model: str,
    openai_base_url: str,
    ollama_model: str,
) -> None:
    _llm_config["provider"] = provider
    if openai_api_key:
        _llm_config["openai_api_key"] = openai_api_key
    _llm_config["openai_model"] = openai_model
    _llm_config["openai_base_url"] = openai_base_url
    _llm_config["ollama_model"] = ollama_model
