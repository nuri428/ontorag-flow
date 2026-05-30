"""HumanReviewEngine — always defer to a human reviewer.

The simplest decision engine: it proposes a single :class:`RequestHumanReview`
action whose execution makes the case manager auto-suspend the case. Useful as a
deliberate handoff (process declares ``engine: human``) or as a stacked fallback
when another engine yields no proposals.
"""

from __future__ import annotations

from ontorag_flow.actions.human import RequestHumanReview
from ontorag_flow.core.action import ActionProposal
from ontorag_flow.core.case import Case
from ontorag_flow.core.process import ProcessDefinition

__all__ = ["HumanReviewEngine"]


class HumanReviewEngine:
    """Proposes a single 'request human review' action with full confidence."""

    async def propose_next(self, case: Case, process: ProcessDefinition) -> list[ActionProposal]:
        return [
            ActionProposal(
                action_uri=RequestHumanReview.uri,
                params={"reason": "Engine deferred to human judgment."},
                rationale="Hand off to a human for review.",
                confidence=1.0,
                proposed_by="HumanReviewEngine",
            )
        ]
