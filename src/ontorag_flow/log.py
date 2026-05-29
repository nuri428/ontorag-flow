"""Logging setup. The project forbids ``print``; everything goes through here."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Install a Rich-backed handler on the root logger (idempotent).

    Logs go to stderr so that stdout carries only command output — keeping the
    CLI scriptable (``ontorag-flow case create ... | ...``).

    Args:
        level: A standard logging level name (e.g. ``"INFO"``, ``"DEBUG"``).
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=Console(stderr=True),
                rich_tracebacks=True,
                show_path=False,
            )
        ],
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, ensuring logging is configured first."""

    configure_logging()
    return logging.getLogger(name)
