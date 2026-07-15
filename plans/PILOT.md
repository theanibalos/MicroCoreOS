# Pilot Run — Does the Two-Session Pipeline Pay Off?

A single, measured end-to-end run of the workflow in `plans/README.md`, with
success criteria defined BEFORE starting. The goal is a yes/no answer to:
*"is the plan-first, two-session, canonical-prompt pipeline worth it?"* —
backed by numbers, not vibes.

**The human reads exactly two documents: `plans/README.md` (the how) and this
file (the what + the scorecard).** Everything else is read by the AIs.

---

## What to build: the `audit` domain

An event-driven audit trail. Chosen because it is real (feeds the future
observability dashboard), small (one wave), and exercises EVERY piece of the
machinery — including the parts that were never stress-tested together:

| Piece of the pipeline | How the audit domain exercises it |
|---|---|
| `phase_0` with `columns:` | 1 migration: `audit_entries` (id, event_name, subject_id, payload_json, created_at) |
| Pure consumer feature | `RecordAuditEntryPlugin` — consumes `user.created` AND `user.deleted` (tolerant reader), no route |
| CRUD features | `ListAuditEntriesPlugin` (GET /audit, protected), `GetAuditEntryByIdPlugin` (GET /audit/{id}, protected) |
| `flows` + sad paths | one flow: `user.* → RecordAuditEntryPlugin` with `retries: 2`, `idempotent: true` + double-delivery test, `dlq_watcher: null` (loss accepted), `sad_path_test` |
| Chain e2e test | `assert_chain(tree, ["user.created", ...])` via trace helper |

Scope: 3 features + 1 flow-tests task, 1 migration, 1 flow, no new tools.
The wave is therefore **4 executors**: one per feature (each writes test
first + plugin, per `plans/executor_rules.md`) plus one for the flow's
`e2e_test` + `sad_path_test`. Expected plan size: ~90-120 YAML lines. This
mirrors the "3 CRUDs + 1 tool" workload that once burned 60% of a session's
budget — the direct comparison point.

---

## Success criteria (fill the scorecard as you go)

| # | Metric | Target | Falsified if |
|---|---|---|---|
| 1 | Planning session total tokens | ≤ 25k | > 60k (no better than the old way) |
| 2 | Plan validation iterations | ≤ 2 rounds to zero errors | > 4 rounds |
| 3 | Execution session total tokens | ≤ 30k | > 60k |
| 4 | Executors passing on FIRST attempt (3 features + 1 flow-tests) | ≥ 3 of 4 | < 2 of 4 |
| 5 | Human code edits needed | 0 (paste prompts + run commands only) | any manual code fix |
| 6 | Prefix cache confirmed in the wave | executor 2+ processes ≤ 10% of the prompt | no reuse observed |
| 7 | Final gate | pytest green + `/system/lint` clean + AI_CONTEXT == plan | any red at the end |

**Verdict rule:** 6-7 pass → the pipeline pays off, adopt it as the standard.
4-5 pass → pays off with fixes; write down WHICH step leaked tokens/failures
and patch the docs. ≤ 3 pass → the ceremony costs more than it saves for
small tasks; keep the plan format only for multi-domain work.

---

## Run script (the human's checklist)

### Session A — Planning (conversational)
1. Open a fresh session with your smartest model.
2. Paste the Planner prompt from `plans/README.md` Step 1 with this request:
   > "Create an `audit` domain: an audit trail table that records every
   > `user.created` and `user.deleted` event, plus protected endpoints to
   > list entries (GET /audit) and fetch one (GET /audit/{id}). The consumer
   > must be idempotent with 2 retries; losing an entry after final failure
   > is accepted (no DLQ watcher)."
3. Iterate until you're satisfied. Run Step 2 validation → zero errors.
4. Send the closing message ("confirm every decision is in the plan").
5. **Record**: total tokens of the session, number of validation rounds.
   (For Claude Code sessions, tikitokens computes totals and cache hit-rate
   automatically from `~/.claude/projects/` — no manual counting.)
6. Close the session.

### Session B — Execution (systematic)
1. Fresh session / fresh AIs. Follow `plans/README.md` Steps 3-5 verbatim:
   Phase 0 prompt → boot once → `build_executor_prompt` per feature PLUS the
   flow-tests prompt for `audit-trail` (4 executors total, each a FRESH
   conversation) → dispatch (first one, then the rest) → pytest + lint →
   reconstruct failures (fresh executor + one-line hint; two strikes → back
   to the Planner).
2. **Record**: total tokens, per-executor processed-token counts (cache
   evidence — on Anthropic read `usage.cache_read_input_tokens`; local, the
   engine's `prompt_eval_count`/`prompt_n`; or run `dev_infra/cache_probe.py`),
   first-attempt pass rate, number of reconstructions.
3. When done: archive the plan (`plans/archive/`) and fill the scorecard.

### Scorecard

| Metric | Result | Pass? |
|---|---|---|
| 1. Planning tokens | | |
| 2. Validation rounds | | |
| 3. Execution tokens | | |
| 4. First-attempt pass rate | | |
| 5. Human code edits | | |
| 6. Cache reuse | | |
| 7. Final gate | | |

**Verdict:**

**What leaked (if anything) and which doc to patch:**
