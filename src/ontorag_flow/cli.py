"""Command-line interface (Typer + Rich).

v0.1 scope: project ``init``, the ``action`` sub-app (list / register / run a
single action — no cases yet), an ontorag connectivity ``status`` check, and
``serve`` for the API.
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
from ontorag_flow.core.executor import ActionExecutor, ActionValidationError
from ontorag_flow.core.registry import ActionRegistry, default_registry
from ontorag_flow.core.state import EMPTY_STATE
from ontorag_flow.log import configure_logging

app = typer.Typer(
    name="ontorag-flow",
    help="Ontology-grounded adaptive case management — the Kinetic layer over ontorag.",
    no_args_is_help=True,
    add_completion=False,
)
action_app = typer.Typer(help="Inspect, register, and run actions.", no_args_is_help=True)
app.add_typer(action_app, name="action")

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


# --- helpers ---------------------------------------------------------------


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
