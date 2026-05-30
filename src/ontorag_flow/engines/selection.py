"""Engine selection — pick a decision engine per process.

The :class:`~ontorag_flow.core.case_manager.CaseManager` takes an
``engine_factory: Callable[[ProcessDefinition], DecisionEngine]`` but stays
agnostic about *which* engine. This resolver supplies that callable: it holds the
backing clients (an ontorag MCP client for Bayesian, an LLM client for the agent
engine) and, given a process, builds the engine the process asks for.

Selection order: an explicit ``process.engine`` wins; otherwise it is inferred
from the config present (a ``bayesian`` block implies the Bayesian engine, a
non-empty ``rules`` list implies the rule engine); failing both, the configured
default. If a process asks for an engine whose backing client was not provided,
:class:`EngineUnavailableError` is raised with an actionable message.
"""

from __future__ import annotations

from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.registry import ActionRegistry
from ontorag_flow.engines.base import DecisionEngine
from ontorag_flow.engines.bayesian import BayesianMpeEngine, SupportsToolCall
from ontorag_flow.engines.causal import CausalSimulationEngine
from ontorag_flow.engines.human import HumanReviewEngine
from ontorag_flow.engines.llm_agent import LlmAgentEngine, LlmClient
from ontorag_flow.engines.rule import RuleEngine
from ontorag_flow.log import get_logger

logger = get_logger(__name__)

__all__ = ["EngineResolver", "EngineUnavailableError"]

_VALID_KINDS = frozenset({"rule", "bayesian", "causal", "llm", "human"})


class EngineUnavailableError(RuntimeError):
    """A process requests an engine whose backing client is not configured."""


class EngineResolver:
    """Builds the right :class:`DecisionEngine` for a process."""

    def __init__(
        self,
        *,
        registry: ActionRegistry | None = None,
        ontorag_client: SupportsToolCall | None = None,
        llm_client: LlmClient | None = None,
        default: str = "rule",
    ) -> None:
        """Bind the resolver to the clients its engines may need.

        Args:
            registry: Action registry, used to enrich LLM prompts.
            ontorag_client: A connected ontorag MCP client for the Bayesian engine.
            llm_client: An LLM client for the agent engine.
            default: Engine kind to use when a process declares/implies none.
        """

        self._registry = registry
        self._ontorag_client = ontorag_client
        self._llm_client = llm_client
        self._default = default

    def kind_for(self, process: ProcessDefinition) -> str:
        """Resolve the engine kind for a process (explicit, inferred, or default).

        Raises:
            EngineUnavailableError: If ``process.engine`` names an unknown kind.
        """

        if process.engine:
            kind = process.engine.lower()
            if kind not in _VALID_KINDS:
                raise EngineUnavailableError(
                    f"Unknown engine {process.engine!r}; expected one of {sorted(_VALID_KINDS)}."
                )
            return kind
        if process.causal is not None:
            return "causal"
        if process.bayesian is not None:
            return "bayesian"
        if process.rules:
            return "rule"
        return self._default

    def for_process(self, process: ProcessDefinition) -> DecisionEngine:
        """Build the decision engine the process resolves to.

        Raises:
            EngineUnavailableError: If the resolved engine needs a client that
                was not configured.
        """

        kind = self.kind_for(process)
        if kind == "rule":
            return RuleEngine.from_process(process)
        if kind == "human":
            return HumanReviewEngine()
        if kind == "bayesian":
            if self._ontorag_client is None:
                raise EngineUnavailableError(
                    "Process requests the Bayesian engine, but no ontorag client "
                    "is configured (requires a live ontorag v0.7; set "
                    "CONNECT_ONTORAG=true and ensure the server is reachable)."
                )
            return BayesianMpeEngine(self._ontorag_client)
        if kind == "causal":
            if self._ontorag_client is None:
                raise EngineUnavailableError(
                    "Process requests the Causal engine, but no ontorag client "
                    "is configured (requires a live ontorag v0.8; set "
                    "CONNECT_ONTORAG=true and ensure the server is reachable)."
                )
            return CausalSimulationEngine(self._ontorag_client)
        if kind == "llm":
            if self._llm_client is None:
                raise EngineUnavailableError(
                    "Process requests the LLM engine, but no LLM client is "
                    "configured (set LLM_PROVIDER, e.g. anthropic|openai|ollama)."
                )
            return LlmAgentEngine(self._llm_client, registry=self._registry)
        raise EngineUnavailableError(f"Unsupported engine kind: {kind!r}")
