"""Application settings loaded from environment variables and the local ``.env`` file."""
from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv



@dataclass(frozen=True)
class Settings:
    """Runtime configuration for MongoDB, Ollama, and optional notifications."""

    mongo_uri: str
    mongo_db: str
    ollama_host: str
    ollama_model: str
    max_agent_steps: int
    slack_webhook_url: str | None


def get_settings() -> Settings:
    """Load settings, using ``.env`` values when present and documented defaults otherwise."""
    load_dotenv()
    max_agent_steps = int(os.getenv("MAX_AGENT_STEPS", "4"))
    if max_agent_steps < 1:
        raise ValueError("MAX_AGENT_STEPS must be at least 1")

    webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    return Settings(
        mongo_uri=os.getenv("MONGO_URI", "mongodb://localhost:27017"),
        mongo_db=os.getenv("MONGO_DB", "anvesaka"),
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"),
        max_agent_steps=max_agent_steps,
        slack_webhook_url=webhook or None,
    )


settings = get_settings()
