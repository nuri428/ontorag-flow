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
    ontorag_mcp_https_only: bool = Field(
        default=False,
        alias="ONTORAG_MCP_HTTPS_ONLY",
        description=(
            "When true, refuse to connect to ontorag MCP unless the URL uses "
            "https://. Protects against accidental plain-text deployments and "
            "URL hijack via env-var manipulation."
        ),
    )
    ontorag_expected_version: str | None = Field(
        default=None,
        alias="ONTORAG_EXPECTED_VERSION",
        description=(
            "Optional pinned ontorag server version string. When set, the "
            "client verifies the server's reported version after connect "
            "and logs a WARN (does not abort) on mismatch — drift detection "
            "for the trust boundary between the two repos."
        ),
    )
    plugin_allowlist: str | None = Field(
        default=None,
        alias="ONTORAG_FLOW_PLUGIN_ALLOWLIST",
        description=(
            "Comma-separated list of entry-point names from the "
            "'ontorag_flow.actions' group that are allowed to load. When set, "
            "any other discovered plugin is skipped (logged as WARN). Unset = "
            "all plugins load (backward-compatible default)."
        ),
    )
    audit_retention_days: int | None = Field(
        default=None,
        alias="AUDIT_RETENTION_DAYS",
        description=(
            "Default retention window for `ontorag-flow audit prune` when "
            "`--older-than` is not supplied. Cases that are closed or failed "
            "AND whose newest activity is older than this many days are "
            "deleted (case row + activities). Unset = no default; the CLI "
            "requires an explicit window."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process-wide :class:`Settings` instance."""

    return Settings()
