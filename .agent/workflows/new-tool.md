---
description: Create a new infrastructure Tool, or a replacement Tool that swaps an existing one (parity suite mandatory)
---

# New Tool Workflow

Tools are the ONE legitimate place for shared infrastructure logic. Everything
else about them exists so they can be swapped without touching a single plugin.

## Prerequisites

- Read `INSTRUCTIONS_FOR_AI.md` → "New Tool" and "The Parity Rule".
- Decide which case you are in:
  - **A. New capability** (a tool name that does not exist yet, e.g. `s3`).
  - **B. Replacement** (same `name`, different backend, e.g. Redis state for
    in-memory state). **The parity suite is NOT optional here.**

## Rules (both cases)

1. **Location**: `tools/{name}/{name}_tool.py` — or `extras/available_tools/{name}/`
   if it should not be active by default (a replacement ALWAYS starts in
   extras/: two tools with the same `name` silently overwrite each other).
2. **The `name` property is the contract** — it is the DI injection key.
3. **A tool never uses other tools.** If a capability needs `db` + `event_bus`
   + `scheduler`, it is not a tool: compose it in the plugin layer
   (precedents: DurableOneShotsPlugin, the deferred Outbox — Issue 28).
4. **Self-documented**: every public method appears in
   `get_interface_description()` — the anti-drift linter warns on discrepancies.
5. **Config via `os.getenv()`** inside the tool (the `config` tool is for plugins).
6. **Header spec**: the tool's docstring/header documents its replacement
   contract — the exact API and semantics a substitute must honor.
7. **External backend?** Make its connection-error class inherit
   `ToolUnavailableError` so ToolProxy marks it DEAD on the first
   infrastructure failure. In-memory/local tools skip this.

## Steps

### 1. Write the contract first

The header spec + `get_interface_description()`. If this is case B, the
contract already exists in the reference tool's header — read it, honor it.
If the tool is phase 0 of a formal plan, the plan's `contract:` entry declares
the signatures — honor it the way migrations honor `columns:`, never inventing
a method. Keep the signatures backend-neutral: a payments contract that mirrors
one provider's API makes the future swap cost what the abstraction saved.

### 2. Implement

No imports from other tools, no plugin imports, stateless where possible.

### 3. Parity suite (case B: mandatory / case A: write it for the future)

The same test battery runs against the reference implementation AND yours:

- Canonical examples: `tests/tools/test_state_parity.py`,
  `tests/tools/test_event_bus_broker_parity.py` (parameterized over transports).
- If the backend needs a server, the suite skips itself when unavailable and
  the server is added to CI services (`dev_infra/docker-compose.yml`).
- **A replacement that does not pass the reference's parity suite is not a
  replacement.** (Issue 22 — Contract Parity Rules.)

### 4. Activate and verify end to end

- Case B: move the reference out of `tools/`, move yours in (or set its env
  switch), boot, and exercise a real flow through the swapped tool.
- Check `AI_CONTEXT.md` regenerated with the tool's interface, and
  `GET /system/status` shows it `OK`.

### 5. Document

- Add the tool to `README.md` (Available Tools / extras table).
- If it introduced a new pattern or decision, record it in `ROADMAP.md`.
