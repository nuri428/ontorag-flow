"""Shared posterior extraction for engines that score via ontorag MCP tools.

Both :class:`~ontorag_flow.engines.bayesian.BayesianMpeEngine` (observational,
Pearl Rung 1) and :class:`~ontorag_flow.engines.causal.CausalSimulationEngine`
(interventional, Pearl Rung 2) ask ontorag for a posterior, but ontorag's
v0.7/v0.8 response schemas are still provisional. This module owns the tolerant
parser so the two engines stay in sync.
"""

from __future__ import annotations

from typing import Any

__all__ = ["extract_posterior"]


def extract_posterior(result: Any) -> float:
    """Coerce an ontorag posterior response into a float in ``[0, 1]``.

    Accepts, in order:

    1. a bare ``float``/``int`` (the posterior itself);
    2. a mapping with a numeric ``"posterior"`` key;
    3. a mapping with a numeric ``"probability"`` key.

    Args:
        result: Whatever the ontorag tool returned.

    Returns:
        The posterior probability as a float.

    Raises:
        ValueError: If no probability can be extracted, or it falls outside
            ``[0, 1]``.
    """

    if isinstance(result, bool):
        raise ValueError(f"Cannot extract a posterior from boolean result: {result!r}")
    if isinstance(result, (int, float)):
        value: Any = result
    elif isinstance(result, dict) and _is_number(result.get("posterior")):
        value = result["posterior"]
    elif isinstance(result, dict) and _is_number(result.get("probability")):
        value = result["probability"]
    else:
        raise ValueError(
            "Could not extract a posterior probability from ontorag response "
            f"(expected a float, or a 'posterior'/'probability' key): {result!r}"
        )

    posterior = float(value)
    if not 0.0 <= posterior <= 1.0:
        raise ValueError(f"Posterior {posterior} is outside the valid probability range [0, 1].")
    return posterior


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
