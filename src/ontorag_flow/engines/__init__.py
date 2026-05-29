"""Decision engines — pluggable strategies for proposing the next action.

Decision engines are first-class, swappable components. They *propose*; they
never *execute* (recommendation is not execution). Implementations arrive over
several milestones: rule (v0.3), Bayesian MPE (v0.4), LLM agent (v0.5), causal
simulation (v0.8), and a human-in-the-loop fallback.
"""

from __future__ import annotations

from ontorag_flow.engines.base import DecisionEngine
from ontorag_flow.engines.bayesian import BayesianMpeEngine

__all__ = ["DecisionEngine", "BayesianMpeEngine"]
