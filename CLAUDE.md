# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Reading Path (minimize token usage)

**To write a plugin or domain**: Read `AI_CONTEXT.md` + the entity model in `domains/{domain}/models/`. Nothing else.
**For testing, observability, or creating tools**: Read `INSTRUCTIONS_FOR_AI.md`.

## Commands

```bash
uv run main.py                              # Run the app
uv run -m pytest                            # Run all tests
uv run -m pytest tests/test_file.py         # Run single test
docker compose -f dev_infra/docker-compose.yml up -d  # Dev infra
```

## Essential Rules

1. **Never modify `main.py`** — Kernel auto-discovers everything. Features NEVER touch it; the only thing that lives there is generic process entry-mode dispatch (e.g. `--boot-tool <name>`), and adding a new mode requires explicit human approval. Neither `main.py` nor `core/` may reference any specific tool.
2. **1 file = 1 feature** — Plugins in `domains/{domain}/plugins/`.
3. **DI by name** — `__init__` parameter names match tool `name` properties.
4. **Entity in models/ = DB mirror only** — Request AND response schemas go inline in the plugin.
5. **No cross-domain imports** — Use `event_bus` for communication.
6. **Return format**: `{"success": bool, "data": ..., "error": ...}`.
7. **Safe Errors**: NEVER return `str(e)` to clients. Use generic messages.
8. **No Magic**: Kernel (ToolProxy) NEVER retries tool calls automatically.
9. **Runner**: Always `uv run`.
10. **Core uses `print()`, not the logger** — by design: the logger is a swappable tool and `core/` must not depend on it. Do not "fix" this.
11. **Protect endpoints**: Pass `auth_validator=self.auth.validate_token` to `add_endpoint` for any non-public endpoint, and check ownership via `data["_auth"]["sub"]` inside the handler.

> Advanced topics (testing, observability, creating tools): `INSTRUCTIONS_FOR_AI.md`.
