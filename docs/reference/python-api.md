# Python API

Auto-rendered from in-source Google-style docstrings via
[mkdocstrings](https://mkdocstrings.github.io/). The signatures below
are *the same code* the runtime imports — they cannot drift from the
implementation.

Use this page as the *type-level* reference. For *task-level* guidance
see [How-to](../how-to/engines.md) and [Tutorials](../tutorials/first-case.md).

---

## Core

### `core.action`

::: ontorag_flow.core.action
    options:
      members:
        - SideEffectKind
        - ActionResult
        - ActionProposal
        - ProvOActivity
        - Action
        - BaseAction

### `core.case`

::: ontorag_flow.core.case
    options:
      members:
        - CaseStatus
        - CaseState
        - CaseEvent
        - Case

### `core.process`

::: ontorag_flow.core.process
    options:
      members:
        - ProcessDefinition
        - ProcessParseError
        - load_process

### `core.process_rdf`

::: ontorag_flow.core.process_rdf
    options:
      members:
        - process_to_rdf
        - load_process_rdf

### `core.case_manager`

::: ontorag_flow.core.case_manager
    options:
      members:
        - CaseManager
        - CaseManagerError
        - ProcessNotFoundError
        - CaseNotFoundError
        - ActionNotAllowedError
        - ActionNotFoundError
        - CaseClosedError
        - NoEngineConfiguredError
        - CompensationError
        - CaseStateTransitionError
        - ConstraintViolationError
        - CounterfactualError

### `core.registry`

::: ontorag_flow.core.registry
    options:
      members:
        - ActionRegistry
        - default_registry
        - with_triple_actions

### `core.executor`

::: ontorag_flow.core.executor
    options:
      members:
        - ActionExecutor
        - ActionValidationError

---

## Engines

### `engines.base`

::: ontorag_flow.engines.base
    options:
      members:
        - DecisionEngine
        - EngineExplanation

### `engines.rule`

::: ontorag_flow.engines.rule
    options:
      members:
        - RuleEngine
        - Rule
        - RuleOutcome

### `engines.bayesian`

::: ontorag_flow.engines.bayesian
    options:
      members:
        - BayesianMpeEngine
        - BayesianConfig
        - BayesianCandidate

### `engines.causal`

::: ontorag_flow.engines.causal
    options:
      members:
        - CausalSimulationEngine
        - CausalConfig
        - CausalCandidate
        - StackedEngine
        - CounterfactualResult

### `engines.cascade`

::: ontorag_flow.engines.cascade
    options:
      members:
        - CascadeEngine

### `engines.llm_agent`

::: ontorag_flow.engines.llm_agent
    options:
      members:
        - LlmAgentEngine
        - LlmClient

### `engines.human`

::: ontorag_flow.engines.human
    options:
      members:
        - HumanReviewEngine

### `engines.selection`

::: ontorag_flow.engines.selection
    options:
      members:
        - EngineResolver
        - EngineUnavailableError

---

## Actions

### `actions.case_state`

::: ontorag_flow.actions.case_state
    options:
      members:
        - UpdateCaseProperty
        - SetGoal

### `actions.human`

::: ontorag_flow.actions.human
    options:
      members:
        - RequestHumanReview

### `actions.triples`

::: ontorag_flow.actions.triples
    options:
      members:
        - AssertTriple
        - RetractTriple

---

## Stores

### `stores.base`

::: ontorag_flow.stores.base
    options:
      members:
        - OptimisticLockError

### `stores.sqlite`

::: ontorag_flow.stores.sqlite
    options:
      members:
        - SqliteStore

### `stores.postgres`

::: ontorag_flow.stores.postgres
    options:
      members:
        - PostgresStore

---

## ontorag client

### `ontorag_client.client`

::: ontorag_flow.ontorag_client.client
    options:
      members:
        - OntoragClient
        - OntoragClientError

### `ontorag_client.tools`

::: ontorag_flow.ontorag_client.tools
    options:
      members:
        - find_entities
        - describe_entity
        - get_schema
        - compute_posterior
        - do_query
        - counterfactual
        - assert_triple
        - retract_triple
        - smoke_test
