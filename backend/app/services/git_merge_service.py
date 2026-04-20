"""Git merge service for teammate worktree management.

Handles:
- Worktree creation and cleanup
- 3-way merge operations
- Conflict detection
- Merge conflict resolution
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)


@dataclass
class MergeConflict:
    """Represents a merge conflict."""

    file_path: str
    ours: str  # Content from main branch
    theirs: str  # Content from worktree branch
    base: str  # Content from merge base
    conflict_markers: str  # Raw conflict with markers

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "file_path": self.file_path,
            "ours_size": len(self.ours),
            "theirs_size": len(self.theirs),
            "base_size": len(self.base),
            "has_conflict": True,
        }


@dataclass
class MergeResult:
    """Result of a merge operation."""

    success: bool
    message: str
    conflicts: list[MergeConflict] = field(default_factory=list)
    merge_commit_sha: str | None = None
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "message": self.message,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "merge_commit_sha": self.merge_commit_sha,
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "conflict_count": len(self.conflicts),
        }


class GitMergeService:
    """Service for git merge operations."""

    def __init__(self, repo_root: Path):
        """Initialize merge service.

        Args:
            repo_root: Root directory of git repository
        """
        self.repo_root = Path(repo_root)
        self._verify_git_repo()

    def _verify_git_repo(self) -> None:
        """Verify that repo_root is a git repository."""
        git_dir = self.repo_root / ".git"
        if not git_dir.exists():
            raise ValueError(f"Not a git repository: {self.repo_root}")

    def _run_git(self, *args: str, check: bool = True) -> tuple[int, str, str]:
        """Run a git command in the repository.

        Args:
            *args: Git command arguments
            check: Raise exception on non-zero exit code

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        cmd = ["git", "-C", str(self.repo_root)] + list(args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if check and result.returncode != 0:
                _LOG.error(f"Git command failed: {' '.join(cmd)}")
                _LOG.error(f"stderr: {result.stderr}")
                raise RuntimeError(f"Git command failed: {result.stderr}")
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            raise RuntimeError("Git command timed out") from None

    def create_worktree(self, worktree_name: str, base_branch: str = "main") -> Path:
        """Create a new git worktree.

        Args:
            worktree_name: Name for the worktree (used in path)
            base_branch: Branch to base worktree on (default: main)

        Returns:
            Path to the worktree directory

        Raises:
            RuntimeError: If worktree creation fails
        """
        worktree_dir = self.repo_root / ".claude" / "worktrees" / worktree_name

        try:
            # Create .claude/worktrees directory if it doesn't exist
            worktree_dir.parent.mkdir(parents=True, exist_ok=True)

            # Create worktree
            self._run_git(
                "worktree",
                "add",
                str(worktree_dir),
                base_branch,
            )

            _LOG.info(f"Created worktree: {worktree_dir}")
            return worktree_dir

        except Exception as e:
            _LOG.error(f"Failed to create worktree: {e}")
            raise

    def remove_worktree(self, worktree_name: str, force: bool = False) -> None:
        """Remove a git worktree.

        Args:
            worktree_name: Name of the worktree to remove
            force: Force removal even if worktree is dirty

        Raises:
            RuntimeError: If worktree removal fails
        """
        worktree_dir = self.repo_root / ".claude" / "worktrees" / worktree_name

        try:
            if not worktree_dir.exists():
                _LOG.warning(f"Worktree does not exist: {worktree_dir}")
                return

            # Remove worktree
            args = ["worktree", "remove"]
            if force:
                args.append("--force")
            args.append(str(worktree_dir))

            self._run_git(*args)
            _LOG.info(f"Removed worktree: {worktree_dir}")

        except Exception as e:
            _LOG.error(f"Failed to remove worktree: {e}")
            raise

    def merge_worktree_to_main(self, worktree_name: str) -> MergeResult:
        """Merge a worktree back to main branch.

        Args:
            worktree_name: Name of the worktree to merge

        Returns:
            MergeResult with success status and conflict info
        """
        worktree_dir = self.repo_root / ".claude" / "worktrees" / worktree_name

        try:
            # Get current branch in worktree
            _, branch, _ = self._run_git(
                "-C",
                str(worktree_dir),
                "rev-parse",
                "--abbrev-ref",
                "HEAD",
            )
            branch = branch.strip()

            # Switch to main branch in main repo
            self._run_git("checkout", "main", check=False)

            # Attempt merge
            returncode, stdout, stderr = self._run_git(
                "merge",
                "--no-ff",
                f"{worktree_dir}",
                check=False,
            )

            if returncode == 0:
                # Merge successful
                _LOG.info(f"Successfully merged worktree {worktree_name}")

                # Get merge stats
                _, stats, _ = self._run_git("diff", "--stat", "HEAD~1..HEAD", check=False)

                return MergeResult(
                    success=True,
                    message=f"Successfully merged {branch} from worktree",
                    merge_commit_sha=stdout.strip().split()[-1] if stdout else None,
                )

            # Check for conflicts
            _, status, _ = self._run_git("status", check=False)

            if "conflict" in status.lower():
                conflicts = self._parse_conflicts()
                self._run_git("merge", "--abort", check=False)  # Abort merge
                return MergeResult(
                    success=False,
                    message=f"Merge conflict detected in {len(conflicts)} file(s)",
                    conflicts=conflicts,
                )

            # Other merge failure
            self._run_git("merge", "--abort", check=False)
            return MergeResult(
                success=False,
                message=stderr or "Merge failed for unknown reason",
            )

        except Exception as e:
            _LOG.error(f"Failed to merge worktree: {e}")
            self._run_git("merge", "--abort", check=False)  # Clean up on error
            return MergeResult(
                success=False,
                message=f"Merge operation failed: {str(e)}",
            )

    def _parse_conflicts(self) -> list[MergeConflict]:
        """Parse merge conflicts from git status.

        Returns:
            List of MergeConflict objects
        """
        conflicts = []

        try:
            # Get list of conflicted files
            _, diff_output, _ = self._run_git("diff", "--name-only", "--diff-filter=U", check=False)

            for file_path in diff_output.strip().split("\n"):
                if not file_path:
                    continue

                try:
                    # Get conflict markers
                    _, markers, _ = self._run_git("show", f":{file_path}", check=False)

                    # Get ours (main branch)
                    _, ours, _ = self._run_git("show", f":1:{file_path}", check=False)

                    # Get theirs (worktree branch)
                    _, theirs, _ = self._run_git("show", f":3:{file_path}", check=False)

                    # Get base
                    _, base, _ = self._run_git("show", f":2:{file_path}", check=False)

                    conflicts.append(
                        MergeConflict(
                            file_path=file_path,
                            ours=ours,
                            theirs=theirs,
                            base=base,
                            conflict_markers=markers,
                        )
                    )
                except Exception as e:
                    _LOG.warning(f"Failed to parse conflict for {file_path}: {e}")

            return conflicts

        except Exception as e:
            _LOG.error(f"Failed to parse conflicts: {e}")
            return []

    def resolve_conflict_ours(self, file_path: str) -> bool:
        """Resolve conflict by keeping ours (main) version.

        Args:
            file_path: Path to conflicted file

        Returns:
            True if successful
        """
        try:
            self._run_git("checkout", "--ours", file_path)
            self._run_git("add", file_path)
            _LOG.info(f"Resolved {file_path} using ours")
            return True
        except Exception as e:
            _LOG.error(f"Failed to resolve conflict for {file_path}: {e}")
            return False

    def resolve_conflict_theirs(self, file_path: str) -> bool:
        """Resolve conflict by keeping theirs (worktree) version.

        Args:
            file_path: Path to conflicted file

        Returns:
            True if successful
        """
        try:
            self._run_git("checkout", "--theirs", file_path)
            self._run_git("add", file_path)
            _LOG.info(f"Resolved {file_path} using theirs")
            return True
        except Exception as e:
            _LOG.error(f"Failed to resolve conflict for {file_path}: {e}")
            return False

    def complete_merge(self, message: str = "Merge teammate changes") -> bool:
        """Complete a merge after resolving conflicts.

        Args:
            message: Commit message for the merge

        Returns:
            True if successful
        """
        try:
            self._run_git("commit", "--no-edit", "-m", message)
            _LOG.info("Merge completed successfully")
            return True
        except Exception as e:
            _LOG.error(f"Failed to complete merge: {e}")
            return False
