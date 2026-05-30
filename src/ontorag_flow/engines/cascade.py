"""CascadeEngine — try engines in order, take the first that returns proposals.

Where :class:`~ontorag_flow.engines.causal.StackedEngine` combines a proposer
*and* a validator on every call, the cascade picks the first engine in a
sequence that actually has something to say — useful for fallback chains:
"try the LLM; if it produces nothing, fall back to rules; if that also
yields nothing, escalate to a human".

Declared in YAML::

    engine: cascade
    arbitration:
      sequence: [llm, rule, human]

Engines beyond the first are not consulted unless the previous one returned
an empty list. The first non-empty result wins outright — its proposals are
the engine's proposals, untouched.
"""

from __future__ import annotations

from collections.abc import Sequence

from ontorag_flow.core.action import ActionProposal
from ontorag_flow.core.case import Case
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.engines.base import DecisionEngine, EngineExplanation

__all__ = ["CascadeEngine"]


def _is_sane(proposal: ActionProposal, process: ProcessDefinition) -> bool:
    """Reject a proposal that violates the basic sanity contract.

    Used by health_check=True cascades to drop garbage from a compromised
    proposer before it blocks fallback. The checks are deliberately cheap:

    - action_uri must be allowed by the process
    - confidence (if set) must be in [0, 1]
    - params must be a dict (None is treated as {} elsewhere; non-dict isn't)
    """

    if not process.allows(proposal.action_uri):
        return False
    if proposal.confidence is not None and not 0.0 <= proposal.confidence <= 1.0:
        return False
    # Pydantic typing says params is dict[str, Any], but a malicious plugin
    # could circumvent validation by assigning post-construction; the
    # isinstance guard is the runtime backstop.
    if not isinstance(proposal.params, dict):  # type: ignore[reportUnnecessaryIsInstance]
        return False
    return True


class CascadeEngine:
    """Walks a sequence of engines; first non-empty proposals list wins."""

    def __init__(
        self,
        engines: Sequence[tuple[str, DecisionEngine]],
        *,
        health_check: bool = False,
    ) -> None:
        """Bind the cascade.

        Args:
            engines: Ordered list of ``(kind, engine)`` tuples. ``kind`` is a
                human-readable label for the trace (e.g. ``"llm"``); ``engine``
                is the actual :class:`DecisionEngine` instance.
            health_check: When True, validate each engine's proposals against
                the process before accepting them (confidence in ``[0, 1]``,
                action in ``allowed_actions``, params is a dict). Invalid
                proposals are dropped *and* the engine is treated as if it
                returned nothing — the cascade falls through to the next.
                Defends against a compromised proposer that always emits
                garbage with confidence 1.0 just to block fallback.
        """

        if not engines:
            raise ValueError("CascadeEngine requires a non-empty engine sequence.")
        self._engines = list(engines)
        self._health_check = health_check

    async def propose_next(self, case: Case, process: ProcessDefinition) -> list[ActionProposal]:
        for _kind, engine in self._engines:
            proposals = await engine.propose_next(case, process)
            if self._health_check:
                proposals = [p for p in proposals if _is_sane(p, process)]
            if proposals:
                return proposals
        return []

    async def explain(self, case: Case, process: ProcessDefinition) -> EngineExplanation:  # noqa: D401
        """Trace records what each engine returned and which one was chosen.

        Short-circuits at the winner — engines after the chosen one are *not*
        invoked, because explain() must not change the cost profile of the
        recommendation. Post-winner entries are recorded as ``consulted: false``
        so the operator can see *which* engines were the fallback tail without
        triggering an LLM/Bayesian call for each just to count.
        """

        attempts: list[dict[str, object]] = []
        chosen: str | None = None
        winning_proposals: list[ActionProposal] = []
        for kind, engine in self._engines:
            if chosen is not None:
                attempts.append({"kind": kind, "consulted": False, "count": None})
                continue
            proposals = await engine.propose_next(case, process)
            raw_count = len(proposals)
            if self._health_check:
                proposals = [p for p in proposals if _is_sane(p, process)]
            entry: dict[str, object] = {
                "kind": kind,
                "consulted": True,
                "count": len(proposals),
            }
            if self._health_check and raw_count != len(proposals):
                entry["health_check_dropped"] = raw_count - len(proposals)
            attempts.append(entry)
            if proposals:
                chosen = kind
                winning_proposals = proposals
        return EngineExplanation(
            engine_kind="CascadeEngine",
            proposals=winning_proposals,
            trace={
                "sequence": [kind for kind, _ in self._engines],
                "attempts": attempts,
                "chosen": chosen,
            },
        )
