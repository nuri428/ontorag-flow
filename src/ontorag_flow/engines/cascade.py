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


class CascadeEngine:
    """Walks a sequence of engines; first non-empty proposals list wins."""

    def __init__(self, engines: Sequence[tuple[str, DecisionEngine]]) -> None:
        """Bind the cascade.

        Args:
            engines: Ordered list of ``(kind, engine)`` tuples. ``kind`` is a
                human-readable label for the trace (e.g. ``"llm"``); ``engine``
                is the actual :class:`DecisionEngine` instance.
        """

        if not engines:
            raise ValueError("CascadeEngine requires a non-empty engine sequence.")
        self._engines = list(engines)

    async def propose_next(self, case: Case, process: ProcessDefinition) -> list[ActionProposal]:
        for _kind, engine in self._engines:
            proposals = await engine.propose_next(case, process)
            if proposals:
                return proposals
        return []

    async def explain(self, case: Case, process: ProcessDefinition) -> EngineExplanation:
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
            attempts.append({"kind": kind, "consulted": True, "count": len(proposals)})
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
