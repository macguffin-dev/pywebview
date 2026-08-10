"""Loads pythonnet with the runtime pywebview wants.

Importing this module chooses the runtime -- coreclr first, netfx as a
fallback -- and loads pythonnet, so the Windows backends can just do
``from webview.platforms._pythonnet import clr`` instead of each repeating
the bootstrap. The runtime has to be selected before pythonnet is imported,
which is why the import below trails a statement.
"""

from webview.clr_runtime import select_runtime

select_runtime()

import clr  # noqa: E402, F401
