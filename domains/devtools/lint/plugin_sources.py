"""Where every devtools linter reads plugin sources from.

Each linter reasons about a different rule, but they all need the same two
facts first: which files are plugins, and which domain owns each one. That
enumeration lives here and nowhere else — a linter that walked the tree its own
way would silently lint a different set of files than its neighbours, and the
disagreement would be invisible (both would just report "no violations").

Not a tool: this is not a capability plugins consume, it is devtools' internal
vocabulary for reading the repo.
"""

import os
from typing import Iterator


def iter_plugin_files() -> Iterator[tuple[str, str]]:
    """Yields (domain, filepath) for every plugin file in domains/*/plugins/.

    Deterministic order (sorted) so two runs report findings in the same order.
    """
    domains_dir = os.path.abspath("domains")
    if not os.path.isdir(domains_dir):
        return

    for domain in sorted(os.listdir(domains_dir)):
        plugins_dir = os.path.join(domains_dir, domain, "plugins")
        if not os.path.isdir(plugins_dir):
            continue
        for filename in sorted(os.listdir(plugins_dir)):
            if filename.endswith(".py"):
                yield domain, os.path.join(plugins_dir, filename)
