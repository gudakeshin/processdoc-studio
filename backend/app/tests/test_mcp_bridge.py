"""Unit tests for MCP bridge module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.mcp.bridge import call_mcp_tool, try_mcp_tool_call
from app.services.mcp.registry import MCPRegistry, MCPServerInstance


class TestMCPBridge:
    """Test MCP bridge tool calling."""

    @pytest.fixture
    def mock_registry(self):
        """Create a mock registry with a running server."""
        registry = MCPRegistry()

        # Create a mock server instance
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None  # Alive
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()

        instance = MCPServerInstance(
            server_id="test-server",
            process=mock_process,
            config={"id": "test-server"},
        )

        registry.servers["test-server"] = instance
        return registry

    @pytest.mark.asyncio
    async def test_call_mcp_tool_server_not_running(self):
        """Fail gracefully when server is not running."""
        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            mock_registry = MagicMock()
            mock_registry.servers = {}  # No servers
            mock_get_reg.return_value = mock_registry

            result = await call_mcp_tool(
                "nonexistent",
                "test_tool",
                {"arg": "value"}
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_call_mcp_tool_success(self, mock_registry):
        """Successfully call an MCP tool and get result."""
        # Mock the response
        response_json = json.dumps({
            "jsonrpc": "2.0",
            "result": {"status": "ok", "data": [1, 2, 3]},
            "id": 0,
        })

        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            mock_get_reg.return_value = mock_registry

            # Mock stdout.readline()
            mock_registry.servers["test-server"].process.stdout.readline.return_value = (
                response_json.encode("utf-8")
            )

            result = await call_mcp_tool(
                "test-server",
                "list_tools",
                {}
            )

            assert result is not None
            assert result["status"] == "ok"
            assert result["data"] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_call_mcp_tool_error_response(self, mock_registry):
        """Handle MCP error responses."""
        error_response = json.dumps({
            "jsonrpc": "2.0",
            "error": {
                "code": -32600,
                "message": "Invalid Request"
            },
            "id": 0,
        })

        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            mock_get_reg.return_value = mock_registry
            mock_registry.servers["test-server"].process.stdout.readline.return_value = (
                error_response.encode("utf-8")
            )

            result = await call_mcp_tool(
                "test-server",
                "bad_tool",
                {}
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_call_mcp_tool_timeout(self, mock_registry):
        """Handle timeout on MCP tool call."""
        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            with patch("asyncio.wait_for") as mock_wait_for:
                mock_get_reg.return_value = mock_registry
                mock_wait_for.side_effect = TimeoutError()

                result = await call_mcp_tool(
                    "test-server",
                    "slow_tool",
                    {},
                    timeout_sec=1.0
                )

                assert result is None

    @pytest.mark.asyncio
    async def test_call_mcp_tool_empty_response(self, mock_registry):
        """Handle empty response from server."""
        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            mock_get_reg.return_value = mock_registry
            mock_registry.servers["test-server"].process.stdout.readline.return_value = b""

            result = await call_mcp_tool(
                "test-server",
                "test_tool",
                {}
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_call_mcp_tool_invalid_json(self, mock_registry):
        """Handle invalid JSON response from server."""
        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            mock_get_reg.return_value = mock_registry
            mock_registry.servers["test-server"].process.stdout.readline.return_value = (
                b"{ invalid json }"
            )

            result = await call_mcp_tool(
                "test-server",
                "test_tool",
                {}
            )

            # Should handle gracefully
            assert result is None

    @pytest.mark.asyncio
    async def test_call_mcp_tool_broken_pipe(self, mock_registry):
        """Handle broken pipe on stdin write."""
        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            mock_get_reg.return_value = mock_registry

            # Make stdin.write() raise BrokenPipeError
            mock_registry.servers["test-server"].process.stdin.write.side_effect = (
                BrokenPipeError()
            )

            result = await call_mcp_tool(
                "test-server",
                "test_tool",
                {"arg": "value"}
            )

            assert result is None

    def test_try_mcp_tool_call_sync_wrapper(self):
        """Test synchronous wrapper function."""
        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.is_running.return_value = False
            mock_loop.run_until_complete.return_value = {"result": "ok"}
            mock_get_loop.return_value = mock_loop

            result = try_mcp_tool_call(
                "test-server",
                "test_tool",
                {"arg": "value"}
            )

            assert result == {"result": "ok"}
            mock_loop.run_until_complete.assert_called_once()

    def test_try_mcp_tool_call_no_loop(self):
        """Handle case where no event loop exists."""
        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_get_loop.side_effect = RuntimeError("No running event loop")

            result = try_mcp_tool_call(
                "test-server",
                "test_tool",
                {"arg": "value"}
            )

            assert result is None

    def test_try_mcp_tool_call_loop_already_running(self):
        """Fail gracefully when loop is already running."""
        with patch("asyncio.get_event_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.is_running.return_value = True  # Already running
            mock_get_loop.return_value = mock_loop

            result = try_mcp_tool_call(
                "test-server",
                "test_tool",
                {"arg": "value"}
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_call_mcp_tool_request_counter_increment(self, mock_registry):
        """Verify request counter increments."""
        response_json = json.dumps({
            "jsonrpc": "2.0",
            "result": {"ok": True},
            "id": 0,
        })

        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            mock_get_reg.return_value = mock_registry
            instance = mock_registry.servers["test-server"]

            initial_counter = instance.request_counter
            mock_registry.servers["test-server"].process.stdout.readline.return_value = (
                response_json.encode("utf-8")
            )

            await call_mcp_tool("test-server", "test_tool", {})

            # Counter should increment
            assert instance.request_counter == initial_counter + 1

    @pytest.mark.asyncio
    async def test_call_mcp_tool_writes_to_stdin(self, mock_registry):
        """Verify tool call writes to stdin."""
        response_json = json.dumps({
            "jsonrpc": "2.0",
            "result": {"ok": True},
            "id": 0,
        })

        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            mock_get_reg.return_value = mock_registry
            mock_registry.servers["test-server"].process.stdout.readline.return_value = (
                response_json.encode("utf-8")
            )

            await call_mcp_tool(
                "test-server",
                "test_tool",
                {"key": "value"}
            )

            # Should have written to stdin
            mock_registry.servers["test-server"].process.stdin.write.assert_called_once()
            mock_registry.servers["test-server"].process.stdin.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_mcp_tool_multiple_calls(self, mock_registry):
        """Test multiple consecutive calls."""
        response_json = json.dumps({
            "jsonrpc": "2.0",
            "result": {"ok": True},
            "id": None
        })

        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            mock_get_reg.return_value = mock_registry
            mock_registry.servers["test-server"].process.stdout.readline.return_value = (
                response_json.encode("utf-8")
            )

            # Make multiple calls
            result1 = await call_mcp_tool("test-server", "tool1", {})
            result2 = await call_mcp_tool("test-server", "tool2", {})

            assert result1 is not None
            assert result2 is not None
