"""Runtime LLM configuration — shared between main and agents.
Persisted to /app/data/llm_config.json so config survives restarts.
"""
import json
import os
import logging
from pathlib import Path

from backend.config import get_settings

log = logging.getLogger(__name__)
cfg = get_settings()

_CONFIG_FILE = Path(os.getenv("LLM_CONFIG_PATH", "/app/data/llm_config.json"))

_defaults = {
    "provider": cfg.llm_provider,
    "openai_api_key": cfg.openai_api_key,
    "openai_model": cfg.openai_model,
    "openai_base_url": cfg.openai_base_url,
    "ollama_model": cfg.ollama_model,
}


def _load() -> dict:
    """Load config from file, falling back to defaults."""
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE) as f:
                saved = json.load(f)
            # Merge with defaults so new keys are always present
            merged = {**_defaults, **saved}
            log.info("Loaded LLM config from %s (provider=%s)", _CONFIG_FILE, merged["provider"])
            return merged
        except Exception as e:
            log.warning("Failed to load LLM config: %s", e)
    return dict(_defaults)


def _save(config: dict):
    """Persist config to file."""
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        log.info("Saved LLM config to %s", _CONFIG_FILE)
    except Exception as e:
        log.warning("Failed to save LLM config: %s", e)


_llm_config = _load()


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
    _save(_llm_config)
