"""Runtime configuration loaded from environment / ``.env``.

ontorag-flow stores no domain ontology data; the only configuration it needs is
where to find the ontorag MCP server, who it is acting as (for provenance), and
how to bind its own API.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide settings.

    Environment variable names match the field aliases (see ``.env.example``).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    ontorag_mcp_url: str = Field(
        default="http://localhost:8000/mcp",
        alias="ONTORAG_MCP_URL",
        description="MCP endpoint of the ontorag server consumed as a client.",
    )
    agent_id: str = Field(
        default="urn:ontorag-flow:agent:system",
        alias="AGENT_ID",
        description="Agent identity recorded as prov:wasAssociatedWith.",
    )
    db_path: str = Field(
        default="ontorag_flow.db",
        alias="DATABASE_PATH",
        description="SQLite file for case state, processes, and the audit log.",
    )
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8100, alias="API_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Decision-engine wiring (see EngineResolver). The rule engine always works;
    # the others are enabled only when their backing client is configured.
    llm_provider: str | None = Field(
        default=None,
        alias="LLM_PROVIDER",
        description="LLM provider for LlmAgentEngine: anthropic | openai | ollama.",
    )
    llm_model: str | None = Field(
        default=None, alias="LLM_MODEL", description="LLM model override."
    )
    connect_ontorag: bool = Field(
        default=False,
        alias="CONNECT_ONTORAG",
        description="Open an ontorag MCP connection at startup to enable the Bayesian engine.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process-wide :class:`Settings` instance."""

    return Settings()
