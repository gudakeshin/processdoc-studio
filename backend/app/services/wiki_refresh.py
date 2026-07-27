"""
Wiki source tracking and continuous refresh (Phase 4).

Tracks source freshness and automatically refreshes wiki pages when sources change.
Implements smart scheduling and handles incremental updates with change detection.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from app.core.tz import IST
from pathlib import Path
from typing import Any

from app.services.storage import workspace_path

_LOG = logging.getLogger(__name__)


class SourceTracker:
    """Track and manage source freshness."""

    def __init__(self, wiki_type: str = "leading_practice", project_id: str | None = None):
        """Initialize source tracker."""
        self.wiki_type = wiki_type
        self.project_id = project_id
        self.wiki_dir = self._get_wiki_dir()
        self.sources_file = self._get_sources_file()
        self.sources_metadata = self._load_sources_metadata()

    def _get_wiki_dir(self) -> Path:
        """Get wiki directory."""
        if self.wiki_type == "leading_practice":
            return workspace_path("leading_practices") / "wiki"
        else:
            return workspace_path(self.project_id) / "wiki"

    def _get_sources_file(self) -> Path:
        """Get sources metadata file path."""
        meta_dir = self.wiki_dir / ".meta"
        return meta_dir / "sources_metadata.json"

    def _load_sources_metadata(self) -> dict[str, Any]:
        """Load sources metadata."""
        try:
            if self.sources_file.exists():
                return json.loads(self.sources_file.read_text(encoding="utf-8"))
            return {"sources": {}, "last_checked": None, "version": 1}
        except Exception as e:
            _LOG.warning(f"Error loading sources metadata: {e}")
            return {"sources": {}, "last_checked": None, "version": 1}

    def register_source(
        self,
        page_id: str,
        source_url: str,
        source_type: str = "url",
    ) -> bool:
        """
        Register a source for a wiki page.

        Args:
            page_id: Page ID
            source_url: Source URL/path
            source_type: Type of source (url, document, memory, run)

        Returns:
            True if registered
        """
        try:
            if page_id not in self.sources_metadata["sources"]:
                self.sources_metadata["sources"][page_id] = {
                    "sources": [],
                    "last_synced": None,
                    "current_hash": None,
                }

            # Check if source already registered
            existing = next(
                (s for s in self.sources_metadata["sources"][page_id]["sources"]
                 if s["url"] == source_url),
                None
            )

            if not existing:
                self.sources_metadata["sources"][page_id]["sources"].append({
                    "url": source_url,
                    "type": source_type,
                    "added_at": datetime.now(IST).isoformat(),
                    "last_checked": None,
                    "hash": None,
                    "status": "pending",
                })

            self._persist()
            return True

        except Exception as e:
            _LOG.error(f"Error registering source: {e}")
            return False

    def check_source_freshness(self, page_id: str) -> dict[str, Any]:
        """
        Check if page sources have changed.

        Args:
            page_id: Page ID

        Returns:
            {
                "page_id": str,
                "has_changes": bool,
                "sources_checked": int,
                "sources_changed": int,
                "details": [source freshness info]
            }
        """
        try:
            if page_id not in self.sources_metadata["sources"]:
                return {
                    "page_id": page_id,
                    "has_changes": False,
                    "sources_checked": 0,
                    "sources_changed": 0,
                    "details": [],
                }

            page_sources = self.sources_metadata["sources"][page_id]
            changed_sources = []
            checked = 0

            for source in page_sources.get("sources", []):
                source_url = source.get("url", "")
                source_type = source.get("type", "url")

                try:
                    current_hash = self._get_source_hash(source_url, source_type)
                    checked += 1
                    old_hash = source.get("hash")

                    if old_hash and current_hash != old_hash:
                        changed_sources.append({
                            "url": source_url,
                            "type": source_type,
                            "old_hash": old_hash,
                            "new_hash": current_hash,
                            "changed": True,
                        })
                    else:
                        source["hash"] = current_hash
                        source["last_checked"] = datetime.now(IST).isoformat()

                except Exception as e:
                    _LOG.warning(f"Error checking source {source_url}: {e}")
                    changed_sources.append({
                        "url": source_url,
                        "type": source_type,
                        "error": str(e),
                    })

            self._persist()

            return {
                "page_id": page_id,
                "has_changes": len(changed_sources) > 0,
                "sources_checked": checked,
                "sources_changed": len(changed_sources),
                "details": changed_sources,
            }

        except Exception as e:
            _LOG.error(f"Error checking source freshness: {e}")
            return {
                "page_id": page_id,
                "has_changes": False,
                "error": str(e),
            }

    def _get_source_hash(self, source_url: str, source_type: str) -> str:
        """
        Get hash of source content for change detection.

        Args:
            source_url: Source URL/path
            source_type: Type of source

        Returns:
            Content hash
        """
        try:
            if source_type == "url":
                from app.core.config import settings
                from app.services.http_fetch import SafeFetchError, safe_get

                try:
                    body = safe_get(
                        source_url,
                        max_bytes=int(getattr(settings, "http_fetch_max_bytes", 2_000_000)),
                        timeout=float(getattr(settings, "http_fetch_timeout_sec", 15.0)),
                    )
                    content = body.decode("utf-8", errors="replace")
                except SafeFetchError:
                    return "not_found"
            elif source_type == "document":
                # Handle local file
                path = Path(source_url)
                if path.exists():
                    content = path.read_text(encoding="utf-8")
                else:
                    return "not_found"
            else:
                # For memory, run, etc., use the URL as-is
                content = source_url

            return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()[:16]

        except Exception as e:
            _LOG.warning(f"Error getting source hash: {e}")
            return "error"

    def get_pages_needing_refresh(self, days_old: int = 14) -> list[str]:
        """
        Get pages whose sources haven't been checked recently.

        Args:
            days_old: Days since last check before marking for refresh

        Returns:
            List of page IDs
        """
        try:
            threshold = datetime.now(IST) - timedelta(days=days_old)
            pages_to_refresh = []

            for page_id, page_data in self.sources_metadata.get("sources", {}).items():
                last_checked = page_data.get("last_synced")

                if not last_checked:
                    # Never checked
                    pages_to_refresh.append(page_id)
                else:
                    try:
                        checked_date = datetime.fromisoformat(last_checked)
                        if checked_date < threshold:
                            pages_to_refresh.append(page_id)
                    except Exception:  # noqa: S110 — best-effort, non-fatal
                        pass

            return pages_to_refresh

        except Exception as e:
            _LOG.error(f"Error getting pages needing refresh: {e}")
            return []

    def get_refresh_priority(self) -> list[dict[str, Any]]:
        """
        Get prioritized list of pages for refresh.

        Prioritizes:
        1. High-traffic pages
        2. Frequently-cited pages
        3. Oldest pages

        Returns:
            Prioritized list of pages with their metrics
        """
        try:
            from app.services.wiki_analytics import PageAnalytics

            analytics = PageAnalytics()
            popular_pages = analytics.get_popular_pages(limit=100)
            popular_ids = {p["page_id"] for p in popular_pages}

            refresh_list = []

            for page_id, page_data in self.sources_metadata.get("sources", {}).items():
                last_synced = page_data.get("last_synced")
                sources_count = len(page_data.get("sources", []))

                # Calculate priority
                priority = 0

                # High-traffic pages get higher priority
                if page_id in popular_ids:
                    popularity = next(p["view_count"] for p in popular_pages if p["page_id"] == page_id)
                    priority += popularity / 10

                # Older syncs get higher priority
                if last_synced:
                    try:
                        days_since_sync = (datetime.now(IST) - datetime.fromisoformat(last_synced)).days
                        priority += days_since_sync
                    except Exception:
                        priority += 30

                # Multiple sources increase priority
                priority += sources_count * 5

                refresh_list.append({
                    "page_id": page_id,
                    "priority": priority,
                    "sources_count": sources_count,
                    "last_synced": last_synced,
                })

            # Sort by priority
            refresh_list.sort(key=lambda x: x["priority"], reverse=True)
            return refresh_list

        except Exception as e:
            _LOG.error(f"Error getting refresh priority: {e}")
            return []

    def _persist(self) -> None:
        """Save sources metadata."""
        try:
            self.sources_metadata["last_checked"] = datetime.now(IST).isoformat()

            meta_dir = self.wiki_dir / ".meta"
            meta_dir.mkdir(exist_ok=True)

            self.sources_file.write_text(
                json.dumps(self.sources_metadata, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            _LOG.error(f"Error persisting sources metadata: {e}")


class RefreshScheduler:
    """Schedule and manage wiki page refreshes."""

    def __init__(self, wiki_type: str = "leading_practice", project_id: str | None = None):
        """Initialize refresh scheduler."""
        self.wiki_type = wiki_type
        self.project_id = project_id
        self.wiki_dir = self._get_wiki_dir()
        self.tracker = SourceTracker(wiki_type, project_id)

    def _get_wiki_dir(self) -> Path:
        """Get wiki directory."""
        if self.wiki_type == "leading_practice":
            return workspace_path("leading_practices") / "wiki"
        else:
            return workspace_path(self.project_id) / "wiki"

    def get_refresh_schedule(self, batch_size: int = 10) -> dict[str, Any]:
        """
        Get scheduled refreshes for the next period.

        Args:
            batch_size: Max pages per batch

        Returns:
            {
                "batch_size": int,
                "total_pages_to_refresh": int,
                "next_batch": [page_ids],
                "priority_scores": {page_id: score}
            }
        """
        try:
            priority_list = self.tracker.get_refresh_priority()

            next_batch = [p["page_id"] for p in priority_list[:batch_size]]
            priority_scores = {p["page_id"]: p["priority"] for p in priority_list}

            return {
                "status": "success",
                "wiki_type": self.wiki_type,
                "batch_size": batch_size,
                "total_pages_to_refresh": len(priority_list),
                "next_batch": next_batch,
                "priority_scores": priority_scores,
                "schedule_date": datetime.now(IST).isoformat(),
            }

        except Exception as e:
            _LOG.error(f"Error getting refresh schedule: {e}")
            return {"status": "error", "error": str(e)}

    def mark_page_synced(self, page_id: str) -> bool:
        """Mark a page as synced with its sources."""
        try:
            if page_id in self.tracker.sources_metadata["sources"]:
                self.tracker.sources_metadata["sources"][page_id]["last_synced"] = \
                    datetime.now(IST).isoformat()
                self.tracker._persist()
                return True
            return False
        except Exception as e:
            _LOG.error(f"Error marking page synced: {e}")
            return False


def check_wiki_source_freshness(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
) -> dict[str, Any]:
    """
    Check freshness of all sources in a wiki.

    Returns summary of which pages have changed sources.
    """
    try:
        tracker = SourceTracker(wiki_type, project_id)
        pages_with_changes = 0
        total_sources_changed = 0
        details = []

        for page_id in tracker.sources_metadata.get("sources", {}):
            freshness = tracker.check_source_freshness(page_id)
            if freshness.get("has_changes"):
                pages_with_changes += 1
                total_sources_changed += freshness.get("sources_changed", 0)
                details.append(freshness)

        return {
            "status": "success",
            "wiki_type": wiki_type,
            "pages_checked": len(tracker.sources_metadata.get("sources", {})),
            "pages_with_changes": pages_with_changes,
            "total_sources_changed": total_sources_changed,
            "details": details,
        }

    except Exception as e:
        _LOG.error(f"Error checking source freshness: {e}")
        return {"status": "error", "error": str(e)}


def get_refresh_schedule(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
    batch_size: int = 10,
) -> dict[str, Any]:
    """Get refresh schedule for a wiki."""
    scheduler = RefreshScheduler(wiki_type, project_id)
    return scheduler.get_refresh_schedule(batch_size)
