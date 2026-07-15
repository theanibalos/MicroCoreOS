# PLAN — EventContractLinterPlugin (event contract linter)

> **Status: IMPLEMENTED** (`domains/devtools/plugins/event_contract_linter_plugin.py`,
> exposed via `GET /system/lint`). Kept as the design record — do not treat as
> pending work. Phases 2 and 3 remain optional future evolutions.

> Implementation plan. Goal: detect at boot that the payloads published on the
> bus are compatible with what consumers expect, in the style of the existing
> `ArchitectureLinterPlugin` (same pattern: AST scan in `on_boot`, warnings to
> the logger, findings to `registry.register_domain_metadata`).

## Location and pattern

- `domains/devtools/plugins/event_contract_linter_plugin.py` (1 file = 1 feature).
- DI: `def __init__(self, container, logger, registry, http)` — same access as the arch linter (`container.registry`), plus `http` for the exposure endpoint.
- Runs in `on_boot()`: scans `domains/*/plugins/*.py` with `ast`, cross-references publishers vs consumers, registers findings. Zero runtime cost (v1 is 100% static).

## Phase 1 — Static extraction (AST)

### Publishers
Look for `*.publish(<event>, <payload>, ...)` calls:
- Event as a `str` literal → register it. Dynamic event (variable, f-string) → informative `DYNAMIC_EVENT` finding (not verifiable) and continue.
- Payload as a dict literal → extract the literal keys. If the dict has a `**spread` → known keys + `open=True` flag (the missing-key check is suppressed for that site; it is not an error).
- Payload as a variable/call → try to resolve backwards ONLY the trivial case (a prior dict-literal assignment in the same function); otherwise, informative `UNKNOWN_PAYLOAD`.
- Register the site: `domain`, file, line, plugin class.

### Consumers
Look for `*.subscribe(<event>, self.<handler>, ...)` with a literal event → locate the handler's `FunctionDef`/`AsyncFunctionDef` in the same class (AST of the same file; the "no cross-domain imports" rule guarantees the handler lives there). Inside the handler body, using the event parameter name (typically `event`):
- `event.payload["k"]` (Subscript) → **required** key.
- `event.payload.get("k")` → **optional** key (no error if missing).
- `event.payload.get("k", default)` → optional.
- Alias `p = event.payload` → follow the alias within the same function (direct assignment only, no complex flow).
- Non-analyzable access (passes the whole `event.payload` to another function, dynamic iteration) → mark the consumer as `OPAQUE_CONSUMER` (informative, no key errors).

Also treat `request(<event>, ...)` as a publisher (same payload analysis).

## Phase 1 — Checks and severities

For every event with at least one analyzable publisher and consumer:

| Code | Condition | Severity |
|---|---|---|
| `MISSING_KEY` | A consumer requires (Subscript) a key that some publish site does not include (and that site is not `open`) | **warning** (the central goal) |
| `ORPHAN_PUBLISH` | Event published with no static subscriber | info |
| `ORPHAN_SUBSCRIBE` | Subscriber of an event nobody publishes | info |
| `UNKNOWN_PAYLOAD` / `DYNAMIC_EVENT` / `OPAQUE_CONSUMER` | Not statically verifiable | info |

Always exclude `_dlq.*`, `_reply.*` and wildcards. The `system` domain's own events (`system.one_shot.*`, `event.delivery.failed`) are analyzed the same way — no special cases.

Finding format (serializable dict):
```python
{"code": "MISSING_KEY", "severity": "warning", "event": "user.created",
 "publisher": "users.CreateUserPlugin (create_user_plugin.py:57)",
 "consumer": "users.WelcomeServicePlugin.on_user_created",
 "detail": "consumer requires 'email' but the publish at line 57 does not include it"}
```

Output in `on_boot`:
- `self.registry.register_domain_metadata("system", "event_contract_violations", findings)`
- `logger.warning` per warning, one `logger.info` summary for infos (no spam).

## Phase 1b — `GET /system/lint` endpoint

New endpoint (may live in this same plugin) returning the three lint sources from `registry.get_domain_metadata()`:
```json
{"success": true, "data": {"arch_violations": [...], "drift_warnings": [...], "event_contract_violations": [...]}}
```
With a Pydantic `response_model` as the manifest requires. This endpoint is consumed by future visual tooling (linter overlays).

## Phase 2 (optional, decide after using Phase 1) — Runtime validation

An `event_bus.add_listener(...)` sink that validates every real payload against the requirements inferred from its consumers and accumulates discrepancies (counter + last example) in memory, exposed in `/system/lint` under `runtime_violations`. Catches what AST cannot (dynamic payloads). Must be O(keys) and never raise — the sink runs on the publish hot path.

## Phase 3 (optional, evolution to formal contracts)

Opt-in convention `domains/{domain}/events.py` with Pydantic models for the events the domain **emits** (the event's owner is its publisher). The linter — not the plugins — loads and validates them: (a) the emitting domain's literal publishes against its model, (b) consumer accesses against the model's fields. Consumers never import those models (the cross-domain prohibition holds: the only reader is the system domain's linter via filesystem/AST). This would add type checking, not just keys. Do NOT implement until Phase 1 is validated in real use.

## Tests (`tests/domains/system/test_event_contract_linter.py`)

Unit tests of the analyzer with plugin sources as string fixtures (no real filesystem, use `ast.parse` directly):
1. Publish with a dict literal + consumer with a Subscript of a present key → no findings.
2. Consumer requires a key the publish does not carry → `MISSING_KEY`.
3. `payload.get("k")` of an absent key → no warning (optional).
4. Dict with `**spread` → no `MISSING_KEY`.
5. F-string event → `DYNAMIC_EVENT` info.
6. Publish with no subscribers → `ORPHAN_PUBLISH`.
7. Alias `p = event.payload; p["x"]` → detects the required key.
8. Integration test: run the linter against the repo's real domains and verify it produces no false **warnings** (infos are acceptable). Note: `users.WelcomeServicePlugin` consumes `user.created` — manually verify which keys it uses vs those `CreateUserPlugin` publishes BEFORE accepting the test; if there is a real incompatibility, the linter must report it and the plugin gets fixed, not the test.

## Acceptance criteria

- `uv run main.py` boots and logs `[EventLinter] ...` with a summary (same style as ArchLinter).
- Deliberately introduce a consumer reading `event.payload["does_not_exist"]` → `MISSING_KEY` warning at boot and visible in `GET /system/lint`.
- `uv run -m pytest` green.
- No false warnings in the current repo (infos are allowed).
