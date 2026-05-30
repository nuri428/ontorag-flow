"""Command-line interface (Typer + Rich).

v0.1 scope: project ``init``, the ``action`` sub-app (list / register / run a
single action — no cases yet), an ontorag connectivity ``status`` check, and
``serve`` for the API. v0.2 adds the ``process`` and ``case`` sub-apps.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from ontorag_flow import __version__
from ontorag_flow.config import get_settings
from ontorag_flow.core.action import Action, BaseAction
from ontorag_flow.core.case_manager import CaseManager, CaseManagerError
from ontorag_flow.core.executor import ActionExecutor, ActionValidationError
from ontorag_flow.core.process import ProcessParseError, load_process
from ontorag_flow.core.process_rdf import load_process_rdf
from ontorag_flow.core.provenance import ExportFormat, render
from ontorag_flow.core.registry import ActionRegistry, default_registry
from ontorag_flow.core.state import EMPTY_STATE
from ontorag_flow.engines.selection import EngineResolver, EngineUnavailableError
from ontorag_flow.engines.wiring import build_llm_client, maybe_connect_ontorag
from ontorag_flow.log import configure_logging
from ontorag_flow.stores.sqlite import SqliteStore

app = typer.Typer(
    name="ontorag-flow",
    help="Ontology-grounded adaptive case management — the Kinetic layer over ontorag.",
    no_args_is_help=True,
    add_completion=False,
)
action_app = typer.Typer(help="Inspect, register, and run actions.", no_args_is_help=True)
app.add_typer(action_app, name="action")

process_app = typer.Typer(help="Load and inspect process definitions.", no_args_is_help=True)
app.add_typer(process_app, name="process")

case_app = typer.Typer(help="Create, inspect, and advance cases.", no_args_is_help=True)
app.add_typer(case_app, name="case")

audit_app = typer.Typer(help="Inspect and export the PROV-O audit trail.", no_args_is_help=True)
app.add_typer(audit_app, name="audit")

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"ontorag-flow {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    _version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    configure_logging(get_settings().log_level)


@app.command()
def init() -> None:
    """Create a local ``.env`` from ``.env.example`` if one does not exist."""

    target = Path(".env")
    example = Path(".env.example")
    if target.exists():
        console.print("[yellow].env already exists — leaving it untouched.[/]")
        raise typer.Exit()
    if not example.exists():
        console.print("[red].env.example not found in the current directory.[/]")
        raise typer.Exit(code=1)
    shutil.copyfile(example, target)
    console.print(
        "[green]Created .env from .env.example.[/] Edit it to point at your ontorag MCP server."
    )


@action_app.command("list")
def action_list() -> None:
    """List the built-in registered actions and their declared side effects."""

    _print_actions(default_registry())


@action_app.command("register")
def action_register(
    path: Path = typer.Argument(..., help="Python file defining BaseAction subclasses."),
) -> None:
    """Load a plugin action file and report the actions it defines.

    v0.1 has no persistent registry across processes; this validates the plugin
    and lists what it would contribute.
    """

    if not path.exists():
        console.print(f"[red]No such file:[/] {path}")
        raise typer.Exit(code=1)
    registry = default_registry()
    discovered = _load_actions_from_file(path, registry)
    if not discovered:
        console.print(f"[yellow]No BaseAction subclasses found in {path}.[/]")
        raise typer.Exit(code=1)
    console.print(f"[green]Discovered {len(discovered)} action(s):[/]")
    _print_actions(registry, only=discovered)


@action_app.command("run")
def action_run(
    action_uri: str = typer.Argument(..., help="URI of the action to run."),
    param: list[str] = typer.Option(
        [],
        "--param",
        "-p",
        help="Action parameter as key=value (value parsed as JSON, else string).",
    ),
) -> None:
    """Validate and execute a single action against an empty case state."""

    registry = default_registry()
    action = registry.get(action_uri)
    if action is None:
        console.print(f"[red]Unknown action:[/] {action_uri}")
        _print_actions(registry)
        raise typer.Exit(code=1)

    params = _parse_params(param)
    try:
        # BaseAction is what every concrete action subclasses; the executor's
        # Action Protocol is structurally satisfied but pyright sees the
        # narrower Params types as a Liskov violation. Suppressed at this
        # boundary (and at the case_manager boundary).
        outcome = asyncio.run(_run_action(action, params))  # pyright: ignore[reportArgumentType]
    except ActionValidationError as exc:
        console.print(f"[red]Validation failed:[/] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[bold]success:[/] {outcome.result.success}")
    console.print(f"[bold]outputs:[/] {json.dumps(outcome.result.outputs, default=str)}")
    console.print(f"[bold]new state:[/] {json.dumps(outcome.state.model_dump(), default=str)}")
    console.print(f"[bold]activity:[/] {outcome.activity.activity_uri}")
    if outcome.result.error:
        console.print(f"[red]error:[/] {outcome.result.error}")


@app.command()
def status() -> None:
    """Show config and probe the ontorag MCP connection (find_entities smoke)."""

    settings = get_settings()
    console.print(f"[bold]ontorag MCP URL:[/] {settings.ontorag_mcp_url}")
    console.print(f"[bold]agent:[/] {settings.agent_id}")
    console.print(f"[bold]registered actions:[/] {len(default_registry())}")

    reachable, detail = asyncio.run(_probe_ontorag(settings.ontorag_mcp_url))
    if reachable:
        console.print(f"[green]ontorag MCP: reachable[/] ({detail})")
    else:
        console.print(f"[red]ontorag MCP: unreachable[/] — {detail}")


@app.command()
def serve(
    host: str | None = typer.Option(None, help="Bind host (defaults to API_HOST)."),
    port: int | None = typer.Option(None, help="Bind port (defaults to API_PORT)."),
) -> None:
    """Run the FastAPI + MCP server with uvicorn."""

    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "ontorag_flow.api.main:create_app",
        factory=True,
        host=host or settings.api_host,
        port=port or settings.api_port,
    )


# --- process commands ------------------------------------------------------


@process_app.command("load")
def process_load(
    path: Path = typer.Argument(..., help="Path to a process definition YAML file."),
) -> None:
    """Load a process definition from YAML or RDF (.ttl/.rdf/.n3/.jsonld/.nt) and persist it."""

    rdf_suffixes = {".ttl", ".rdf", ".n3", ".xml", ".jsonld", ".json-ld", ".nt"}
    loader = load_process_rdf if path.suffix.lower() in rdf_suffixes else load_process
    try:
        process = loader(path)
    except ProcessParseError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc

    asyncio.run(_with_manager(lambda m: m.register_process(process)))
    console.print(
        f"[green]Loaded process[/] {process.process_uri} "
        f"({len(process.allowed_actions)} allowed action(s))."
    )


@process_app.command("simulate")
def process_simulate(
    path: Path = typer.Argument(..., help="Path to a process definition (YAML or RDF)."),
    state: list[str] = typer.Option(
        [], "--state", "-s", help="Initial state KEY=VALUE; values are JSON-decoded if possible."
    ),
    execute_top: bool = typer.Option(
        False,
        "--execute-top/--no-execute",
        help="Execute the top proposal and print the resulting case state.",
    ),
    explain: bool = typer.Option(
        False,
        "--explain/--no-explain",
        help="Also print the engine's reasoning trace.",
    ),
) -> None:
    """Dry-run a process: build an in-memory case, ask the engine, optionally execute.

    Nothing is persisted — the case URI is synthetic, the SQLite store is
    an in-memory copy, and exit returns the disk to its original state.
    Use this while authoring a process YAML to verify the engine picks
    what you expect for a given case state, without polluting the dev DB.
    """

    rdf_suffixes = {".ttl", ".rdf", ".n3", ".xml", ".jsonld", ".json-ld", ".nt"}
    loader = load_process_rdf if path.suffix.lower() in rdf_suffixes else load_process
    try:
        process = loader(path)
    except ProcessParseError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc

    initial = _parse_params(state)

    async def _run() -> None:
        from ontorag_flow.stores.sqlite import SqliteStore as _Store

        async with _Store(":memory:") as store:
            settings = get_settings()
            registry = default_registry()
            ontorag_client = await maybe_connect_ontorag(
                settings, on_error=lambda message: console.print(f"[yellow]{message}[/]")
            )
            try:
                resolver = EngineResolver(
                    registry=registry,
                    ontorag_client=ontorag_client,
                    llm_client=build_llm_client(settings),
                )
                executor = ActionExecutor(audit_store=store, agent="urn:ontorag-flow:simulate")
                manager = CaseManager(
                    case_store=store,
                    process_store=store,
                    executor=executor,
                    registry=registry,
                    engine_factory=resolver.for_process,
                )
                await manager.register_process(process)
                case = await manager.create_case(process.process_uri, initial_state=initial)
                console.print(
                    f"[cyan]Simulated case[/] {case.case_uri} on process "
                    f"[bold]{process.name}[/] (in-memory; not persisted)."
                )
                console.print(f"State: {json.dumps(case.state.properties, default=str)}")

                proposals = await manager.propose_next(case.case_uri)
                if not proposals:
                    console.print("[yellow]Engine returned no proposals.[/]")
                else:
                    table = Table(title="Proposals (best-first)")
                    table.add_column("Action", style="cyan")
                    table.add_column("Conf", justify="right")
                    table.add_column("Params", style="dim")
                    table.add_column("Rationale")
                    for proposal in proposals:
                        table.add_row(
                            proposal.action_uri,
                            f"{proposal.confidence:.2f}"
                            if proposal.confidence is not None
                            else "—",
                            json.dumps(proposal.params, default=str),
                            proposal.rationale or "—",
                        )
                    console.print(table)

                if explain:
                    explanation = await manager.explain_next(case.case_uri)
                    console.print(f"[dim]Engine[/]: [bold]{explanation.engine_kind}[/]")
                    console.print("[dim]Trace[/]:")
                    console.print_json(json.dumps(explanation.trace, default=str))

                if execute_top and proposals:
                    top = proposals[0]
                    updated, _ = await manager.execute_action(
                        case.case_uri, top.action_uri, top.params
                    )
                    console.print(
                        f"[green]Executed[/] {top.action_uri} → state "
                        f"{json.dumps(updated.state.properties, default=str)} "
                        f"(status={updated.status.value})"
                    )
            finally:
                if ontorag_client is not None:
                    await ontorag_client.aclose()

    asyncio.run(_run())


@process_app.command("list")
def process_list() -> None:
    """List persisted process definitions."""

    processes = asyncio.run(_with_manager(lambda m: m.list_processes()))
    if not processes:
        console.print("[yellow]No processes loaded.[/]")
        return
    table = Table(title="Processes")
    table.add_column("URI", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Allowed", justify="right")
    table.add_column("Goal", style="magenta")
    for process in processes:
        table.add_row(
            process.process_uri,
            process.name,
            str(len(process.allowed_actions)),
            json.dumps(process.goal, default=str) if process.goal else "—",
        )
    console.print(table)


# --- case commands ---------------------------------------------------------


@case_app.command("create")
def case_create(
    process_uri: str = typer.Argument(..., help="Process URI governing the case."),
    initial_state: list[str] = typer.Option(
        [],
        "--initial-state",
        "-s",
        help="Seed property as key=value (JSON or string).",
    ),
) -> None:
    """Create a new case from a process definition."""

    state = _parse_params(initial_state)
    try:
        case = asyncio.run(_with_manager(lambda m: m.create_case(process_uri, initial_state=state)))
    except CaseManagerError as exc:
        console.print(f"[red]{type(exc).__name__}:[/] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Created case[/] {case.case_uri}")


@case_app.command("status")
def case_status(
    case_uri: str = typer.Argument(..., help="Case URI."),
) -> None:
    """Show a case's status, state, and history."""

    case = asyncio.run(_with_manager(lambda m: m.get_case(case_uri)))
    if case is None:
        console.print(f"[red]No such case:[/] {case_uri}")
        raise typer.Exit(code=1)
    console.print(f"[bold]case:[/] {case.case_uri}")
    console.print(f"[bold]process:[/] {case.process_uri}")
    console.print(f"[bold]status:[/] {case.status.value}")
    console.print(f"[bold]properties:[/] {json.dumps(case.state.properties, default=str)}")
    console.print(f"[bold]goal:[/] {json.dumps(case.state.goal, default=str)}")
    console.print(f"[bold]history:[/] {len(case.history)} event(s)")
    for event in case.history:
        mark = "[green]ok[/]" if event.success else "[red]fail[/]"
        console.print(f"  - {event.action_uri} ({mark})")


