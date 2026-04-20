"""Teammate subprocess entrypoint.

Runs in a separate process spawned by TeammateExecutor.
Executes a single task using the subagent tool loop in isolation.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import traceback
from typing import Any, NoReturn

from app.claude_tools import run_subagent_tool_loop
from app.services.observability import increment

_LOG = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure logging for subprocess."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,  # Log to stderr so stdout stays for JSON output
    )


def handle_sigterm(signum: int, frame: Any) -> NoReturn:
    """Handle SIGTERM gracefully."""
    _LOG.info("Received SIGTERM, shutting down gracefully...")
    sys.exit(143)  # Standard exit code for SIGTERM


def main() -> None:
    """Main entrypoint for teammate subprocess.

    Expected stdin: JSON-serialized ProcessDocState
    Expected args: --teammate-id <id> --task-id <id>
    Output: JSON object with status and result

    Exit codes:
    - 0: Success
    - 1: Execution error
    - 143: Terminated by SIGTERM
    """
    setup_logging()
    signal.signal(signal.SIGTERM, handle_sigterm)

    # Parse arguments
    parser = argparse.ArgumentParser(description="Teammate subprocess worker")
    parser.add_argument("--teammate-id", required=True, help="Teammate ID")
    parser.add_argument("--task-id", required=True, help="Task ID")
    args = parser.parse_args()

    teammate_id = args.teammate_id
    task_id = args.task_id

    _LOG.info(f"Teammate {teammate_id} starting execution of task {task_id}")

    try:
        # Read state from stdin
        state_json = sys.stdin.read()
        if not state_json.strip():
            raise ValueError("No state provided on stdin")

        state = json.loads(state_json)
        _LOG.info(f"Loaded state for task {task_id}: {len(state)} keys")

        # Execute task using subagent tool loop
        _LOG.info(f"Running subagent tool loop for task {task_id}...")
        result = run_subagent_tool_loop(
            teammate_id=teammate_id,
            task_id=task_id,
            state=state,
            max_rounds=5,  # Configurable per task type
            max_tokens=50000,
        )

        # Package result
        output = {
            "status": "success",
            "task_id": task_id,
            "teammate_id": teammate_id,
            "result": result,
        }

        increment("teammate_task_success_total")
        _LOG.info(f"Task {task_id} completed successfully")

    except Exception as e:
        _LOG.error(f"Task {task_id} failed: {e}")
        _LOG.error(traceback.format_exc())

        output = {
            "status": "error",
            "task_id": task_id,
            "teammate_id": teammate_id,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }

        increment("teammate_task_error_total")
        sys.exit(1)

    # Output result as JSON to stdout
    print(json.dumps(output, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
