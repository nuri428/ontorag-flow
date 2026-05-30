"""Each engine's optional ``explain()`` returns a typed :class:`EngineExplanation`.

These tests pin down the *shape* of each engine's trace dict, not its
contents — engines are free to enrich their explanations over time, but
the inspector UI depends on `engine_kind`, `proposals`, and `trace` being
present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ontorag_flow.core.case import Case, CaseStatus
from ontorag_flow.core.process import ProcessDefinition
from ontorag_flow.core.state import CaseState
from ontorag_flow.engines.base import EngineExplanation
from ontorag_flow.engines.bayesian import BayesianMpeEngine
from ontorag_flow.engines.causal import CausalSimulationEngine, StackedEngine
from ontorag_flow.engines.human import HumanReviewEngine
from ontorag_flow.engines.llm_agent import LlmAgentEngine
from ontorag_flow.engines.rule import RuleEngine

ACT = "urn:a:1"
OTHER = "urn:a:2"


def _case(props: dict[str, Any] | None = None) -> Case:
    return Case(
        case_uri="urn:c:1",
        process_uri="urn:p:1",
        status=CaseStatus.OPEN,
        state=CaseState(properties=props or {}),
    )


# --- RuleEngine ----------------------------------------------------------


async def test_rule_engine_explain_classifies_each_rule() -> None:
    process = ProcessDefinition(
        process_uri="urn:p:1",
        name="P",
        allowed_actions=[ACT],
        rules=[
            {"name": "fires", "when": {"level": "unknown"}, "then": {"action": ACT}},
            {"name": "unmatched", "when": {"level": "critical"}, "then": {"action": ACT}},
            {"name": "disallowed", "when": {}, "then": {"action": "urn:not-allowed"}},
        ],
    )
    engine = RuleEngine.from_process(process)
    explanation = await engine.explain(_case({"level": "unknown"}), process)

    assert isinstance(explanation, EngineExplanation)
    assert explanation.engine_kind == "RuleEngine"
    assert len(explanation.proposals) == 1
    assert explanation.proposals[0].action_uri == ACT

    trace = explanation.trace
    assert trace["rules_evaluated"] == 3
    assert any(r["name"] == "fires" for r in trace["rules_fired"])
    assert "unmatched" in trace["rules_unmatched"]
    assert "disallowed" in trace["rules_skipped_disallowed"]


# --- HumanReviewEngine ---------------------------------------------------


async def test_human_engine_explain_is_unconditional() -> None:
    engine = HumanReviewEngine()
    process = ProcessDefinition(process_uri="urn:p:h", name="H", allowed_actions=[])
    explanation = await engine.explain(_case(), process)

    assert explanation.engine_kind == "HumanReviewEngine"
    assert explanation.trace["policy"].startswith("always defer")
    assert len(explanation.proposals) == 1


# --- BayesianMpeEngine ---------------------------------------------------


@dataclass
class _FakeBayesianClient:
    posteriors: dict[str, float]  # action -> posterior
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        # Identify the candidate by what action_uri was put in evidence.
        evidence = arguments["evidence"]
        action_key = evidence.get("_action")
        return {"posterior": self.posteriors.get(str(action_key), 0.5)}


async def test_bayesian_engine_explain_includes_posterior_breakdown() -> None:
    process = ProcessDefinition(
        process_uri="urn:p:b",
        name="B",
        allowed_actions=[ACT, OTHER],
        bayesian={
            "target": {"diagnosed": True},
            "candidates": [
                {"action": ACT, "evidence": {"_action": ACT}},
                {"action": OTHER, "evidence": {"_action": OTHER}},
            ],
        },
    )
    client = _FakeBayesianClient(posteriors={ACT: 0.9, OTHER: 0.2})
    engine = BayesianMpeEngine(client)
    explanation = await engine.explain(_case(), process)

    assert explanation.engine_kind == "BayesianMpeEngine"
    assert explanation.trace["target"] == {"diagnosed": True}
    breakdown = explanation.trace["posterior_by_action"]
    assert breakdown[ACT] == 0.9
    assert breakdown[OTHER] == 0.2
    # Best-first ordering preserved.
    assert explanation.proposals[0].action_uri == ACT


# --- CausalSimulationEngine ---------------------------------------------


@dataclass
class _FakeCausalClient:
    posteriors: dict[str, float]
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        intervention = arguments["intervention"]
        return {"posterior": self.posteriors.get(intervention.get("_act", ""), 0.5)}


async def test_causal_engine_explain_includes_interventions() -> None:
    process = ProcessDefinition(
        process_uri="urn:p:c",
        name="C",
        allowed_actions=[ACT, OTHER],
        causal={
            "target": {"diagnosed": True},
            "candidates": [
                {"action": ACT, "intervention": {"_act": ACT}},
                {"action": OTHER, "intervention": {"_act": OTHER}},
            ],
        },
    )
    client = _FakeCausalClient(posteriors={ACT: 0.7, OTHER: 0.3})
    engine = CausalSimulationEngine(client)
    explanation = await engine.explain(_case(), process)

    assert explanation.engine_kind == "CausalSimulationEngine"
    interventions = explanation.trace["interventions_by_action"]
    assert interventions[ACT] == {"_act": ACT}
    assert interventions[OTHER] == {"_act": OTHER}
    assert explanation.proposals[0].action_uri == ACT


# --- LlmAgentEngine ------------------------------------------------------


class _FakeLlm:
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.last_user: str | None = None
        self.last_system: str | None = None

    async def complete(self, *, system: str, user: str) -> str:
        self.last_system = system
        self.last_user = user
        return self._reply


async def test_llm_engine_explain_captures_prompt_and_raw_reply() -> None:
    process = ProcessDefinition(
        process_uri="urn:p:llm",
        name="L",
        allowed_actions=[ACT],
    )
    reply = '[{"action_uri": "urn:a:1", "confidence": 0.8, "rationale": "go"}]'
    engine = LlmAgentEngine(_FakeLlm(reply))
    explanation = await engine.explain(_case({"k": "v"}), process)

    assert explanation.engine_kind == "LlmAgentEngine"
    assert explanation.trace["raw_reply"] == reply
    assert "Allowed actions" in explanation.trace["user_prompt"]
    assert explanation.trace["parsed_count"] == 1
    assert explanation.proposals[0].action_uri == ACT


async def test_llm_engine_explain_with_no_allowed_actions() -> None:
    process = ProcessDefinition(
        process_uri="urn:p:empty",
        name="E",
        allowed_actions=[],
    )
    engine = LlmAgentEngine(_FakeLlm(""))
    explanation = await engine.explain(_case(), process)

    assert explanation.engine_kind == "LlmAgentEngine"
    assert explanation.proposals == []
    assert "reason" in explanation.trace


# --- StackedEngine -------------------------------------------------------


async def test_stacked_engine_explain_compares_proposer_and_validator() -> None:
    process = ProcessDefinition(
        process_uri="urn:p:s",
        name="S",
        allowed_actions=[ACT, OTHER],
        rules=[
            {"name": "r1", "when": {}, "then": {"action": ACT}, "confidence": 0.4},
            {"name": "r2", "when": {}, "then": {"action": OTHER}, "confidence": 0.4},
        ],
        goal={"diagnosed": True},
    )
    proposer = RuleEngine.from_process(process)

    @dataclass
    class _ConstantValidator:
        async def score_intervention(
            self, intervention: dict[str, Any], target: Any, *, tool: str = "do_query"
        ) -> float:
            # OTHER always wins over ACT.
            return 0.9 if intervention == {} or "other" in str(intervention).lower() else 0.1

    stacked = StackedEngine(proposer=proposer, validator=_ConstantValidator())  # type: ignore[arg-type]
    explanation = await stacked.explain(_case(), process)

    assert explanation.engine_kind == "StackedEngine"
    assert explanation.trace["proposer_kind"] == "RuleEngine"
    assert explanation.trace["validator_kind"] == "_ConstantValidator"
    assert "proposer_original" in explanation.trace
    assert "validator_rescored" in explanation.trace
    # Each proposer row carries the action's params as the intervention payload
    # — the same value the validator's score_intervention was called with, so
    # the inspector can show "same intervention, different probability mass".
    for entry in explanation.trace["proposer_original"]:
        assert "intervention" in entry
        assert isinstance(entry["intervention"], dict)


# --- CaseManager.explain_next default for engines without explain() -----


async def test_case_manager_explain_next_falls_back_for_plain_engine() -> None:
    """An engine that doesn't implement explain() still produces an explanation."""

    from ontorag_flow.core.case_manager import CaseManager
    from ontorag_flow.core.executor import ActionExecutor
    from ontorag_flow.core.registry import default_registry
    from ontorag_flow.stores.sqlite import SqliteStore

    class _PlainEngine:
        async def propose_next(self, case: Case, process: ProcessDefinition) -> list[Any]:
            return []

    async with SqliteStore(":memory:") as store:
        manager = CaseManager(
            case_store=store,
            process_store=store,
            executor=ActionExecutor(audit_store=store, agent="urn:test"),
            registry=default_registry(),
            engine_factory=lambda _process: _PlainEngine(),  # type: ignore[return-value]
        )
        process = ProcessDefinition(process_uri="urn:p:plain", name="P", allowed_actions=[])
        await manager.register_process(process)
        case = await manager.create_case("urn:p:plain")

        explanation = await manager.explain_next(case.case_uri)
        assert explanation.engine_kind == "_PlainEngine"
        assert "does not implement explain" in explanation.trace["note"]