@case_app.command("propose-next")
def case_propose_next(
    case_uri: str = typer.Argument(..., help="Case URI."),
) -> None:
    """Show the decision engine's ranked next-action proposals (no execution)."""

    try:
        proposals = asyncio.run(_with_manager(lambda m: m.propose_next(case_uri)))
    except (CaseManagerError, EngineUnavailableError) as exc:
        console.print(f"[red]{type(exc).__name__}:[/] {exc}")
        raise typer.Exit(code=1) from exc

    if not proposals:
        console.print("[yellow]No action proposed for the current state.[/]")
        return
    table = Table(title="Proposals (best first)")
    table.add_column("Action", style="cyan", no_wrap=True)
    table.add_column("Conf.", justify="right")
    table.add_column("Params", style="magenta")
    table.add_column("Why")
    for proposal in proposals:
        table.add_row(
            proposal.action_uri,
            f"{proposal.confidence:.2f}" if proposal.confidence is not None else "—",
            json.dumps(proposal.params, default=str) if proposal.params else "—",
            proposal.rationale or "—",
        )
    console.print(table)


@case_app.command("counterfactual")
def case_counterfactual(
    case_uri: str = typer.Argument(..., help="Case URI."),
    swap_activity_uri: str = typer.Option(..., "--swap", help="Activity URI to swap in history."),
    action_uri: str = typer.Option(..., "--action", help="Alternative action URI."),
    param: list[str] = typer.Option(
        [],
        "--param",
        "-p",
        help="Counterfactual action parameter as key=value (JSON or string).",
    ),
) -> None:
    """Ask 'what if we had taken <action> at <swap> instead?' (requires causal engine)."""

    params = _parse_params(param)
    try:
        result = asyncio.run(
            _with_manager(
                lambda m: m.counterfactual(
                    case_uri,
                    swap_activity_uri=swap_activity_uri,
                    action_uri=action_uri,
                    params=params,
                )
            )
        )
    except (CaseManagerError, EngineUnavailableError) as exc:
        console.print(f"[red]{type(exc).__name__}:[/] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[bold]posterior:[/] {result.posterior:.3f}")
    console.print(f"[bold]rationale:[/] {result.rationale}")


