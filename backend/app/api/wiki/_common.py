"""Shared helpers, constants, and logger for the wiki API package.

Moved verbatim from the former single-module app/api/wiki.py so that every
submodule can import the access-control helpers and regex constants.
"""

import logging
import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.config import settings
from app.db.models import User


logger = logging.getLogger(__name__)

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_PAGE_STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_WIKI_VIEW_ROLES = frozenset({"Owner", "Editor", "Viewer"})
_WIKI_EDIT_ROLES = frozenset({"Owner", "Editor"})


def _wiki_dir_for(wiki_type: str, project_id: str | None):
    from app.services.storage import workspace_path
    if wiki_type == "leading_practice":
        return workspace_path("leading_practices") / "wiki"
    return workspace_path(project_id) / "wiki"


def _wiki_lp_admin_emails() -> frozenset[str]:
    raw = (settings.wiki_lp_admin_emails or "").strip()
    if not raw:
        return frozenset()
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def _wiki_require_access(
    wiki_type: str,
    project_id: str | None,
    user: User,
    db: Session,
    *,
    mutating: bool,
) -> None:
    """Enforce auth + project role for project wiki; LP mutations require an admin allowlist.

    - ``wiki_type=project``: ``require_project_role`` on ``project_id`` (view vs. edit roles).
    - ``wiki_type=leading_practice``:
        * reads: any authenticated user (caller already passed ``get_current_user``).
        * mutations: allowed only for emails listed in ``settings.wiki_lp_admin_emails``.
          If the allowlist is empty AND ``processdoc_env == "development"``, mutations are
          permitted (preserves the historical dev-only behavior); in staging/production an
          empty allowlist denies all LP mutations so the shared LP wiki cannot be edited by
          any authenticated user.
    """
    if wiki_type not in ("leading_practice", "project"):
        raise HTTPException(status_code=400, detail="Invalid wiki_type")
    if wiki_type == "project":
        if not project_id or not _PROJECT_ID_RE.match(project_id):
            raise HTTPException(status_code=400, detail="Invalid or missing project_id")
        roles = _WIKI_EDIT_ROLES if mutating else _WIKI_VIEW_ROLES
        require_project_role(project_id, roles, user, db)
        return
    # leading_practice
    if not mutating:
        return
    admins = _wiki_lp_admin_emails()
    if admins:
        if (user.email or "").strip().lower() not in admins:
            raise HTTPException(status_code=403, detail="Leading-practice wiki mutations are restricted to admins")
        return
    # No allowlist configured — only allow mutations in development.
    env = (settings.processdoc_env or "development").strip().lower()
    if env != "development":
        raise HTTPException(
            status_code=403,
            detail="Leading-practice wiki mutations require wiki_lp_admin_emails to be configured",
        )
