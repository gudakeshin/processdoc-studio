"""Project API package: CRUD, conversation, preferences, and scheduled tasks.

Split from the former single-module app/api/projects.py. Route paths are
unchanged: submodules register on the shared router in _router.py, which is
mounted with prefix="/projects" in app/api/routes.py.
"""

# Importing the submodules registers their routes on the shared router.
# Order mirrors the original module: crud, conversation, preferences, tasks.
from app.api.projects import (  # noqa: F401
    conversation,
    crud,
    preferences,
    scheduled_tasks,
)
from app.api.projects._router import router  # noqa: F401

# Re-exported for compatibility with existing importers (tests import these
# helpers from app.api.projects directly).
from app.api.projects.conversation import (  # noqa: F401
    _extract_discovery_answers_fast,
    _has_sufficient_discovery,
    _is_acknowledgment,
    _is_commit_intent,
    _is_contextual_followup,
    _is_proposal_instruction,
    _is_vague_instruction,
    _merge_discovery,
    _required_discovery_missing_slots,
)
