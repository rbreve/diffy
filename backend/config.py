"""Application configuration sourced from the environment / ``.env`` file."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the diff viewer backend.

    :ivar github_token: Personal access token used to authenticate GitHub API
        calls. Optional; raises rate limits and grants private-repo access.
    :ivar anthropic_api_key: API key for the Anthropic SDK. Enables the AI
        endpoints (chat, summary, inline issues) via Anthropic directly.
    :ivar anthropic_model: Claude model identifier used for Anthropic calls.
    :ivar openrouter_api_key: API key for OpenRouter. When set, the AI endpoints
        use OpenRouter (OpenAI-compatible) instead of Anthropic directly.
    :ivar openrouter_model: OpenRouter model slug (e.g. ``anthropic/claude-sonnet-4.5``
        or ``openai/gpt-4o``) used for all OpenRouter calls.
    :ivar max_file_bytes: Files larger than this are not fetched for full-text
        diffing; the viewer shows a "too large" placeholder instead.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(default="openai/gpt-4o-mini", alias="OPENROUTER_MODEL")
    max_file_bytes: int = Field(default=1_000_000, alias="MAX_FILE_BYTES")


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    :returns: The process-wide settings object.
    """
    return Settings()
