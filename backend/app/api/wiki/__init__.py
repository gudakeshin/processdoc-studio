"""Wiki API package: ingest, query, pages, graph, analytics, authoring.

Split from the former single-module app/api/wiki.py. Route paths are
unchanged: submodules register on the shared router in _router.py
(prefix=/api/wiki), imported here in original file order to preserve route
registration order. Mounted in app/main.py via `from app.api.wiki import router`.
"""

# Importing the submodules registers their routes on the shared router.
from app.api.wiki import (  # noqa: F401
    ingest,
    query,
    pages,
    graph,
    analytics,
    authoring,
)
from app.api.wiki._router import router  # noqa: F401

__all__ = ["router"]
