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
from ontorag_flow.core.registry import ActionRegistry, default_registry
from ontorag_flow.core.state import EMPTY_STATE
from ontorag_flow.engines.rule import RuleEngine
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

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"ontorag-flow {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    _version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True,
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
    console.print("[green]Created .env from .env.example.[/] Edit it to point at your ontorag MCP server.")


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
        [], "--param", "-p", help="Action parameter as key=value (value parsed as JSON, else string).",
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
        outcome = asyncio.run(_run_action(action, params))
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
    """Load a process definition from YAML and persist it."""

    try:
        process = load_process(path)
    except ProcessParseError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc

    asyncio.run(_with_manager(lambda m: m.register_process(process)))
    console.print(
        f"[green]Loaded process[/] {process.process_uri} "
        f"({len(process.allowed_actions)} allowed action(s))."
    )


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
        [], "--initial-state", "-s", help="Seed property as key=value (JSON or string).",
    ),
) -> None:
    """Create a new case from a process definition."""

    state = _parse_params(initial_state)
    try:
        case = asyncio.run(
            _with_manager(lambda m: m.create_case(process_uri, initial_state=state))
        )
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
    except CaseManagerError as exc:
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


@case_app.command("execute")
def case_execute(
    case_uri: str = typer.Argument(..., help="Case URI."),
    action_uri: str = typer.Argument(..., help="Action URI to execute."),
    param: list[str] = typer.Option(
        [], "--param", "-p", help="Action parameter as key=value (JSON or string).",
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


# --- helpers ---------------------------------------------------------------


async def _with_manager(fn):
    """Open a SQLite-backed CaseManager, run ``fn(manager)``, then close."""

    settings = get_settings()
    store = SqliteStore(settings.db_path)
    await store.connect()
    try:
        executor = ActionExecutor(audit_store=store, agent=settings.agent_id)
        manager = CaseManager(
            case_store=store,
            process_store=store,
            executor=executor,
            registry=default_registry(),
            engine_factory=RuleEngine.from_process,
        )
        return await fn(manager)
    finally:
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
