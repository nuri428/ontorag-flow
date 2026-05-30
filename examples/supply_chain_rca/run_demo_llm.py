"""Supply-chain RCA driven by ``LlmAgentEngine`` instead of the rule engine.

The same process definition, the same custom actions, the same constraints —
only the engine changes. Demonstrates that ``process.yaml`` is data and the
engine is policy.

Two modes:

* **live** — when ``LLM_PROVIDER`` is set (``anthropic`` / ``openai`` /
  ``ollama``), the real SDK is called; the LLM reads the allowed-action
  catalog and proposes the next step.
* **fake** — default. A small :class:`FakeReasoningLlm` parses the prompt
  for current case state and returns deterministic LLM-ish proposals.
  Lets CI run this demo on every PR without an API key, and lets the
  reader see the framework's wiring (prompt → JSON → ranked proposals)
  without paying for tokens.

Run::

    # fake mode (deterministic, no API key)
    uv run python examples/supply_chain_rca/run_demo_llm.py

    # live mode
    LLM_PROVIDER=anthropic uv run python examples/supply_chain_rca/run_demo_llm.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.table import Table

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from actions import DOMAIN_ACTIONS  # noqa: E402

from ontorag_flow.core.case import CaseStatus  # noqa: E402
from ontorag_flow.core.case_manager import CaseManager  # noqa: E402
from ontorag_flow.core.executor import ActionExecutor  # noqa: E402
from ontorag_flow.core.process import load_process  # noqa: E402
from ontorag_flow.core.registry import default_registry  # noqa: E402
from ontorag_flow.engines.llm_agent import LlmClient  # noqa: E402
from ontorag_flow.engines.selection import EngineResolver  # noqa: E402
from ontorag_flow.stores.sqlite import SqliteStore  # noqa: E402

UPDATE_PROPERTY = "urn:ontorag-flow:action:UpdateCaseProperty"
console = Console()


class FakeReasoningLlm:
    """Deterministic LLM stand-in for the demo's no-API-key path.

    Parses ``LlmAgentEngine``'s prompt to find current case state, then
    returns LLM-ish proposals (richer rationale text than the rule engine's
    declarative one-liners) for the next investigation step.
    """

    async def complete(self, *, system: str, user: str) -> str:
        properties = self._extract_properties(user)
        proposals = self._pick(properties)
        return json.dumps(proposals)

    @staticmethod
    def _extract_properties(prompt: str) -> dict[str, object]:
        marker = "Current case properties: "
        for line in prompt.splitlines():
            if line.startswith(marker):
                try:
                    return json.loads(line[len(marker) :])
                except json.JSONDecodeError:
                    return {}
        return {}

    @staticmethod
    def _pick(properties: dict[str, object]) -> list[dict[str, object]]:
        delay = properties.get("delay_minutes", 0)
        evidence_count = properties.get("evidence_count", 0)
        supplier_status = properties.get("supplier_status", "unknown")
        routing = properties.get("routing", "primary")

        if evidence_count == 0:
            return [
                {
                    "action_uri": "urn:demo:supply-chain:RecordEvidence",
                    "params": {
                        "note": f"Shipment is overdue by {delay} minutes; opening RCA dossier."
                    },
                    "rationale": (
                        "Standard RCA practice: capture the observed deviation before "
                        "forming hypotheses. With no evidence on file yet, this is the "
                        "first step regardless of downstream branches."
                    ),
                    "confidence": 0.92,
                }
            ]
        if supplier_status == "unknown":
            return [
                {
                    "action_uri": "urn:demo:supply-chain:QuerySupplier",
                    "params": {"supplier_id": "SUP-42"},
                    "rationale": (
                        "We have one piece of evidence on file; the primary supplier is "
                        "the most likely upstream cause and the cheapest hypothesis to test "
                        "first — probe their status endpoint."
                    ),
                    "confidence": 0.88,
                }
            ]
        if supplier_status == "non_responsive" and routing != "backup":
            return [
                {
                    "action_uri": "urn:demo:supply-chain:RouteThroughBackup",
                    "params": {"backup_id": "ROUTE-B"},
                    "rationale": (
                        "Supplier did not respond; continuing to wait would extend customer "
                        "impact. The contracted backup carrier is the documented fallback — "
                        "switch the shipment now."
                    ),
                    "confidence": 0.94,
                }
            ]
        if routing == "backup":
            return [
                {
                    "action_uri": "urn:demo:supply-chain:ApproveCompensation",
                    "params": {
                        "reason": (
                            "Backup routing was invoked; per policy this triggers a "
                            "customer-compensation review."
                        )
                    },
                    "rationale": (
                        "Company policy makes compensation a human decision once we've "
                        "engaged the backup route. Yielding to a reviewer here."
                    ),
                    "confidence": 0.97,
                }
            ]
        return []


def build_llm_client() -> tuple[LlmClient, str]:
    """Return the LLM client + the mode label to show the user."""

    provider = os.getenv("LLM_PROVIDER")
    if provider:
        from ontorag_flow.engines.llm_providers import make_llm_client

        client = make_llm_client(provider, os.getenv("LLM_MODEL"))
        return client, f"LIVE ({provider})"
    return FakeReasoningLlm(), "FAKE (set LLM_PROVIDER to switch to a real model)"


async def run() -> None:
    logging.getLogger("ontorag_flow").setLevel(logging.WARNING)

    llm_client, mode = build_llm_client()
    style = "green" if mode.startswith("LIVE") else "yellow"
    console.rule(f"[bold {style}]LlmAgentEngine[/] — {mode}")

    process = load_process(HERE / "process.yaml").model_copy(update={"engine": "llm"})
    console.print(f"process: {process.process_uri}  (engine override → llm)")
    console.print(f"goal:    {process.goal}")

    with tempfile.TemporaryDirectory() as workdir:
        store = SqliteStore(str(Path(workdir) / "demo.db"))
        await store.connect()
        try:
            registry = default_registry()
            for action in DOMAIN_ACTIONS:
                registry.register(action)

            resolver = EngineResolver(registry=registry, llm_client=llm_client)
            manager = CaseManager(
                case_store=store,
                process_store=store,
                executor=ActionExecutor(audit_store=store, agent="urn:demo:ops-llm"),
                registry=registry,
                engine_factory=resolver.for_process,
            )
            await manager.register_process(process)

            incident = {"delay_minutes": 120}
            case = await manager.create_case(process.process_uri, initial_state=incident)
            console.print(f"\nopened [cyan]{case.case_uri}[/] with {incident}\n")

            console.rule("Investigation loop (LlmAgentEngine)")
            case = await _drive_until_terminal(manager, case.case_uri)

            if case.status is CaseStatus.SUSPENDED:
                console.rule("[yellow]Human handoff[/]")
                console.print(
                    "Case auto-suspended after the LLM picked "
                    "[magenta]ApproveCompensation[/] (HUMAN side effect)."
                )
                console.print(
                    f"   compensation_reason: {case.state.properties.get('compensation_reason')}"
                )
                console.print("   ...simulating the reviewer signing off...")
                case = await manager.resume(case.case_uri)

                console.rule("Wrap-up after human sign-off")
                case, _ = await manager.execute_action(
                    case.case_uri,
                    UPDATE_PROPERTY,
                    {"key": "rca_complete", "value": True},
                )

            console.rule("Result")
            console.print(f"status:  [bold]{case.status.value}[/]")
            console.print(f"history: {len(case.history)} event(s)")
            _print_history(await store.list_by_case(case.case_uri))
        finally:
            await store.close()


async def _drive_until_terminal(manager: CaseManager, case_uri: str):  # type: ignore[no-untyped-def]
    """Run propose/execute until the case leaves OPEN."""

    step = 0
    case = await manager.get_case(case_uri)
    assert case is not None
    while case.status is CaseStatus.OPEN:
        step += 1
        proposals = await manager.propose_next(case_uri)
        if not proposals:
            console.print("[yellow]engine yielded nothing — stopping.[/]")
            break
        top = proposals[0]
        short = top.action_uri.rsplit(":", 1)[-1]
        console.print(f"[bold]#{step}[/] picks [magenta]{short}[/]  (conf {top.confidence:.2f})")
        console.print(f"   rationale: [italic]{top.rationale}[/]")
        case, _ = await manager.execute_action(case_uri, top.action_uri, top.params)
        console.print(f"   state: {case.state.properties}")
    return case


def _print_history(activities) -> None:  # type: ignore[no-untyped-def]
    table = Table(title="Audit trail")
    table.add_column("#", justify="right")
    table.add_column("Action")
    table.add_column("Proposed by", style="cyan")
    for index, activity in enumerate(activities, start=1):
        short = activity.action_uri.rsplit(":", 1)[-1]
        table.add_row(
            str(index), short, "LlmAgentEngine" if "Update" not in short else "(manual wrap-up)"
        )
    console.print(table)


if __name__ == "__main__":
    asyncio.run(run())
