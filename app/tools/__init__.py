"""tools package: the eleven tools of spec 2.2, registered with one call to `register_all(registry)`.

Tool modules are imported lazily inside `register_all`, so `import tools` works even before they exist.
Tools depend only on `common`.
"""

from __future__ import annotations

import importlib

from common.schema import TOOL_NAMES
from common.tooling import ToolRegistry, ToolSpec

TOOL_MODULES = ("tools.places", "tools.evidence", "tools.files", "tools.course", "tools.publish")


def register_all(registry: ToolRegistry) -> None:
    """Register every module's `SPECS` in spec 2.2 order (`TOOL_NAMES`)."""
    specs: list[ToolSpec] = []
    for module_name in TOOL_MODULES:
        module = importlib.import_module(module_name)
        specs.extend(module.SPECS)
    order = {name: i for i, name in enumerate(TOOL_NAMES)}
    for spec in sorted(specs, key=lambda s: order.get(s.name, len(order))):
        registry.register(spec)
