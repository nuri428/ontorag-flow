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
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8100, alias="API_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process-wide :class:`Settings` instance."""

    return Settings()
