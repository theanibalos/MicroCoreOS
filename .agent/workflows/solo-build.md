---
description: Build features or a whole domain sequentially as a single agent (Solo route)
---

# Solo Build Workflow

Guide for a single agent building features, domains, or an entire app end-to-end sequentially without delegating to subagents or managing multi-agent dispatch queues.

## Overview & Flow

As a **Solo** agent, you execute all phases in order. The black-box rule (not reading another agent's uncommitted work) does not apply to code **you** wrote yourself, but the validation and migration gates remain mandatory.

```text
Phase 1 (Plan) → Phase 0 (Migrations/Models) → Phase 2 (Plugins + Tests) → Phase 3 (Verify & Lint)
```

---

## Step-by-step Execution

### Phase 1: Planning
1. **Read**:
   - `plans/active_plan.yaml` (template/existing plan).
   - `AI_CONTEXT.md` down to `## 🧩 Plugin Authoring Guide` (existing tables, routes, events).
2. **Write**:
   - `plans/active_plan.yaml` (overwrite with your new domain/feature plan).
   - `plans/active_plan.md` (checklist with one checkbox per task/file).
3. **Validate**:
   ```bash
   microcoreos plan validate
   ```
   Must return **0 errors** before proceeding to code.

---

### Phase 2: Foundation (Phase 0)
*Skip if your plan has no `phase_0` section.*

1. **Write Migrations & Models**:
   - Create SQL migration files in `domains/{domain}/migrations/001_*.sql` matching `phase_0.migrations` exactly.
   - Use `-- depends: other_domain/001_*.sql` if FK ordering is needed.
   - Create Pydantic entity models in `domains/{domain}/models/*.py`.
2. **Apply & Verify**:
   ```bash
   microcoreos migrate
   microcoreos schema
   ```
   Ensure tables and columns match the plan.

---

### Phase 3: Plugin Implementation (Phase 2 Wave)
For each feature declared in `features:`:
1. **Write the Plugin**: `domains/{domain}/plugins/{feature}_plugin.py`.
   - Schemas inline at the top.
   - DI by parameter name (`http`, `db`, `event_bus`, `logger`, etc.).
   - Return envelope: `{"success": bool, "data": ..., "error": ...}`.
2. **Write its Test**: `tests/domains/{domain}/test_{feature}_plugin.py`.
   - Black-box integration tests using `@pytest.mark.migrations("{domain}")`.
   - Assert status codes, response envelope, and DB side effects.
3. **Mark Checklist**: Check off the task in `plans/active_plan.md`.

---

### Phase 4: Verification & Boot (Phase 3)
1. **Run pytest**:
   ```bash
   uv run -m pytest
   ```
2. **Boot verification**:
   ```bash
   microcoreos migrate   # regenerates AI_CONTEXT.md and validates system integrity
   ```
3. Done!
