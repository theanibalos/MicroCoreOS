---
name: microcoreos-architecture
description: Ensures adherence to MicroCoreOS "Atomic Microkernel" architecture. Use when creating or modifying core, tools, plugins, or domains.
---

# MicroCoreOS Architecture Skill

## Reading Path

**To write a plugin**: Read `AI_CONTEXT.md` + entity model in `domains/{domain}/models/`. Nothing else.
**To create a full domain**: Use the `/new-domain` workflow.
**Templates + anti-patterns + detailed rules**: `INSTRUCTIONS_FOR_AI.md`.

## Pre-commit Checklist

- [ ] `main.py` untouched
- [ ] No cross-domain imports (use `event_bus`)
- [ ] Entity in `models/` mirrors DB only — schemas inline in plugin
- [ ] All request fields use `pydantic.Field` with constraints
- [ ] `response_model=` passed to `add_endpoint`
- [ ] Plugin is a single self-contained file
- [ ] `async def` for I/O, `def` for CPU
- [ ] Test file exists at `tests/test_{name}_plugin.py`
- [ ] `uv run main.py` runs without errors
