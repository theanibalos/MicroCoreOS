# {name}

Built on [MicroCoreOS](https://github.com/theanibalos/MicroCoreOS) — an atomic
microkernel where **one file = one feature**.

Everything in this directory is yours. The Kernel arrives as a package
(`microcoreos`); the tools and domains below were copied into your project so
you can read them, edit them and replace them.

## Run it

```bash
microcoreos              # boot        (or: uv run main.py)
microcoreos dev          # boot with auto-reload on .py changes
```

Then open <http://localhost:5000/docs> for the auto-generated API, and
<http://localhost:5000/system/status> for the live health of every tool.

Configuration lives in `.env` — `.env.example` documents every variable.
SQLite is the default and needs no setup.

## Layout

```
tools/          Infrastructure you own — http, db, event_bus, auth, logger, state, ...
domains/        Your business logic. One folder per domain.
  system/         Observability endpoints (/system/*)
  devtools/       Linters that run at boot and tell you when a rule is broken
extras/         The swap catalog: tools and domains not active yet (see below)
plans/          The plan an AI agent works from
main.py         Boots the Kernel. Never needs editing — discovery is automatic.
AI_CONTEXT.md   Regenerated on every boot: live inventory of tools, tables, endpoints
```

## Add a feature

One file, dropped in `domains/<your_domain>/plugins/`, ending in `_plugin.py`:

```python
# domains/products/plugins/create_product_plugin.py
from microcoreos import BasePlugin

class CreateProductPlugin(BasePlugin):
    def __init__(self, db, http, event_bus):   # tools arrive by name
        self.db = db
        self.http = http
        self.bus = event_bus

    async def on_boot(self):
        self.http.add_api_route("/products", self.execute, methods=["POST"])

    async def execute(self, req):
        await self.db.execute(
            "INSERT INTO products (name, price) VALUES ($1, $2)", [req.name, req.price]
        )
        await self.bus.publish("product.created", {"name": req.name})
        return {"success": True}
```

Restart. No registration, no wiring, no edit to `main.py` — the Kernel finds it,
injects what its `__init__` asks for, and boots it.

Tool names and exact signatures: `AI_CONTEXT.md`. Rules and anti-patterns:
`INSTRUCTIONS_FOR_AI.md`.

## Activate an extra

```bash
microcoreos add postgres
```

One command, three acts: installs the dependency (`uv add
'microcoreos[postgres]'`), moves the source out of `extras/` into `tools/`
(and `domains/` when the extra is a pair), and appends its settings to `.env`
— never overwriting a value you already chose. `microcoreos add` with no
argument lists what is available.

The three are separate acts because they fail in different places: without the
library the boot reports `No module named 'asyncpg'`; without the source
nothing happens at all, since the Kernel only discovers what is under `tools/`
and `domains/`. `--no-install` skips the dependency step if you manage it
yourself.

## Work with an AI agent

`AGENTS.md` is the entry point — point your agent at it. It sets the reading
path (`AI_CONTEXT.md` for the live inventory, `plans/` for the task) and the
workflow to match the size of the request.

```
> Read AI_CONTEXT.md. Create a plugin in the orders domain that
> creates an order and publishes order.created.
```

The linters in `domains/devtools/` run on every boot and report architecture
violations, event contract mismatches, route collisions and table ownership
conflicts — so a mistake surfaces at boot, not in production.

## Upgrading the Kernel

```bash
uv add --upgrade microcoreos
```

That updates the Kernel only. The tools and domains in this project are your
source now: a fix upstream does not reach them on its own.
