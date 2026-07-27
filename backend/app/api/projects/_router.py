"""Shared APIRouter for the projects package.

All submodules register routes on this single router instance (FastAPI cannot
nest an empty-path route via include_router with an empty prefix, and the
list/create routes use path ""). The aggregate is mounted with
prefix="/projects" in app/api/routes.py, so every URL is unchanged from the
former single-module app/api/projects.py.
"""

from fastapi import APIRouter

router = APIRouter()
