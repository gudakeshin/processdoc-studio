"""Shared APIRouter for the wiki package (prefix=/api/wiki).

All submodules register routes on this single instance; it is mounted in
app/main.py via `from app.api.wiki import router`. URLs are unchanged from
the former single-module app/api/wiki.py.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/wiki", tags=["wiki"])
