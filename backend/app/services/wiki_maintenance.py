"""
Wiki maintenance service for autonomous wiki evolution.

Implements autonomous maintenance following Karpathy's Second Brain principles:
- Auto-fix low-risk linting issues
- Detect and merge duplicates
- Track and refresh stale pages
- Generate synthesis pages for gaps
- Evolve wiki schema based on patterns

This runs as a scheduled background task, making the LLM an active "research librarian"
that continuously refines and evolves the wiki without user intervention.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.services import wiki_lint
from app.services.storage import workspace_path
from app.services.wiki_operations import NonTransientError

_LOG = logging.getLogger(__name__)


class WikiMaintenanceManager:
    """Autonomous wiki maintenance orchestrator."""

    def __init__(self, wiki_type: str = "leading_practice", project_id: str | None = None):
        """
        Initialize maintenance manager.

        Args:
            wiki_type: "leading_practice" or "project"
            project_id: Required if wiki_type is "project"
        """
        self.wiki_type = wiki_type
        self.project_id = project_id
        self.wiki_dir = self._get_wiki_dir()
        self.config = self._load_config()
        self.maintenance_log = self._get_maintenance_log_path()

    def _get_wiki_dir(self) -> Path:
        """Get the wiki directory path."""
        if self.wiki_type == "leading_practice":
            return workspace_path("leading_practices") / "wiki"
        else:
            return workspace_path(self.project_id) / "wiki"

    def _get_maintenance_log_path(self) -> Path:
        """Get the maintenance log file path."""
        return self.wiki_dir / "maintenance.log"

    def _load_config(self) -> dict[str, Any]:
        """Load maintenance configuration from schema."""
        schema_path = self.wiki_dir / "SCHEMA.md"
        if not schema_path.exists():
            return self._default_config()

        try:
            import re
            content = schema_path.read_text(encoding="utf-8")
            config_match = re.search(
                r"## Maintenance Rules\s*```yaml\s*(.*?)\s*```",
                content,
                re.DOTALL
            )
            if config_match:
                try:
                    import yaml
                    return yaml.safe_load(config_match.group(1)) or self._default_config()
                except Exception:
                    return self._default_config()
        except Exception as e:
            _LOG.warning(f"Error loading maintenance config: {e}")

        return self._default_config()

    def _default_config(self) -> dict[str, Any]:
        """Default maintenance configuration."""
        return {
            "auto_fix_confidence": 0.85,
            "stale_days": 30,
            "duplicate_confidence": 0.85,
            "synthesis_gap_threshold": 3,
            "max_maintenance_pages": 50,  # Limit batch size
        }

    def _log_maintenance(self, action: str, details: dict[str, Any]) -> None:
        """Log maintenance action."""
        try:
            log_entry = {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "details": details,
            }

            log_data = []
            if self.maintenance_log.exists():
                try:
                    log_data = json.loads(self.maintenance_log.read_text(encoding="utf-8"))
                except Exception:
                    log_data = []

            log_data.append(log_entry)
            # Keep last 1000 entries
            log_data = log_data[-1000:]

            self.maintenance_log.write_text(
                json.dumps(log_data, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            _LOG.error(f"Error logging maintenance: {e}")

    def run_maintenance(self, auto_fix: bool = True) -> dict[str, Any]:
        """
        Run full maintenance cycle.

        Args:
            auto_fix: Whether to auto-fix low-risk issues

        Returns:
            Summary of maintenance results
        """
        _LOG.info(f"Starting maintenance for {self.wiki_type} wiki")

        results = {
            "timestamp": datetime.now(UTC).isoformat(),
            "wiki_type": self.wiki_type,
            "project_id": self.project_id,
            "checks": {},
        }

        try:
            # 1. Fix orphaned pages
            results["checks"]["orphans"] = self._fix_orphaned_pages(auto_fix)

            # 2. Fix broken links
            results["checks"]["broken_links"] = self._fix_broken_links(auto_fix)

            # 3. Detect and merge duplicates
            results["checks"]["duplicates"] = self._handle_duplicates(auto_fix)

            # 4. Detect stale pages
            results["checks"]["stale_pages"] = self._detect_stale_pages(auto_fix)

            # 5. Generate synthesis pages for gaps
            results["checks"]["synthesis"] = self._generate_synthesis_pages(auto_fix)

            results["status"] = "success"

        except NonTransientError as e:
            _LOG.error(f"Maintenance failed (non-transient): {e}")
            results["status"] = "failed"
            results["error"] = str(e)
        except Exception as e:
            _LOG.error(f"Maintenance failed: {e}", exc_info=True)
            results["status"] = "failed"
            results["error"] = str(e)

        self._log_maintenance("full_maintenance", results)
        return results

    def _fix_orphaned_pages(self, auto_fix: bool = True) -> dict[str, Any]:
        """Detect and fix orphaned pages."""
        try:
            issues = wiki_lint._check_orphaned_pages(self.wiki_type, self.project_id)
            orphans = [i for i in issues if i["type"] == "orphan_page"]

            if auto_fix and orphans:
                fixed = self._auto_fix_orphans(orphans)
                return {
                    "found": len(orphans),
                    "fixed": fixed,
                    "status": "fixed" if fixed > 0 else "reviewed",
                }

            return {
                "found": len(orphans),
                "fixed": 0,
                "status": "reviewed",
            }
        except Exception as e:
            _LOG.error(f"Error fixing orphaned pages: {e}")
            return {"error": str(e), "status": "failed"}

    def _auto_fix_orphans(self, orphans: list[dict[str, Any]]) -> int:
        """
        Auto-fix orphaned pages by deleting or merging.

        Returns count of fixed pages.
        """
        fixed = 0
        for orphan in orphans[:self.config["max_maintenance_pages"]]:
            page_id = orphan["page_id"]
            page_path = self.wiki_dir / f"{page_id}.md"

            try:
                if page_path.exists():
                    # Mark as archived instead of deleting
                    content = page_path.read_text(encoding="utf-8")
                    content = content.replace(
                        "status: draft",
                        "status: archived"
                    ).replace(
                        "status: published",
                        "status: archived"
                    )
                    if "status: archived" not in content:
                        content = "---\nstatus: archived\n---\n\n" + content
                    page_path.write_text(content, encoding="utf-8")
                    fixed += 1
                    _LOG.info(f"Archived orphaned page: {page_id}")
            except Exception as e:
                _LOG.warning(f"Error archiving orphan {page_id}: {e}")

        return fixed

    def _fix_broken_links(self, auto_fix: bool = True) -> dict[str, Any]:
        """Detect and fix broken links."""
        try:
            issues = wiki_lint._check_broken_links(self.wiki_type, self.project_id)
            broken = [i for i in issues if i["type"] == "broken_link"]

            if auto_fix and broken:
                fixed = self._auto_fix_broken_links(broken)
                return {
                    "found": len(broken),
                    "fixed": fixed,
                    "status": "fixed" if fixed > 0 else "reviewed",
                }

            return {
                "found": len(broken),
                "fixed": 0,
                "status": "reviewed",
            }
        except Exception as e:
            _LOG.error(f"Error fixing broken links: {e}")
            return {"error": str(e), "status": "failed"}

    def _auto_fix_broken_links(self, broken: list[dict[str, Any]]) -> int:
        """
        Auto-fix broken links by removing or correcting.

        Returns count of fixed issues.
        """
        fixed = 0
        for issue in broken[:self.config["max_maintenance_pages"]]:
            page_id = issue["page_id"]
            target_text = issue["target"]
            page_path = self.wiki_dir / f"{page_id}.md"

            try:
                if page_path.exists():
                    content = page_path.read_text(encoding="utf-8")
                    # Remove broken link, replace with text
                    new_content = content.replace(f"[[{target_text}]]", target_text)
                    if new_content != content:
                        page_path.write_text(new_content, encoding="utf-8")
                        fixed += 1
                        _LOG.info(f"Fixed broken link in {page_id}: {target_text}")
            except Exception as e:
                _LOG.warning(f"Error fixing link in {page_id}: {e}")

        return fixed

    def _handle_duplicates(self, auto_fix: bool = True) -> dict[str, Any]:
        """Detect and handle duplicate pages."""
        try:
            from app.services.wiki_dedup import DuplicateDetector
            detector = DuplicateDetector(self.wiki_type, self.project_id)
            candidates = detector.find_duplicates(confidence=self.config["duplicate_confidence"])

            if auto_fix and candidates:
                merged = detector.auto_merge_duplicates(candidates)
                return {
                    "found": len(candidates),
                    "merged": merged,
                    "status": "merged" if merged > 0 else "reviewed",
                }

            return {
                "found": len(candidates),
                "merged": 0,
                "status": "reviewed",
            }
        except ImportError:
            _LOG.warning("wiki_dedup not yet available")
            return {"status": "skipped", "reason": "dedup_not_available"}
        except Exception as e:
            _LOG.error(f"Error handling duplicates: {e}")
            return {"error": str(e), "status": "failed"}

    def _detect_stale_pages(self, auto_fix: bool = True) -> dict[str, Any]:
        """Detect pages that haven't been updated in a while."""
        try:
            stale_pages = []
            now = datetime.now(UTC)
            stale_threshold = now - timedelta(days=self.config["stale_days"])

            for md_file in self.wiki_dir.glob("*.md"):
                if md_file.name in ("index.md", "log.md", "maintenance.log"):
                    continue

                try:
                    content = md_file.read_text(encoding="utf-8")
                    # Extract last_updated from frontmatter
                    import re
                    updated_match = re.search(
                        r"^last_updated:\s*['\"]?([^'\"\\n]+)",
                        content,
                        re.MULTILINE
                    )

                    if updated_match:
                        updated_str = updated_match.group(1)
                        try:
                            updated = datetime.fromisoformat(updated_str)
                            if updated < stale_threshold:
                                stale_pages.append({
                                    "page_id": md_file.stem,
                                    "last_updated": updated_str,
                                    "days_old": (now - updated).days,
                                })
                        except ValueError:
                            pass
                except Exception:  # noqa: S110 — best-effort, non-fatal
                    pass

            return {
                "found": len(stale_pages),
                "stale_pages": stale_pages[:10],  # Show top 10
                "status": "detected",
            }
        except Exception as e:
            _LOG.error(f"Error detecting stale pages: {e}")
            return {"error": str(e), "status": "failed"}

    def _generate_synthesis_pages(self, auto_fix: bool = True) -> dict[str, Any]:
        """Generate synthesis pages for identified gaps."""
        try:
            # TODO: Implement once Phase 5 (synthesis engine) is done
            return {
                "found": 0,
                "generated": 0,
                "status": "skipped",
                "reason": "synthesis_not_yet_implemented",
            }
        except Exception as e:
            _LOG.error(f"Error generating synthesis pages: {e}")
            return {"error": str(e), "status": "failed"}

    def get_maintenance_status(self) -> dict[str, Any]:
        """Get recent maintenance status."""
        try:
            if not self.maintenance_log.exists():
                return {"status": "no_maintenance_yet", "wiki_type": self.wiki_type}

            log_data = json.loads(self.maintenance_log.read_text(encoding="utf-8"))
            last_10 = log_data[-10:] if log_data else []

            return {
                "wiki_type": self.wiki_type,
                "project_id": self.project_id,
                "total_runs": len(log_data),
                "last_run": log_data[-1]["timestamp"] if log_data else None,
                "recent_runs": last_10,
            }
        except Exception as e:
            _LOG.error(f"Error getting maintenance status: {e}")
            return {"error": str(e), "status": "failed"}


# Convenience functions for API integration
def run_wiki_maintenance(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
    auto_fix: bool = True,
) -> dict[str, Any]:
    """
    Run wiki maintenance.

    Args:
        wiki_type: "leading_practice" or "project"
        project_id: Required if wiki_type is "project"
        auto_fix: Whether to auto-fix low-risk issues

    Returns:
        Maintenance results
    """
    manager = WikiMaintenanceManager(wiki_type, project_id)
    return manager.run_maintenance(auto_fix=auto_fix)


def get_maintenance_status(
    wiki_type: str = "leading_practice",
    project_id: str | None = None,
) -> dict[str, Any]:
    """Get maintenance status for a wiki."""
    manager = WikiMaintenanceManager(wiki_type, project_id)
    return manager.get_maintenance_status()
