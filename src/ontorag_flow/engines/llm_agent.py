"""LlmAgentEngine — an LLM chooses the next action by reasoning.

Where :class:`~ontorag_flow.engines.rule.RuleEngine` fires declarative rows and
:class:`~ontorag_flow.engines.bayesian.BayesianMpeEngine` scores by posterior,
this engine hands the case state, goal, and allowed-action catalog to a language
model and asks it to propose the next action(s) as structured JSON. Like every
engine it only *proposes*; it never executes.

The LLM is reached through a narrow :class:`LlmClient` Protocol, so the engine is
testable with a fake and provider-agnostic — concrete Anthropic/OpenAI/Ollama
adapters live in :mod:`ontorag_flow.engines.llm_providers`. No LangChain/-Index;
direct SDK calls only (matching ontorag's posture).
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from ontorag_flow.core.action import ActionProposal
from ontorag_flow.core.case import Case
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.registry import ActionRegistry
from ontorag_flow.log import get_logger

logger = get_logger(__name__)

__all__ = ["LlmAgentEngine", "LlmClient"]

_SYSTEM_PROMPT = (
    "You are a decision engine for an ontology-grounded case-management system. "
    "Given a case's current state, its goal, and the catalog of actions allowed "
    "by its process, choose the next action(s) that best advance the case toward "
    "its goal. You only RECOMMEND — you never execute. Respond with ONLY a JSON "
    "array (no prose, no code fences) of objects with keys: action_uri (string, "
    "must be one of the allowed actions), params (object), rationale (string), "
    "confidence (number between 0 and 1). Order best-first."
)


class LlmClient(Protocol):
    """Minimal structural contract for a chat-completion backend.

    Concrete adapters (Anthropic/OpenAI/Ollama) satisfy this; tests pass a fake.
    """

    async def complete(self, *, system: str, user: str) -> str: ...


class LlmAgentEngine:
    """Proposes next actions by prompting an LLM and parsing its JSON reply."""

    def __init__(
        self,
        client: LlmClient,
        *,
        registry: ActionRegistry | None = None,
        max_proposals: int = 3,
    ) -> None:
        """Bind the engine to an LLM client.

        Args:
            client: Anything satisfying :class:`LlmClient`.
            registry: Optional action registry; when given, the prompt is
                enriched with each allowed action's description and input schema.
            max_proposals: Cap on the number of proposals returned.
        """

        self._client = client
        self._registry = registry
        self._max_proposals = max_proposals

    async def propose_next(self, case: Case, process: ProcessDefinition) -> list[ActionProposal]:
        """Ask the LLM for ranked next-action proposals.

        Args:
            case: The case whose state and goal frame the decision.
            process: The governing process; supplies the allowed-action set.

        Returns:
            Proposals parsed from the LLM reply, filtered to allowed actions and
            ranked by confidence (best first). Empty if there are no allowed
            actions or the reply cannot be parsed.
        """

        if not process.allowed_actions:
            return []

        user_prompt = self._build_user_prompt(case, process)
        raw = await self._client.complete(system=_SYSTEM_PROMPT, user=user_prompt)
        proposals = self._parse(raw, process)
        return proposals[: self._max_proposals]

    def _build_user_prompt(self, case: Case, process: ProcessDefinition) -> str:
        """Render the case, goal, and allowed-action catalog as a prompt."""

        state_json = json.dumps(case.state.properties, default=str, sort_keys=True)
        goal_json = json.dumps(case.state.goal, default=str, sort_keys=True)

        lines = [
            f"Process: {process.name} ({process.process_uri})",
            f"Current case properties: {state_json}",
            f"Goal (close the case when satisfied): {goal_json}",
            "",
            "Allowed actions:",
        ]
        for uri in process.allowed_actions:
            lines.append(self._describe_action(uri))
        lines.append("")
        lines.append("Return the JSON array of proposals now.")
        return "\n".join(lines)

    def _describe_action(self, uri: str) -> str:
        """One catalog line for an action, enriched from the registry if present."""

        action = self._registry.get(uri) if self._registry is not None else None
        if action is None:
            return f"- {uri}"
        schema = action.input_schema.model_json_schema()
        params = sorted(schema.get("properties", {}).keys())
        required = schema.get("required", [])
        return (
            f"- {uri}: {action.description or action.name} (params: {params}; required: {required})"
        )

    def _parse(self, raw: str, process: ProcessDefinition) -> list[ActionProposal]:
        """Parse the LLM reply into ranked, allowed proposals (tolerant)."""

        entries = _extract_json_array(raw)
        if entries is None:
            logger.warning("LLM reply was not parseable JSON; returning no proposals.")
            return []

        proposals: list[ActionProposal] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            action_uri = entry.get("action_uri")
            if not isinstance(action_uri, str) or not process.allows(action_uri):
                continue
            confidence = _clamp_confidence(entry.get("confidence"))
            params = entry.get("params")
            rationale = entry.get("rationale")
            proposals.append(
                ActionProposal(
                    action_uri=action_uri,
                    params=params if isinstance(params, dict) else {},
                    rationale=rationale if isinstance(rationale, str) else None,
                    confidence=confidence,
                    proposed_by="LlmAgentEngine",
                )
            )

        proposals.sort(key=lambda proposal: proposal.confidence or 0.0, reverse=True)
        return proposals


def _clamp_confidence(value: Any) -> float | None:
    """Coerce a confidence to a float in ``[0, 1]``, or None if absent/invalid."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(1.0, float(value)))


def _extract_json_array(raw: str) -> list[Any] | None:
    """Pull a JSON array out of a possibly fenced / prose-wrapped LLM reply.

    Accepts a bare array, a ```json fenced block, or an object with a
    ``"proposals"`` list. Returns None if no array can be recovered.
    """

    text = raw.strip()
    if "```" in text:
        # Take the content of the first fenced block.
        fence = text.split("```", 2)
        if len(fence) >= 2:
            body = fence[1]
            if body.startswith("json"):
                body = body[len("json") :]
            text = body.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("proposals"), list):
        return parsed["proposals"]
    return None