@case_app.command("compensate")
def case_compensate(
    case_uri: str = typer.Argument(..., help="Case URI."),
    target: str | None = typer.Option(
        None,
        "--target",
        help="Activity URI to compensate from (inclusive). Default: undo all.",
    ),
) -> None:
    """Undo a tail of executed actions on a case (saga compensation)."""

    try:
        case = asyncio.run(
            _with_manager(lambda m: m.compensate(case_uri, target_activity_uri=target))
        )
    except CaseManagerError as exc:
        console.print(f"[red]{type(exc).__name__}:[/] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Compensated.[/] status: {case.status.value}, history: {len(case.history)} event(s)"
    )


@case_app.command("suspend")
def case_suspend(case_uri: str = typer.Argument(..., help="Case URI.")) -> None:
    """Pause an open case."""

    try:
        case = asyncio.run(_with_manager(lambda m: m.suspend(case_uri)))
    except CaseManagerError as exc:
        console.print(f"[red]{type(exc).__name__}:[/] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[yellow]Suspended.[/] {case.case_uri}")


@case_app.command("resume")
def case_resume(case_uri: str = typer.Argument(..., help="Case URI.")) -> None:
    """Reopen a suspended case."""

    try:
        case = asyncio.run(_with_manager(lambda m: m.resume(case_uri)))
    except CaseManagerError as exc:
        console.print(f"[red]{type(exc).__name__}:[/] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Resumed.[/] {case.case_uri}")


