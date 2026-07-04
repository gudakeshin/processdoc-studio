"""Shared APIRouter for the models package.

All submodules register routes on this single router instance; the aggregate is
mounted in app/api/routes.py, so every URL is unchanged from the former
single-module app/api/models.py.
"""

from fastapi import APIRouter

router = APIRouter()
