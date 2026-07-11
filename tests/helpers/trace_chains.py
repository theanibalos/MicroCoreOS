"""
Causal chain assertions — turns a plan's `flows:` happy path into an
executable assertion (docs/PARALLEL_DEVELOPMENT.md, validity rule 8).

Two entry points, one per test style:

- Live system (real e2e): trigger the flow over HTTP, fetch the forest from
  GET /system/traces/tree, and call assert_chain(forest, chain).
- In-process (bus-level): trigger the flow on a real EventBusTool, build the
  forest with build_tree(bus.get_trace_history()), and call assert_chain.

A `chain` is the list of event names of the plan's happy path, e.g.
["user.created", "welcome.notify.sent"]. It matches when those events appear
as a direct parent->child causal path anywhere in the forest — exactly what
the plan's flow declares, no intermediate hops.
"""


def build_tree(history) -> list[dict]:
    """TraceRecords from bus.get_trace_history() -> causal forest.

    Same node linking as /system/traces/tree: merge by envelope id, attach
    each node to its parent_id, roots are nodes whose parent is unknown.
    """
    nodes: dict[str, dict] = {}
    order: list[str] = []
    for record in history:
        env = record.envelope
        if env.event.startswith("_reply."):
            continue
        if env.id not in nodes:
            nodes[env.id] = {
                "id": env.id,
                "parent_id": env.parent_id,
                "event": env.event,
                "children": [],
            }
            order.append(env.id)

    roots: list[dict] = []
    for node_id in order:
        node = nodes[node_id]
        parent = nodes.get(node["parent_id"]) if node["parent_id"] else None
        (parent["children"] if parent else roots).append(node)
    return roots


def find_chain(forest: list[dict], chain: list[str]) -> bool:
    """True if `chain` exists as a direct parent->child causal path.

    The path may start at any node of the forest, not only at a root.
    """
    if not chain:
        return True

    def match_from(node, remaining):
        if node["event"] != remaining[0]:
            return False
        if len(remaining) == 1:
            return True
        return any(match_from(child, remaining[1:]) for child in node["children"])

    def walk(nodes):
        return any(match_from(n, chain) or walk(n["children"]) for n in nodes)

    return walk(forest)


def assert_chain(forest: list[dict], chain: list[str]) -> None:
    """Assert the causal chain exists; on failure, show what actually happened."""
    if find_chain(forest, chain):
        return

    def render(nodes, depth=0):
        lines = []
        for n in nodes:
            lines.append("  " * depth + n["event"])
            lines.extend(render(n["children"], depth + 1))
        return lines

    observed = "\n".join(render(forest)) or "(empty trace)"
    raise AssertionError(
        f"Causal chain {' -> '.join(chain)} not found in the trace tree.\n"
        f"Observed causality:\n{observed}"
    )
