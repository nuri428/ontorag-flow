# Operator guide

> **Audience.** People who run cases — not the people who define processes
> or wire decision engines. If you spend your day at
> `http://localhost:8100/ui/` reacting to what the engine recommends, this
> is for you.

---

## What a case is

A **case** is one long-running unit of work governed by a **process
definition**. Think "one patient triage", "one shipment investigation",
"one onboarding". The process defines *what actions are allowed*; the
case is *the live state of one execution*.

Every action the case takes is recorded as a **PROV-O activity** — who
ran what, when, against which inputs, producing which outputs. The audit
log is the authority; the case's history view is just a rendering of it.

## The lifecycle states

| Status     | Meaning                                            | What you can do                                              |
|------------|----------------------------------------------------|--------------------------------------------------------------|
| `open`     | Accepting new actions                              | Execute, Suspend, Compensate, Spawn subcase, Execute top    |
| `suspended`| Pinned — engine won't auto-act, humans can't run actions | Resume, Compensate, Spawn subcase                       |
| `closed`   | Goal reached (the goal predicate became true)      | Compensate (rewinds even closed cases), Spawn subcase       |
| `failed`   | An action raised an unrecoverable error            | Compensate, Spawn subcase                                    |

## The three UI pages

## `/ui/` — Dashboard

- **Cases table** filtered by status (`all` / `open` / `suspended` /
  `closed` / `failed`). Each row links to the case detail.
- **`Tick all timers` button.** Sweeps every open case for due
  `timer_events` and runs the associated action. Use this when you
  notice SLA-driven actions haven't fired — e.g. cron stopped.
  The redirect shows `Tick fired N timer event(s).`
- **Status filter** — pick a tab to narrow the view.

## `/ui/cases/<uri>` — Case detail

The operational page. Top-down:

- **Header** with case URI, badge for current status, created/updated
  timestamps, and a **Parent** link if this is a subcase.
- **Actions bar** — only the buttons that make sense for the current
  status are rendered. The four mutating buttons:
  - **`Suspend`** (open only) — pauses the case. Use when you want to
    halt automation while a human investigates.
  - **`Resume`** (suspended only) — undoes Suspend; the case is open
    again.
  - **`Execute top proposal`** (open + engine has proposals) — runs the
    highest-confidence recommendation from the decision engine. The
    rationale was visible in the proposals table before you clicked.
  - **`Compensate (undo all)`** (history non-empty) — runs every
    action's compensation hook in reverse order, restoring `case.state`
    to its `initial_state`. Even closed cases compensate.
- **Spawn subcase** form — pick a process and create a child case
  linked back to this one via `parent_uri`. When the child closes, its
  closure event is recorded on the parent. Use for "open an
  investigation off this case".
- **State** — the current `properties` dict and `goal` predicate.
- **Decision engine proposals** — what the engine recommends *right
  now*, with confidence bars, params, and rationale (or an `Decision
  engine unavailable` callout if the engine needs an unreachable
  backend such as ontorag MCP).
- **Subcases** — children spawned from this case, each linking back to
  its own detail page.
- **History** — most recent activities. The `full audit trail →` link
  goes to the audit page.

## `/ui/cases/<uri>/audit` — Audit trail

The forensic page. Every PROV-O activity with timestamps, agent,
inputs (`used`), outputs (`generated`), and the previous activity in
the same case (`informed by`). Each row has a `Counterfactual` link.

## `/ui/cases/<uri>/explain` — Decision engine inspector

