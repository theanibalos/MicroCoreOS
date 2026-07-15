# Active Integration Plan — Execution Checklist

> This file is ONLY the checklist / state machine for orchestrating subagents.
> The formal contract (routes, columns, events, flows) lives in `plans/active_plan.yaml`.
> The coordinator agent (Main Agent) updates the task status as features are verified.
> Include ONLY the phases the plan actually has (no new tool → no Phase 0 tools section, etc.).

## 🛠️ Phase 0: Foundation (Serial — built 1:1 from the plan's `phase_0`)
- [ ] Task T1: Custom Tool / Replacement Driver (`tools/{name}/{name}_tool.py`)
  * **Test**: Parity suite (`tests/tools/test_{name}_parity.py`)
- [ ] Task D1: SQL Migration (`domains/{domain}/migrations/001_initial.sql`)
  * **Tables owned**: `[table_name]` (columns come from the plan's `columns:`)
- [ ] Task D2: Pydantic Entity Model (`domains/{domain}/models/{name}.py`)
  * **Entity name**: `NameEntity`

## 💻 Phase 2: Plugins & Features (Parallel)
- [ ] Task P1: Feature Plugin (`domains/{domain}/plugins/{feature}_plugin.py`)
  * **Dependencies**: `[db, event_bus]`
  * **Route**: `POST /endpoint`
  * **Event**: `domain.event`
- [ ] Task P2: Unit Test (`tests/test_{feature}_plugin.py`)

## 🚦 Phase 3: Integration & Flow Verification (End-to-End)
- [ ] Task F1: Happy-path flow chain test (`tests/test_{feature}_chain.py`)
- [ ] Task F2: Sad-path flow test (`tests/test_{feature}_dlq.py`)
