"""Concrete tool modules — imported to trigger ``registry.register()`` calls.

Each ``.py`` file in this package registers its tools at module-import
time via ``abstract.tools.registry.registry.register()``.  Just importing
this package is enough to populate the global ToolRegistry.
"""

from . import filesystem  # noqa: F401 — side-effect: registers filesystem tools
from . import code        # noqa: F401 — side-effect: registers code tools