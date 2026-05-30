"""Self-contained medical-triage demo.

Loads the YAML process, creates a synthetic high-severity patient case, lets
the rule engine drive the case to closure, then prints the timeline and
exports the PROV-O audit trail to Turtle. Everything below v1.0 in one
~80-line script.

Run from anywhere::

    uv run python examples/medical_triage/run_demo.py
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ontorag_flow.core.case import CaseStatus
from ontorag_flow.core.case_manager import CaseManager
from ontorag_flow.core.executor import ActionExecutor
from ontorag_flow.core.process import load_process
from ontorag_flow.core.provenance import render
from ontorag_flow.core.registry import default_registry
from ontorag_flow.engines.selection import EngineResolver
from ontorag_flow.stores.sqlite import SqliteStore

HERE = Path(__file__).resolve().parent
console = Console()


async def run() -> None:
    logging.getLogger("ontorag_flow").setLevel(logging.WARNING)

    process = load_process(HERE / "process.yaml")
    console.rule(f"[bold]Process[/] {process.process_uri}")
    console.print(f"goal:    {process.goal}")
    console.print(f"actions: {len(process.allowed_actions)}, rules: {len(process.rules)}")

    with tempfile.TemporaryDirectory() as workdir:
        store = SqliteStore(str(Path(workdir) / "demo.db"))
        await store.connect()
        try:
            registry = default_registry()
            manager = CaseManager(
                case_store=store,
                process_store=store,
                executor=ActionExecutor(audit_store=store, agent="urn:demo:clinician"),
                registry=registry,
                engine_factory=EngineResolver(registry=registry).for_process,
            )
            await manager.register_process(process)

            # Synthetic high-severity patient
            patient = {"age": 42, "severity": 8}
            case = await manager.create_case(process.process_uri, initial_state=patient)
            console.print(f"\nopened [cyan]{case.case_uri}[/] with {patient}\n")

            console.rule("Decision loop")
            step = 0
            while case.status is CaseStatus.OPEN:
                step += 1
                proposals = await manager.propose_next(case.case_uri)
                if not proposals:
                    console.print("[yellow]engine yielded nothing — stopping.[/]")
                    break
                top = proposals[0]
                console.print(
                    f"[bold]#{step}[/] picks [magenta]{top.action_uri.rsplit(':', 1)[-1]}[/]"
                    f"  (conf {top.confidence:.2f}) — {top.rationale}"
                )
                case, _ = await manager.execute_action(case.case_uri, top.action_uri, top.params)
                console.print(f"   state: {case.state.properties}")

            console.rule("Result")
            console.print(f"status: [bold]{case.status.value}[/]")
            console.print(f"history: {len(case.history)} event(s)")

            activities = await store.list_by_case(case.case_uri)
            table = Table(title="Audit trail")
            table.add_column("#", justify="right")
            table.add_column("Action")
            table.add_column("Agent")
            table.add_column("Inputs")
            for index, activity in enumerate(activities, start=1):
                table.add_row(
                    str(index),
                    activity.action_uri.rsplit(":", 1)[-1],
                    activity.agent or "—",
                    str(activity.used) if activity.used else "—",
                )
            console.print(table)

            ttl_path = Path(workdir) / "audit.ttl"
            ttl_path.write_text(render(activities, "ttl"), encoding="utf-8")
            console.print(
                f"\nPROV-O Turtle export: {ttl_path.stat().st_size} bytes (first 4 lines):"
            )
            for line in ttl_path.read_text(encoding="utf-8").splitlines()[:4]:
                console.print(f"  {line}")
        finally:
            await store.close()


if __name__ == "__main__":
    asyncio.run(run())
