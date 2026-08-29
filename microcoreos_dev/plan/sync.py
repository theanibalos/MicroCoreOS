"""Checklist generator & synchronizer for MicroCoreOS execution plans.

Reads a Plan object (from `plans/active_plan.yaml`) and generates or updates
the markdown execution checklist at `plans/active_plan.md`.

Preserves existing `[x]` / `[X]` progress so synchronizing a plan does not
reset completed tasks, while ensuring 100% path coverage for Rule 15 and
eliminating the template marker so Rule 0 passes.
"""
import os
from typing import Optional

from microcoreos_dev.plan.schema import Plan, PlanTool


def generate_checklist(plan: Plan, existing_checklist: Optional[str] = None) -> str:
    """Generate or update the markdown checklist from a Plan instance.

    Every file:, test:, migration, model and tool path is generated with a checkbox.
    If existing_checklist contains checked boxes (`- [x]` or `- [X]`) for a path,
    that checkmark is preserved in the updated output.
    """
    done_paths = set()
    if existing_checklist:
        for line in existing_checklist.splitlines():
            stripped = line.strip()
            if stripped.startswith(("- [x]", "- [X]", "* [x]", "* [X]")):
                for token in line.split():
                    clean = token.strip("`(),*[]\"'")
                    if "/" in clean or clean.endswith((".py", ".sql")) or clean.startswith("microcoreos"):
                        done_paths.add(clean)
                        done_paths.add(os.path.basename(clean))

    def mark(path: str) -> str:
        if path in done_paths or os.path.basename(path) in done_paths:
            return "- [x]"
        return "- [ ]"

    lines = [
        "# Active Integration Plan — Execution Checklist",
        "",
        "> This file is the checklist / state machine for orchestrating subagents.",
        "> The formal contract (routes, columns, events, flows) lives in `plans/active_plan.yaml`.",
        "> The coordinator agent updates the task status as features are verified.",
        "",
    ]

    # Phase 0: Foundation
    p0 = plan.phase_0
    has_p0 = bool(p0.tools or p0.migrations or p0.models)
    if has_p0:
        lines.append("## 🛠️ Phase 0: Foundation (Serial — built 1:1 from the plan's `phase_0`)")
        for tool in p0.tools:
            name = tool.name if isinstance(tool, PlanTool) else str(tool)
            file_path = tool.file if isinstance(tool, PlanTool) else str(tool)
            lines.append(f"{mark(file_path)} Task T_{name}: Tool `{name}` (`{file_path}`)")
        for migration in p0.migrations:
            lines.append(f"{mark(migration.file)} Task M_{os.path.basename(migration.file)}: SQL Migration (`{migration.file}`)")
            if migration.tables:
                lines.append(f"  * **Tables owned**: `{migration.tables}`")
        for model in p0.models:
            lines.append(f"{mark(model)} Task D_{os.path.basename(model)}: Model (`{model}`)")
        migrate_cmd = "microcoreos migrate"
        lines.append(f"{mark(migrate_cmd)} Task P0_Migrate: Apply migrations (`{migrate_cmd}`)")
        lines.append("")

    # Phase 2: Plugins & Features
    if plan.features:
        lines.append("## 💻 Phase 2: Plugins & Features (Parallel)")
        for idx, feat in enumerate(plan.features, 1):
            lines.append(f"{mark(feat.file)} Task P{idx}: Feature Plugin `{feat.plugin}` (`{feat.file}`)")
            details = []
            if feat.route:
                details.append(f"**Route**: `{feat.route.method.upper()} {feat.route.path}`")
            if feat.publishes:
                events = [p.event for p in feat.publishes]
                details.append(f"**Publishes**: `{events}`")
            if feat.consumes:
                events = [c.event for c in feat.consumes]
                details.append(f"**Consumes**: `{events}`")
            if feat.tools:
                details.append(f"**Tools**: `{feat.tools}`")
            for d in details:
                lines.append(f"  * {d}")
            if feat.test:
                lines.append(f"{mark(feat.test)} Task P{idx}_Test: Unit Test (`{feat.test}`)")
        lines.append("")

    # Phase 3: Integration & Flow Verification
    if plan.flows:
        lines.append("## 🚦 Phase 3: Integration & Flow Verification (End-to-End)")
        for idx, flow in enumerate(plan.flows, 1):
            if flow.e2e_test:
                lines.append(f"{mark(flow.e2e_test)} Task F{idx}_E2E: Flow `{flow.name}` E2E test (`{flow.e2e_test}`)")
            if flow.sad_path_test:
                lines.append(f"{mark(flow.sad_path_test)} Task F{idx}_Sad: Flow `{flow.name}` Sad-path test (`{flow.sad_path_test}`)")
            for link in flow.links:
                if link.idempotency_test:
                    lines.append(f"{mark(link.idempotency_test)} Task F{idx}_Idempotent: `{link.consumes} → {link.consumer}` (`{link.idempotency_test}`)")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def sync_checklist(plan_path: str = os.path.join("plans", "active_plan.yaml"),
                   checklist_path: str = os.path.join("plans", "active_plan.md")) -> tuple[bool, str]:
    """Read plan_path, update checklist_path, and return (success, message)."""
    if not os.path.isfile(plan_path):
        return False, f"No plan file found at {plan_path}"

    from microcoreos_dev.plan.rules import parse_plan_yaml

    with open(plan_path, "r", encoding="utf-8") as f:
        content = f.read()

    plan_dict, err = parse_plan_yaml(content)
    if err:
        return False, f"Could not parse plan: {err}"

    try:
        plan = Plan(**plan_dict)
    except Exception as e:
        return False, f"Plan schema error: {e}"

    existing = None
    if os.path.isfile(checklist_path):
        with open(checklist_path, "r", encoding="utf-8") as f:
            existing = f.read()

    generated = generate_checklist(plan, existing)

    # Ensure parent dir exists
    parent = os.path.dirname(checklist_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(checklist_path, "w", encoding="utf-8") as f:
        f.write(generated)

    return True, f"Synchronized {checklist_path} from {plan_path}"
