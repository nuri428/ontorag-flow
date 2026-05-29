"""BayesianMpeEngine — a probabilistic decision engine over ontorag's MCP layer.

Where the :class:`~ontorag_flow.engines.rule.RuleEngine` fires declarative
decision-table rows, this engine *scores* candidate actions by the posterior
probability they confer on a target proposition. For each candidate it asks
ontorag to compute ``P(target | evidence ∪ candidate.evidence)`` and ranks the
candidates best-first by that posterior. Like every engine it only *proposes*;
it never executes anything.

Config is declared as data on the process's opaque ``bayesian`` block (parsed
here, exactly as :class:`RuleEngine` parses ``process.rules``)::

    bayesian:
      target: { diagnosed: true }          # goal proposition whose posterior we maximize
      query_tool: "compute_posterior"      # optional, default "compute_posterior"
      candidates:
        - action: "urn:ontorag-flow:action:UpdateCaseProperty"
          params: { key: triage_level, value: urgent }
          evidence: { severity: high }     # extra evidence assumed if this action runs

Wiring note
-----------
Unlike :class:`RuleEngine` (which is built from a process alone), this engine
needs a live ontorag MCP client to score candidates. Because ontorag's Bayesian
tools (``compute_posterior``, ``mpe``) require **ontorag v0.7** — whose response
schema is not yet finalized — this engine is **not** wired into the default app
factory. That wiring waits for a live ontorag v0.7 instance; for now it is
constructed explicitly with a client (the real :class:`OntoragClient` satisfies
the :class:`SupportsToolCall` protocol, and tests pass a fake).
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from ontorag_flow.core.action import ActionProposal
from ontorag_flow.core.case import Case
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.log import get_logger

logger = get_logger(__name__)

__all__ = ["BayesianMpeEngine", "BayesianConfig", "BayesianCandidate", "SupportsToolCall"]


class SupportsToolCall(Protocol):
    """Minimal structural contract for anything that can call an MCP tool.

    The real :class:`~ontorag_flow.ontorag_client.client.OntoragClient` satisfies
    this; tests supply a fake. Keeping the dependency this narrow lets the engine
    be exercised without a live ontorag server.
    """

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


class BayesianCandidate(BaseModel):
    """One candidate action to be scored by its posterior on the target."""

    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra evidence assumed present if this candidate is taken.",
    )


class BayesianConfig(BaseModel):
    """Parsed view of a process's opaque ``bayesian`` block."""

    target: dict[str, Any] = Field(
        description="The goal proposition whose posterior we maximize.",
    )
    query_tool: str = Field(
        default="compute_posterior",
        description="Name of the ontorag MCP tool that computes the posterior.",
    )
    candidates: list[BayesianCandidate] = Field(default_factory=list)


from ontorag_flow.engines._posteriors import extract_posterior as _extract_posterior

# Re-exported for backward compatibility; the canonical helper now lives in
# ``engines/_posteriors.py`` so the Causal engine can share it without a cycle.


class BayesianMpeEngine:
    """Scores candidate actions by the posterior they confer on a target.

    The engine is config-driven from ``process.bayesian``; it needs an ontorag
    MCP client (anything satisfying :class:`SupportsToolCall`) to compute the
    posteriors.
    """

    def __init__(self, client: SupportsToolCall) -> None:
        """Bind the engine to an ontorag MCP client.

        Args:
            client: Anything with ``async call_tool(name, arguments)`` — the real
                :class:`OntoragClient` or a test fake.
        """

        self._client = client

    async def propose_next(
        self, case: Case, process: ProcessDefinition
    ) -> list[ActionProposal]:
        """Score every allowed candidate and return proposals ranked best-first.

        For each configured candidate whose action the process allows, the engine
        merges the case's current properties with the candidate's extra evidence,
        asks ontorag for ``P(target | evidence)``, and emits an
        :class:`ActionProposal` with that posterior as its confidence. Candidates
        whose action is not allowed are skipped (with a warning).

        Args:
            case: The case whose properties form the base evidence.
            process: The governing process; supplies the ``bayesian`` config and
                the allowed-action set.

        Returns:
            Proposals ranked by confidence (posterior), highest first. Empty if
            the process declares no ``bayesian`` config.
        """

        if process.bayesian is None:
            return []

        config = BayesianConfig.model_validate(process.bayesian)
        base_evidence = dict(case.state.properties)

        proposals: list[ActionProposal] = []
        for candidate in config.candidates:
            if not process.allows(candidate.action):
                logger.warning(
                    "Bayesian candidate proposes disallowed action %s; skipping.",
                    candidate.action,
                )
                continue

            evidence = {**base_evidence, **candidate.evidence}
            result = await self._client.call_tool(
                config.query_tool,
                {"evidence": evidence, "query": config.target},
            )
            posterior = _extract_posterior(result)

            proposals.append(
                ActionProposal(
                    action_uri=candidate.action,
                    params=candidate.params,
                    confidence=posterior,
                    rationale=f"P(target | action) ≈ {posterior:.2f}",
                    proposed_by="BayesianMpeEngine",
                )
            )

        proposals.sort(key=lambda proposal: proposal.confidence or 0.0, reverse=True)
        return proposals
