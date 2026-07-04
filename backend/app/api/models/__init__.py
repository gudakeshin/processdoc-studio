"""Models API package: financial model CRUD, Excel collab, calculations, and reporting.

Split from the former single-module app/api/models.py. Route paths are
unchanged: submodules register on the shared router in _router.py, which is
mounted in app/api/routes.py. Import order preserves the original route
registration order (path sets are disjoint across modules).
"""

# Importing the submodules registers their routes on the shared router.
from app.api.models import (  # noqa: F401
    collab,
    crud,
    excel,
    financial,
    links_data,
)
from app.api.models._router import router  # noqa: F401
from app.api.models._shared import OBSERVABILITY_COUNTERS  # noqa: F401
