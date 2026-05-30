"""Supply-chain RCA demo — open-ended investigation with a human handoff.

Differences from ``examples/medical_triage/run_demo.py``:

* registers four **custom** domain actions (not just the built-in catalog);
* exercises CMMN-style ``constraints.requires`` so the manager refuses an
  out-of-order action even if a rule fires for it;
* hits a HUMAN-side-effect action and watches the case auto-suspend, then
  simulates the human review and resumes the case to closure.

Run from anywhere::

    uv run python examples/supply_chain_rca/run_demo.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.table import Table

HERE = Path(__file__).resolve().parent
# Make the local actions module importable when this file is run directly.
sys.path.insert(0, str(HERE))

from actions import DOMAIN_ACTIONS  # noqa: E402

from ontorag_flow.core.case import CaseStatus  # noqa: E402
from ontorag_flow.core.case_manager import CaseManager  # noqa: E402
from ontorag_flow.core.executor import ActionExecutor  # noqa: E402
from ontorag_flow.core.process import load_process  # noqa: E402
from ontorag_flow.core.provenance import render  # noqa: E402
from ontorag_flow.core.registry import default_registry  # noqa: E402
from ontorag_flow.engines.selection import EngineResolver  # noqa: E402
from ontorag_flow.stores.sqlite import SqliteStore  # noqa: E402

UPDATE_PROPERTY = "urn:ontorag-flow:action:UpdateCaseProperty"
console = Console()


async def run() -> None:
    logging.getLogger("ontorag_flow").setLevel(logging.WARNING)

    process = load_process(HERE / "process.yaml")
    console.rule(f"[bold]Process[/] {process.process_uri}")
    console.print(
        f"goal:     {process.goal}\n"
        f"actions:  {len(process.allowed_actions)} "
        f"(4 domain + UpdateCaseProperty for the wrap-up)\n"
        f"rules:    {len(process.rules)}, "
        f"requires: {process.constraints.get('requires', {})}"
    )

    with tempfile.TemporaryDirectory() as workdir:
        store = SqliteStore(str(Path(workdir) / "demo.db"))
        await store.connect()
        try:
            registry = default_registry()
            for action in DOMAIN_ACTIONS:
                registry.register(action)

            manager = CaseManager(
                case_store=store,
                process_store=store,
                executor=ActionExecutor(audit_store=store, agent="urn:demo:ops"),
                registry=registry,
                engine_factory=EngineResolver(registry=registry).for_process,
            )
            await manager.register_process(process)

            # Synthetic 2-hour delay incident
            incident = {"delay_minutes": 120}
            case = await manager.create_case(process.process_uri, initial_state=incident)
            console.print(f"\nopened [cyan]{case.case_uri}[/] with {incident}\n")

            console.rule("Investigation loop (RuleEngine)")
            case = await _drive_until_terminal(manager, case.case_uri)

            if case.status is CaseStatus.SUSPENDED:
                console.rule("[yellow]Human handoff[/]")
                console.print(
                    "Case auto-suspended after [magenta]ApproveCompensation[/] (HUMAN side effect)."
                )
                console.print(
                    f"   compensation_reason: {case.state.properties.get('compensation_reason')}"
                )
                console.print("   ...simulating the reviewer signing off...")
                case = await manager.resume(case.case_uri)

                # The reviewer's wrap-up: mark RCA complete to satisfy the goal.
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

            ttl_path = Path(workdir) / "audit.ttl"
            ttl_path.write_text(
                render(await store.list_by_case(case.case_uri), "ttl"), encoding="utf-8"
            )
            console.print(f"\nPROV-O Turtle export: {ttl_path.stat().st_size} bytes.")
        finally:
            await store.close()


async def _drive_until_terminal(manager: CaseManager, case_uri: str):  # type: ignore[no-untyped-def]
    """Run propose/execute until the case leaves OPEN (closed or suspended)."""

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
        console.print(
            f"[bold]#{step}[/] picks [magenta]{short}[/]  (conf {top.confidence:.2f}) — {top.rationale}"
        )
        case, _ = await manager.execute_action(case_uri, top.action_uri, top.params)
        console.print(f"   state: {case.state.properties}")
    return case


def _print_history(activities) -> None:  # type: ignore[no-untyped-def]
    table = Table(title="Audit trail")
    table.add_column("#", justify="right")
    table.add_column("Action")
    table.add_column("Agent")
    table.add_column("Side effects (inferred from action URI)")
    for index, activity in enumerate(activities, start=1):
        short = activity.action_uri.rsplit(":", 1)[-1]
        table.add_row(str(index), short, activity.agent or "—", "—")
    console.print(table)


if __name__ == "__main__":
    asyncio.run(run())
