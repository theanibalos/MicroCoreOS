---
name: microcoreos-architecture
description: Ensures adherence to MicroCoreOS "Atomic Microkernel" architecture. Use when creating or modifying core, tools, plugins, or domains.
---

# MicroCoreOS Architecture Skill

**Read `AGENTS.md` and follow the route for your role.** That table names the
one or two files your role needs and, just as importantly, the ones it must not
open — a Planner that also loads the plugin templates spends ~3,000 tokens on
code it will never write.

This file deliberately holds no rules, no reading path and no checklist of its
own. It is a routing table and nothing else: every row points at the one place
that owns its subject. Add a rule, a path or a checklist here and it becomes a
rival copy of something canonical — which is the one failure this file exists
to prevent.

| You need | It is in |
|---|---|
| The rules | `AGENTS.md` § Non-Negotiable Rules (canonical) |
| Kernel/tool/event-bus laws | `AGENTS.md` § Core Architectural Laws |
| The plugin template | `AI_CONTEXT.md` § Plugin Authoring Guide (regenerated every boot) |
| What exists right now | `AI_CONTEXT.md` § Available Tools / § Domains |
| The plan format and its 18 rules | `docs/PARALLEL_DEVELOPMENT.md` § Phase 1 |
| Anti-patterns, testing, building a tool | `INSTRUCTIONS_FOR_AI.md` |

Before you finish, the gates are commands, not a checklist to eyeball:

```bash
microcoreos plan validate     # the plan is a contract — zero errors
uv run -m pytest              # green
microcoreos status            # manifest still describes the code on disk
```
