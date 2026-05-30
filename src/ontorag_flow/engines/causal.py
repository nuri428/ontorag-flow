"""CausalSimulationEngine — Pearl Rung 2/3 over ontorag's causal MCP tools.

Where :class:`~ontorag_flow.engines.bayesian.BayesianMpeEngine` asks
``P(target | evidence)`` (observational, Rung 1), this engine asks
``P(target | do(intervention))`` (interventional, Rung 2). Same shape — config
on ``process.causal``, candidates with declared interventions, ranked by
posterior — but the tool it calls is ``do_query``, so the score reflects the
*effect of acting*, not mere correlation.

The engine also offers two extras CLAUDE.md flags for v0.8:

* :meth:`CausalSimulationEngine.counterfactual_replay` — "what if at activity X
  we had taken action Y instead?", using ontorag's ``counterfactual`` tool
  (Rung 3).
* :class:`StackedEngine` — wraps a proposer engine (LLM or Bayesian) and uses a
  causal validator to re-score each proposal by its interventional posterior,
  making causal sim the final arbitrator over BN/LLM picks.

Like every engine here it only *proposes*; it never executes anything. Needs an
ontorag MCP client (anything satisfying :class:`SupportsToolCall`); the engine
is not wired into the default app factory until a live ontorag v0.8 is
configured, exactly as for the Bayesian engine.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ontorag_flow.core.action import ActionProposal
from ontorag_flow.core.case import Case
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.engines._posteriors import extract_posterior
from ontorag_flow.engines.base import DecisionEngine
from ontorag_flow.engines.bayesian import SupportsToolCall
from ontorag_flow.log import get_logger

logger = get_logger(__name__)

__all__ = [
    "CausalSimulationEngine",
    "CausalConfig",
    "CausalCandidate",
    "CounterfactualResult",
    "StackedEngine",
]


class CausalCandidate(BaseModel):
    """One candidate action and the intervention assumed when it runs."""

    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    intervention: dict[str, Any] = Field(
        default_factory=dict,
        description="Variables to set under do() when scoring this candidate.",
    )


class CausalConfig(BaseModel):
    """Parsed view of a process's opaque ``causal`` block."""

    target: dict[str, Any] = Field(
        description="The goal proposition whose interventional posterior we maximize.",
    )
    query_tool: str = Field(
        default="do_query",
        description="Name of the ontorag MCP tool that runs the intervention query.",
    )
    candidates: list[CausalCandidate] = Field(default_factory=list)


class CounterfactualResult(BaseModel):
    """The outcome of a counterfactual replay."""

    case_uri: str
    swapped_activity_uri: str
    counterfactual_action_uri: str
    counterfactual_params: dict[str, Any]
    target: dict[str, Any]
    posterior: float
    rationale: str


