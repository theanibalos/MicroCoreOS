"""
The wheel's template payload, derived from the one list that already defines it.

`microcoreos new` copies from two places: the repo root in a checkout of the
framework, and `microcoreos/_template/` when installed from the wheel. What to
copy was written down twice — `scaffold.RUNTIME_ENTRIES` for the first and a
hand-maintained `force-include` table in pyproject.toml for the second — with
nothing keeping them in step.

They drifted the first time anyone edited one of them: moving auth into an
extra shipped four plugins packaged and copied nine from a checkout, because
`force-include` does not honour the `exclude` list and the pyproject table had
not been narrowed. The failure is invisible without building a wheel, which is
the worst kind: the suite is green and the artefact is wrong.

So the table is gone and this hook computes it. One list, in Python, next to
the code that reads it.
"""

import sys

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

TEMPLATE_ROOT = "microcoreos/_template"


class TemplatePayloadHook(BuildHookInterface):
    PLUGIN_NAME = "template-payload"

    def initialize(self, version, build_data):
        # The build runs isolated, so the package being built is not importable
        # by default — the source is right there at self.root, it just is not on
        # the path. Safe to import once it is: scaffold reaches only os, shutil
        # and upgrade, and upgrade reaches only the standard library, so nothing
        # here drags a runtime dependency into the build environment.
        if self.root not in sys.path:
            sys.path.insert(0, self.root)

        from microcoreos.scaffold import AI_KIT_ENTRIES, RUNTIME_ENTRIES

        for entry in RUNTIME_ENTRIES + AI_KIT_ENTRIES:
            build_data["force_include"][entry] = f"{TEMPLATE_ROOT}/{entry}"
