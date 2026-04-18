"""Application configuration from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Jarvis AI Assistant"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8765

    # Primary LLM — NVIDIA NIM (OpenAI-compatible)
    nim_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        description="NVIDIA NIM OpenAI-compatible base URL",
    )
    nim_api_key: str = ""
    nim_fast_model: str = "meta/llama-3.1-8b-instruct"
    nim_smart_model: str = "meta/llama-3.1-70b-instruct"
    vision_fast_model: str = "nvidia/nemotron-3-nano-vl-8b-v1"
    vision_smart_model: str = "meta/llama-3.2-90b-vision-instruct"
    vision_passive_interval: float = 4.0
    vision_active_interval: float = 1.0
    vision_diff_threshold: float = 0.018

    # Fallback — Ollama
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma2:latest"

    # AWS Bedrock (used by code_assistant app_builder only)
    bedrock_enabled: bool = False
    aws_region: str = "us-east-1"
    bedrock_claude_model_id: str = "anthropic.claude-3-7-sonnet-20250219-v1:0"
    aws_bearer_token_bedrock: str = ""

    # Whisper
    whisper_model: str = "base"
    whisper_device: str = "cpu"

    # Porcupine wake word
    porcupine_access_key: str = ""
    porcupine_keyword_path: str = ""

    # Weather / News
    weatherapi_api_key: str = ""
    weatherapi_city_default: str = "London"
    newsapi_key: str = ""
    google_maps_api_key: str = ""

    # Google OAuth — paths to client secrets JSON
    google_credentials_path: str = ""
    google_token_path: str = ""
    google_oauth_local: bool = False

    # Data directories
    data_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2] / "data")
    chroma_path: str = ""

    # Safety
    require_confirmation_destructive: bool = True

    # Auth — set to False to disable token checks (e.g. during local dev)
    auth_enabled: bool = True

    # Command safety — deny-list check before terminal_command execution
    command_safety_enabled: bool = True

    # Web Agent skill — browser automation via browser-use + NVIDIA NIM VLM
    web_agent_model: str = "nvidia/llama-3.2-90b-vision-instruct"
    web_agent_headless: bool = False
    web_agent_max_steps: int = 15
    web_agent_timeout: int = 120

    # WhatsApp — Node bridge (jarvis-whatsapp-automation / Baileys index.js)
    whatsapp_node_url: str = Field(
        default="http://127.0.0.1:3000",
        description="Express server from integrations/jarvis-whatsapp-automation (POST /send)",
    )

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "jarvis.sqlite3"

    @property
    def chroma_persist(self) -> Path:
        if self.chroma_path:
            return Path(self.chroma_path)
        return self.data_dir / "chroma"

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug(cls, value: object) -> object:
        """Accept common non-boolean env values like DEBUG=release/dev."""
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"release", "prod", "production"}:
                return False
            if lowered in {"dev", "development", "debug"}:
                return True
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