The "why?" page. Reached from the case detail's `Decision engine
proposals — why? →` link. Shows the same proposals you would see on
the case detail plus the engine's `trace` dict:

- **RuleEngine** — every rule classified as fired / unmatched /
  skipped-because-disallowed. So you can see *which* rule fired and
  *why other rules did not*.
- **BayesianMpeEngine** — target proposition + action → posterior map +
  base evidence used.
- **CausalSimulationEngine** — interventions per candidate + posterior
  map (interventional, not observational).
- **LlmAgentEngine** — the full system + user prompt, the raw LLM
  reply, and how many proposals were parsed vs returned (capped by
  `max_proposals`). When LLM output is wrong, this is where you find
  out whether the parser dropped something or the LLM never produced
  it.
- **StackedEngine** — proposer's original confidences side-by-side
  with the validator's rescored confidences.
- **HumanReviewEngine** — single-line "always defer" policy note.

If the engine doesn't implement `explain()`, the page shows the
proposals plus a note that there is no trace.

The trace is rendered with engine-specific cards (rules-fired table,
posterior breakdown bars, prompt collapsibles, proposer-vs-validator
comparison), and the full JSON is always available in a `Raw trace
(JSON)` fold so nothing is hidden — the cards just make the common
case readable.

## Counterfactual replay (Pearl Rung 3)

The audit row's **Counterfactual** link opens
`/ui/cases/<uri>/counterfactual?swap=<activity>` — a form that asks
"if that action had been a different one, what would the posterior on
the goal have been?".

You fill in:

- **Action** — which action to swap in (any registered action; the
  default is the original one).
- **Params (JSON)** — the params for the swap.

What happens when you submit:

- If the case's decision engine is causal (`engines/causal.py`), it
  runs `manager.counterfactual(...)`, which calls ontorag's
  counterfactual MCP tool, and returns the posterior. You see the
  result table at the bottom.
- If the engine is rule/Bayesian/LLM/human, you get a callout
  `CounterfactualError: counterfactual replay (need a
  CausalSimulationEngine)`. No state is changed.
- If the JSON is malformed, you get `Invalid params JSON: ...` in
  place of the result. No state is changed.

Counterfactual is a **read-only operation** — replaying does not modify
the case or audit log. It's safe to experiment.

## Error callouts and how to read them

Mutating buttons use a `POST → 303 redirect` pattern. On failure the
redirect lands back at the same page with `?error=ExceptionType: message`
in the query string, rendered as a red callout. Common ones:

| Callout text                          | What it means                                        | Fix                                                |
|---------------------------------------|------------------------------------------------------|----------------------------------------------------|
| `CaseStateTransitionError: ...`       | The button you pressed isn't valid for current state | Refresh; the button shouldn't be visible anymore   |
| `CaseNotFoundError: <uri>`            | URI typo or case was deleted                         | Go back to dashboard, navigate via link            |
| `ProcessNotFoundError: <uri>`         | Subcase form referenced a process that doesn't exist | Register the process first                         |
| `Engine returned no proposals.`       | The engine has nothing to recommend right now        | Maybe the state already satisfies all rules; pick an action manually via CLI/API |
| `Decision engine unavailable: ...`    | Engine needs ontorag MCP or an LLM client and the connection isn't live | Restart the service with `connect_ontorag=true` or set `LLM_PROVIDER` |
| `CounterfactualError: ...`            | Counterfactual replay needs a causal engine for this case | Switch the process's `engine:` to `causal` (config-time fix) |

## Common scenarios

## "An action ran by mistake — undo it"

`Compensate (undo all)`. If you only want to undo the *last* action,
that's a CLI feature (`ontorag-flow case compensate <uri>
--target-activity <uri>`); the UI's Compensate button always undoes
everything.

## "The engine recommended something risky — pause before it auto-runs"

If you have `auto_execute_top_proposal: true` set on the process,
either `Suspend` the case before the next tick, or change the process
to `auto_execute_top_proposal: false` and have a human always click
`Execute top proposal`. (Recommended default: explicit click.)

## "A timer-driven action didn't fire"

`Tick all timers` from the dashboard. This works whether the cron job
that normally calls `/cases/tick` is alive or not. The redirect tells
you how many fired.

## "I want to spin off an investigation that's tied to this case"

`Spawn subcase` form. Pick the process for the investigation. The new
case links back to this one via `parent_uri`; you'll see it in the
"Subcases" section of this case until you close it.

## "What if last week we had ordered the lab first, not the X-ray?"

Open the case's audit. Find the X-ray activity row. Click
`Counterfactual`. Pick the lab action and its params. Submit. The
posterior tells you how much the goal probability would have changed.

## Things the UI does *not* do (by design)

- **Per-activity Compensate.** The button always undoes everything;
  selective undo is CLI-only.
- **Edit a process definition.** Processes are loaded from YAML/RDF
  files; the UI is read-only for them. Use `ontorag-flow process load`
  or the JSON API.
- **Bulk operations.** No "suspend all open cases" button — that's a
  CLI/script concern.
- **CSRF token on the buttons.** The UI is intended for a single-tenant
  operator workstation (`bind: 127.0.0.1` by default). If you expose
  the API on a public URL, put it behind a reverse-proxy that enforces
  auth — *don't* skip that step.