@case_app.command("tick")
def case_tick() -> None:
    """Fire elapsed timer events across all open cases.

    Schedule this from cron / a Kubernetes CronJob / a systemd timer at
    whatever cadence your tightest SLA needs.
    """

    fired = asyncio.run(_with_manager(lambda m: m.tick()))
    if not fired:
        console.print("[dim]no timers were due.[/]")
        return
    console.print(f"[green]Fired {len(fired)} timer(s):[/]")
    for entry in fired:
        console.print(f"  - {entry}")


@case_app.command("subcase")
def case_subcase(
    parent_uri: str = typer.Argument(..., help="Parent case URI."),
    process_uri: str = typer.Argument(..., help="Process URI governing the child case."),
    initial_state: list[str] = typer.Option(
        [],
        "--initial-state",
        "-s",
        help="Seed property as key=value (JSON or string).",
    ),
) -> None:
    """Spawn a child case under the given parent.

    When the child case closes, the parent's state gains
    ``subcase_<child_uri>_closed`` and ``subcase_<child_uri>_state`` so a
    parent decision engine can react to the child's outcome.
    """

    state = _parse_params(initial_state)
    try:
        case = asyncio.run(
            _with_manager(lambda m: m.create_subcase(parent_uri, process_uri, initial_state=state))
        )
    except CaseManagerError as exc:
        console.print(f"[red]{type(exc).__name__}:[/] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Created subcase[/] {case.case_uri} (parent={parent_uri})")