class CausalSimulationEngine:
    """Scores candidates by P(target | do(intervention))."""

    def __init__(self, client: SupportsToolCall) -> None:
        self._client = client

    async def propose_next(self, case: Case, process: ProcessDefinition) -> list[ActionProposal]:
        """Score every allowed causal candidate and rank best-first."""

        if process.causal is None:
            return []

        config = CausalConfig.model_validate(process.causal)
        proposals: list[ActionProposal] = []
        for candidate in config.candidates:
            if not process.allows(candidate.action):
                logger.warning(
                    "Causal candidate proposes disallowed action %s; skipping.",
                    candidate.action,
                )
                continue
            posterior = await self.score_intervention(
                candidate.intervention, config.target, tool=config.query_tool
            )
            proposals.append(
                ActionProposal(
                    action_uri=candidate.action,
                    params=candidate.params,
                    confidence=posterior,
                    rationale=f"P(target | do({_short(candidate.intervention)})) ≈ {posterior:.2f}",
                    proposed_by="CausalSimulationEngine",
                )
            )
        proposals.sort(key=lambda proposal: proposal.confidence or 0.0, reverse=True)
        return proposals

    async def score_intervention(
        self,
        intervention: dict[str, Any],
        target: Any,
        *,
        tool: str = "do_query",
    ) -> float:
        """Direct one-shot interventional query — used by stacking/arbitration."""

        result = await self._client.call_tool(tool, {"intervention": intervention, "query": target})
        return extract_posterior(result)

    async def counterfactual_replay(
        self,
        *,
        case_uri: str,
        swap_activity_uri: str,
        evidence: dict[str, Any],
        counterfactual_action_uri: str,
        counterfactual_params: dict[str, Any],
        target: dict[str, Any],
    ) -> CounterfactualResult:
        """Ask "what if we had taken Y at this point instead?" via ontorag.

        Args:
            case_uri: The case being replayed.
            swap_activity_uri: The activity in the case's history being swapped.
            evidence: Observed facts up to the swap point (typically the
                ``state_before`` of the swapped activity).
            counterfactual_action_uri: The alternative action whose effect is hypothesised.
            counterfactual_params: Treated as the interventional assignment.
            target: The goal proposition whose counterfactual posterior is computed.
        """

        result = await self._client.call_tool(
            "counterfactual",
            {
                "evidence": evidence,
                "intervention": counterfactual_params,
                "query": target,
            },
        )
        posterior = extract_posterior(result)
        return CounterfactualResult(
            case_uri=case_uri,
            swapped_activity_uri=swap_activity_uri,
            counterfactual_action_uri=counterfactual_action_uri,
            counterfactual_params=counterfactual_params,
            target=target,
            posterior=posterior,
            rationale=(
                f"P(target | evidence, do({_short(counterfactual_params)})) ≈ {posterior:.2f}"
            ),
        )


class StackedEngine:
    """Composes a proposer engine with a causal validator.

    The proposer (e.g. LLM or Bayesian) emits candidate proposals; the validator
    re-scores each by its *interventional* posterior under the proposal's params
    — overwriting the proposer's confidence with the do-effect. The stack thus
    realises CLAUDE.md's "causal sim acts as final validator over BN/LLM
    proposals" — recommendations come with simulated interventional utility, not
    just observational correlation.
    """

    def __init__(
        self,
        *,
        proposer: DecisionEngine,
        validator: CausalSimulationEngine,
        target: dict[str, Any] | None = None,
    ) -> None:
        """Bind the stack.

        Args:
            proposer: Any engine; its proposals are the candidates to validate.
            validator: A causal engine whose ``score_intervention`` re-ranks them.
            target: Goal proposition; defaults to ``process.goal`` at call time.
        """

        self._proposer = proposer
        self._validator = validator
        self._target = target

    async def propose_next(self, case: Case, process: ProcessDefinition) -> list[ActionProposal]:
        proposals = await self._proposer.propose_next(case, process)
        if not proposals:
            return []

        target = self._target if self._target is not None else (process.goal or {})
        if not target:
            logger.warning(
                "StackedEngine has no causal target (process.goal is empty); "
                "returning proposer's proposals unchanged."
            )
            return proposals

        rescored: list[ActionProposal] = []
        for proposal in proposals:
            posterior = await self._validator.score_intervention(proposal.params, target)
            rescored.append(
                proposal.model_copy(
                    update={
                        "confidence": posterior,
                        "rationale": (
                            (proposal.rationale + " | " if proposal.rationale else "")
                            + f"causal: P(goal | do(...)) ≈ {posterior:.2f}"
                        ),
                        "proposed_by": f"{proposal.proposed_by or 'proposer'}+CausalValidator",
                    }
                )
            )
        rescored.sort(key=lambda proposal: proposal.confidence or 0.0, reverse=True)
        return rescored


def _short(payload: dict[str, Any]) -> str:
    """Compact one-line rendering of an intervention payload for rationales."""

    if not payload:
        return "{}"
    return ", ".join(f"{key}={value!r}" for key, value in sorted(payload.items()))
