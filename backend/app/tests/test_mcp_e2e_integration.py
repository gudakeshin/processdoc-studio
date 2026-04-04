"""End-to-end integration tests for MCP tool resolution pipeline."""

import asyncio
import json
import pytest
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.services.tool_registry import resolve_tool_call
from app.services.mcp.registry import MCPRegistry, MCPServerInstance, get_mcp_registry
from app.services.mcp.bridge import call_mcp_tool


class TestMCPEndToEndIntegration:
    """Test full MCP integration from resolve_tool_call through execution."""

    @pytest.fixture
    def mock_mcp_registry(self):
        """Create a mock MCP registry with a simulated running server."""
        registry = MCPRegistry()

        # Create a mock server that simulates a real MCP server
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None  # Process is alive
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()

        instance = MCPServerInstance(
            server_id="test-mcp-server",
            process=mock_process,
            config={"id": "test-mcp-server", "command": "test"},
        )

        registry.servers["test-mcp-server"] = instance
        return registry

    def test_resolve_tool_call_native_then_mcp_fallback(self, mock_mcp_registry):
        """Verify native tools are tried first, MCP as fallback."""
        with patch("app.services.mcp.bridge.try_mcp_tool_call") as mock_mcp_call:
            with patch("app.services.mcp.registry.get_mcp_registry") as mock_get_reg:
                mock_get_reg.return_value = mock_mcp_registry
                mock_mcp_call.return_value = {"status": "from_mcp"}

                # Test 1: Native tool should NOT call MCP
                result = resolve_tool_call(
                    "retrieve_context",
                    {"query": "test"},
                    {"project_id": "test-project"}
                )
                assert isinstance(result, dict)
                assert "chunks" in result  # Native tool response
                mock_mcp_call.assert_not_called()  # MCP not called for native tool

                # Test 2: Unknown tool should fall back to MCP
                mock_mcp_call.reset_mock()
                result = resolve_tool_call(
                    "external_tool",
                    {"arg": "value"},
                    {}
                )
                assert result == {"status": "from_mcp"}
                mock_mcp_call.assert_called_once()

    def test_resolve_tool_call_mcp_multiple_servers(self, mock_mcp_registry):
        """Verify tool resolution tries multiple MCP servers."""
        # Add second server
        mock_process2 = MagicMock()
        mock_process2.pid = 12346
        mock_process2.poll.return_value = None

        instance2 = MCPServerInstance(
            server_id="test-mcp-server-2",
            process=mock_process2,
            config={"id": "test-mcp-server-2", "command": "test"},
        )
        mock_mcp_registry.servers["test-mcp-server-2"] = instance2

        with patch("app.services.mcp.bridge.try_mcp_tool_call") as mock_mcp_call:
            with patch("app.services.mcp.registry.get_mcp_registry") as mock_get_reg:
                mock_get_reg.return_value = mock_mcp_registry
                # First server returns None, second returns result
                mock_mcp_call.side_effect = [None, {"status": "from_server_2"}]

                result = resolve_tool_call(
                    "external_tool",
                    {"arg": "value"},
                    {}
                )

                assert result == {"status": "from_server_2"}
                # Should have called both servers
                assert mock_mcp_call.call_count == 2

    def test_resolve_tool_call_context_propagation(self, mock_mcp_registry):
        """Verify context is correctly merged into tool input."""
        with patch("app.services.tool_registry.TOOL_REGISTRY") as mock_registry:
            mock_handler = MagicMock(return_value={"result": "ok"})
            mock_registry.__contains__ = lambda self, k: k == "test_tool"
            mock_registry.__getitem__ = lambda self, k: mock_handler

            resolve_tool_call(
                "test_tool",
                {"input_arg": "input_value"},
                {
                    "project_id": "proj-123",
                    "user_id": "user-456",
                    "process_model": {"step": 1},
                }
            )

            # Verify context was merged
            call_kwargs = mock_handler.call_args[1]
            assert call_kwargs.get("input_arg") == "input_value"
            assert call_kwargs.get("project_id") == "proj-123"
            assert call_kwargs.get("user_id") == "user-456"
            assert call_kwargs.get("process_model") == {"step": 1}

    @pytest.mark.asyncio
    async def test_mcp_tool_call_json_rpc_message_format(self, mock_mcp_registry):
        """Verify JSON-RPC 2.0 message format in tool calls."""
        response_json = json.dumps({
            "jsonrpc": "2.0",
            "result": {"data": "test_result"},
            "id": 0,
        })

        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            mock_get_reg.return_value = mock_mcp_registry
            instance = mock_mcp_registry.servers["test-mcp-server"]
            instance.process.stdout.readline.return_value = response_json.encode()

            result = await call_mcp_tool(
                "test-mcp-server",
                "custom_tool",
                {"param": "value"}
            )

            assert result == {"data": "test_result"}

            # Verify stdin.write was called with properly formatted JSON-RPC
            write_call = instance.process.stdin.write.call_args[0][0]
            message_bytes = write_call.encode() if isinstance(write_call, str) else write_call
            message_text = message_bytes.decode('utf-8')

            # Parse the JSON-RPC message
            message = json.loads(message_text.split('\n')[0])  # Line-delimited JSON
            assert message["jsonrpc"] == "2.0"
            assert message["method"] == "tools/call"
            assert message["params"]["name"] == "custom_tool"
            assert message["params"]["arguments"] == {"param": "value"}
            assert isinstance(message["id"], int)

    def test_resolve_tool_call_missing_tool_error(self):
        """Verify error when tool not found in native or MCP registries."""
        with patch("app.services.mcp.bridge.try_mcp_tool_call") as mock_mcp_call:
            mock_mcp_call.return_value = None  # MCP doesn't have it

            with pytest.raises(ValueError, match="Unknown tool.*missing_tool"):
                resolve_tool_call("missing_tool", {}, {})

    @pytest.mark.asyncio
    async def test_mcp_server_error_response_handling(self, mock_mcp_registry):
        """Verify proper handling of MCP error responses."""
        error_response = json.dumps({
            "jsonrpc": "2.0",
            "error": {
                "code": -32601,
                "message": "Method not found"
            },
            "id": 0,
        })

        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            mock_get_reg.return_value = mock_mcp_registry
            instance = mock_mcp_registry.servers["test-mcp-server"]
            instance.process.stdout.readline.return_value = error_response.encode()

            result = await call_mcp_tool(
                "test-mcp-server",
                "unknown_tool",
                {}
            )

            # Should return None on error response
            assert result is None

    def test_tool_input_precedence_over_context(self):
        """Verify input arguments take precedence over context values."""
        with patch("app.services.tool_registry.TOOL_REGISTRY") as mock_registry:
            mock_handler = MagicMock(return_value={})
            mock_registry.__contains__ = lambda self, k: k == "test_tool"
            mock_registry.__getitem__ = lambda self, k: mock_handler

            resolve_tool_call(
                "test_tool",
                {"project_id": "input_proj"},  # Input has value
                {"project_id": "context_proj"},  # Context also has value
            )

            call_kwargs = mock_handler.call_args[1]
            # Input should win
            assert call_kwargs.get("project_id") == "input_proj"

    def test_tool_resolution_logging(self, mock_mcp_registry):
        """Verify tool resolution is logged for debugging."""
        with patch("app.services.mcp.bridge.try_mcp_tool_call") as mock_mcp_call:
            with patch("app.services.mcp.registry.get_mcp_registry") as mock_get_reg:
                with patch("app.services.tool_registry._LOG") as mock_log:
                    mock_get_reg.return_value = mock_mcp_registry
                    mock_mcp_call.return_value = {"status": "ok"}

                    resolve_tool_call("external_tool", {}, {})

                    # Should log the resolution
                    assert mock_log.info.called or mock_log.debug.called

    @pytest.mark.asyncio
    async def test_mcp_tool_call_timeout_handling(self, mock_mcp_registry):
        """Verify timeout is properly handled in MCP tool calls."""
        with patch("app.services.mcp.bridge.get_mcp_registry") as mock_get_reg:
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                mock_get_reg.return_value = mock_mcp_registry

                result = await call_mcp_tool(
                    "test-mcp-server",
                    "slow_tool",
                    {},
                    timeout_sec=0.5
                )

                assert result is None

    def test_resolve_tool_call_with_empty_context(self):
        """Verify tool resolution works with empty context."""
        with patch("app.services.tool_registry.TOOL_REGISTRY") as mock_registry:
            mock_handler = MagicMock(return_value={"result": "ok"})
            mock_registry.__contains__ = lambda self, k: k == "test_tool"
            mock_registry.__getitem__ = lambda self, k: mock_handler

            result = resolve_tool_call("test_tool", {"arg": "val"}, {})

            assert result == {"result": "ok"}
            call_kwargs = mock_handler.call_args[1]
            assert call_kwargs["arg"] == "val"
            # Context fields should not be present if not in context
            assert "project_id" not in call_kwargs or call_kwargs.get("project_id") is None

    def test_resolve_tool_call_with_none_context_values(self):
        """Verify None values in context are handled correctly."""
        with patch("app.services.tool_registry.TOOL_REGISTRY") as mock_registry:
            mock_handler = MagicMock(return_value={})
            mock_registry.__contains__ = lambda self, k: k == "test_tool"
            mock_registry.__getitem__ = lambda self, k: mock_handler

            resolve_tool_call(
                "test_tool",
                {"arg": "val"},
                {"project_id": None, "user_id": "user-1"}
            )

            call_kwargs = mock_handler.call_args[1]
            # None values should not be added
            assert call_kwargs.get("project_id") is None
            # Non-None values should be added
            assert call_kwargs.get("user_id") == "user-1"