@case_app.command("fork")
def case_fork(
    case_uri: str = typer.Argument(..., help="Case URI to fork from."),
    new_uri: str | None = typer.Option(None, "--new-uri", help="URI for the forked case."),
) -> None:
    """Create a new case copying state and history from one source."""

    try:
        case = asyncio.run(_with_manager(lambda m: m.fork(case_uri, new_uri=new_uri)))
    except CaseManagerError as exc:
        console.print(f"[red]{type(exc).__name__}:[/] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Forked[/] -> {case.case_uri}")


@case_app.command("execute")
def case_execute(
    case_uri: str = typer.Argument(..., help="Case URI."),
    action_uri: str = typer.Argument(..., help="Action URI to execute."),
    param: list[str] = typer.Option(
        [],
        "--param",
        "-p",
        help="Action parameter as key=value (JSON or string).",
    ),
) -> None:
    """Execute a chosen action against a case."""

    params = _parse_params(param)
    try:
        case, outcome = asyncio.run(
            _with_manager(lambda m: m.execute_action(case_uri, action_uri, params))
        )
    except ActionValidationError as exc:
        console.print(f"[red]Validation failed:[/] {exc}")
        raise typer.Exit(code=1) from exc
    except CaseManagerError as exc:
        console.print(f"[red]{type(exc).__name__}:[/] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[bold]success:[/] {outcome.result.success}")
    console.print(f"[bold]status:[/] {case.status.value}")
    console.print(f"[bold]properties:[/] {json.dumps(case.state.properties, default=str)}")
    if case.status.value == "closed":
        console.print("[green]Goal reached — case closed.[/]")


# --- audit commands --------------------------------------------------------


@audit_app.command("show")
def audit_show(
    case_uri: str = typer.Argument(..., help="Case URI whose audit trail to show."),
) -> None:
    """Show the PROV-O activities recorded for a case."""

    activities = asyncio.run(_with_store(lambda s: s.list_by_case(case_uri)))
    if not activities:
        console.print(f"[yellow]No audit activities for case[/] {case_uri}")
        return
    table = Table(title=f"Audit trail — {case_uri}")
    table.add_column("Action", style="cyan", no_wrap=True)
    table.add_column("Agent", style="magenta")
    table.add_column("Started")
    table.add_column("Result", justify="center")
    for activity in activities:
        mark = "[green]ok[/]" if activity.success else "[red]fail[/]"
        started = activity.started_at.isoformat() if activity.started_at else "—"
        table.add_row(activity.action_uri, activity.agent or "—", started, mark)
    console.print(table)


