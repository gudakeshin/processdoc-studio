"""MCP tool call routing and stdio communication."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.services.mcp.protocol import (
    format_json_rpc_request,
    parse_json_rpc_response,
)
from app.services.mcp.registry import get_mcp_registry

logger = logging.getLogger(__name__)


async def call_mcp_tool(
    server_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    timeout_sec: float = 10.0,
) -> Any | None:
    """
    Call a tool on an MCP server via stdio, return result or None on failure.

    Args:
        server_id: ID of the MCP server (must be running)
        tool_name: Name of the tool to call
        tool_input: Input parameters for the tool
        timeout_sec: Timeout for the call in seconds

    Returns:
        Tool result or None if call failed/timed out
    """
    registry = get_mcp_registry()
    instance = registry.servers.get(server_id)

    if not instance:
        logger.warning(f"MCP server {server_id} not running")
        return None

    try:
        # Craft tool call as JSON-RPC 2.0 request
        request_id = instance.request_counter
        instance.request_counter += 1

        # Format message
        msg = format_json_rpc_request(
            method="tools/call",
            params={
                "name": tool_name,
                "arguments": tool_input,
            },
            request_id=request_id,
        )

        # The underlying Popen pipes are blocking, so both directions run in the
        # default executor and can never stall the event loop.
        loop = asyncio.get_event_loop()

        if instance.process.stdin:
            def write_request() -> bool:
                try:
                    instance.process.stdin.write(msg.encode("utf-8"))
                    instance.process.stdin.flush()
                    return True
                except BrokenPipeError:
                    return False

            if not await loop.run_in_executor(None, write_request):
                logger.error(f"MCP server {server_id} stdin broken")
                return None

        # Read response from stdout with timeout (also off the event loop).

        def read_response():
            try:
                if instance.process.stdout:
                    line = instance.process.stdout.readline()
                    if not line:
                        return None
                    return line.decode("utf-8").strip()
                return None
            except Exception as e:
                logger.error(f"Failed to read from MCP stdout: {e}")
                return None

        try:
            response_str = await asyncio.wait_for(
                loop.run_in_executor(None, read_response),
                timeout=timeout_sec,
            )
        except TimeoutError:
            logger.error(f"MCP tool call timeout for {tool_name}")
            return None

        if not response_str:
            logger.error(f"Empty response from MCP server {server_id}")
            return None

        # Parse JSON-RPC response
        json.loads(response_str)
        response = parse_json_rpc_response(response_str.encode())

        if response is None:
            logger.error(f"Invalid JSON-RPC response from MCP server {server_id}")
            return None

        if response.error:
            logger.error(
                f"MCP tool call error: {response.error.get('message', 'unknown')}"
            )
            return None

        return response.result

    except TimeoutError:
        logger.error(f"MCP tool call timeout for {tool_name}")
        return None
    except Exception as e:
        logger.error(f"MCP tool call failed: {e}")
        return None


def try_mcp_tool_call(
    server_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
) -> Any | None:
    """
    Synchronous wrapper for MCP tool call.

    Returns None if the call cannot be made synchronously (e.g., inside async context).
    """
    try:
        loop = asyncio.get_event_loop()

        # Check if we're already in an async context
        if loop.is_running():
            logger.debug(
                "Cannot call MCP from running async context, use call_mcp_tool() instead"
            )
            return None

        # Run async call synchronously
        return loop.run_until_complete(
            call_mcp_tool(server_id, tool_name, tool_input)
        )
    except RuntimeError as e:
        # No event loop in current thread
        logger.debug(f"No event loop available for MCP tool call: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to call MCP tool synchronously: {e}")
        return None
