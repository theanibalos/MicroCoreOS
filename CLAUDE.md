# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Reading Path (minimize token usage)

**To write a plugin or domain**: Read `AI_CONTEXT.md` + the entity model in `domains/{domain}/models/`. Nothing else.
**For testing, observability, or creating tools**: Read `INSTRUCTIONS_FOR_AI.md`.

## Commands

```bash
uv run main.py                              # Run the app
uv run pytest                               # Run all tests
uv run pytest tests/test_file.py            # Run single test
docker compose -f dev_infra/docker-compose.yml up -d  # Dev infra
```

## Essential Rules

1. **Never modify `main.py`** — Kernel auto-discovers everything.
2. **1 file = 1 feature** — Plugins in `domains/{domain}/plugins/`.
3. **DI by name** — `__init__` parameter names match tool `name` properties.
4. **Entity in models/ = DB mirror only** — Request AND response schemas go inline in the plugin.
5. **No cross-domain imports** — Use `event_bus` for communication.
6. **Return format**: `{"success": bool, "data": ..., "error": ...}`.
7. **Runner**: Always `uv run`.

> Advanced topics (testing, observability, creating tools): `INSTRUCTIONS_FOR_AI.md`.