@audit_app.command("export")
def audit_export(
    case_uri: str = typer.Argument(..., help="Case URI whose trail to export."),
    fmt: ExportFormat = typer.Option(
        "jsonld",
        "--format",
        "-f",
        help="Export format: jsonld or ttl.",
    ),
) -> None:
    """Export a case's PROV-O trail to stdout as JSON-LD or Turtle."""

    activities = asyncio.run(_with_store(lambda s: s.list_by_case(case_uri)))
    # Logs go to stderr, so stdout carries only the rendered document.
    console.print(render(activities, fmt), markup=False, highlight=False)


# --- helpers ---------------------------------------------------------------


async def _with_store(fn):
    """Open a SQLite store, run ``fn(store)``, then close it."""

    store = SqliteStore(get_settings().db_path)
    await store.connect()
    try:
        return await fn(store)
    finally:
        await store.close()


async def _with_manager(fn):
    """Open a SQLite-backed CaseManager, run ``fn(manager)``, then close.

    Wires an :class:`EngineResolver` so the right decision engine is chosen per
    process. The LLM engine is enabled when ``LLM_PROVIDER`` is set; the Bayesian
    engine when ``CONNECT_ONTORAG`` is true and the server is reachable.
    """

    settings = get_settings()
    store = SqliteStore(settings.db_path)
    await store.connect()
    ontorag_client = None
    try:
        registry = default_registry()
        ontorag_client = await maybe_connect_ontorag(
            settings,
            on_error=lambda message: console.print(f"[yellow]{message}[/]"),
        )
        resolver = EngineResolver(
            registry=registry,
            ontorag_client=ontorag_client,
            llm_client=build_llm_client(settings),
        )
        executor = ActionExecutor(audit_store=store, agent=settings.agent_id)
        manager = CaseManager(
            case_store=store,
            process_store=store,
            executor=executor,
            registry=registry,
            engine_factory=resolver.for_process,
        )
        return await fn(manager)
    finally:
        if ontorag_client is not None:
            await ontorag_client.aclose()
        await store.close()


def _parse_params(pairs: list[str]) -> dict[str, Any]:
    """Parse ``key=value`` strings; values are JSON-decoded, else kept as text."""

    params: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise typer.BadParameter(f"Expected key=value, got {pair!r}")
        key, _, raw = pair.partition("=")
        try:
            params[key] = json.loads(raw)
        except json.JSONDecodeError:
            params[key] = raw
    return params


async def _run_action(action: Action, params: dict[str, Any]):
    executor = ActionExecutor(agent=get_settings().agent_id)
    return await executor.execute(action, params, EMPTY_STATE)


async def _probe_ontorag(url: str) -> tuple[bool, str]:
    from ontorag_flow.ontorag_client import OntoragClient, OntoragClientError
    from ontorag_flow.ontorag_client.tools import smoke_test

    try:
        async with OntoragClient(url) as client:
            await smoke_test(client)
        return True, "find_entities smoke ok"
    except OntoragClientError as exc:
        return False, str(exc)


def _load_actions_from_file(path: Path, registry: ActionRegistry) -> list[str]:
    """Import a plugin module, register its concrete BaseAction subclasses."""

    spec = importlib.util.spec_from_file_location(f"_plugin_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise typer.BadParameter(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    discovered: list[str] = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, BaseAction)
            and obj is not BaseAction
            and not inspect.isabstract(obj)
            and obj.__module__ == spec.name
        ):
            instance = obj()
            registry.register(instance)
            discovered.append(instance.uri)
    return discovered


def _print_actions(registry: ActionRegistry, only: list[str] | None = None) -> None:
    table = Table(title="Actions")
    table.add_column("URI", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Side effects", style="magenta")
    for action in registry.all():
        if only is not None and action.uri not in only:
            continue
        effects = ", ".join(sorted(e.value for e in action.side_effects))
        table.add_row(action.uri, action.name, effects)
    console.print(table)
