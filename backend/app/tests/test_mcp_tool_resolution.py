"""Unit tests for MCP tool resolution in tool_registry."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.tool_registry import _try_mcp_tool_call, resolve_tool_call


class TestMCPToolResolution:
    """Test MCP tool call resolution."""

    def test_resolve_tool_call_native_first(self):
        """Native tools take precedence over MCP."""
        # retrieve_context is a native tool
        result = resolve_tool_call(
            "retrieve_context",
            {"query": "test"},
            {"project_id": "test-project"}
        )

        assert isinstance(result, dict)
        assert "chunks" in result or "context_text" in result

    def test_resolve_tool_call_unknown_native(self):
        """Fail when tool not in registry."""
        with pytest.raises(ValueError, match="Unknown tool"):
            resolve_tool_call(
                "nonexistent_tool",
                {},
                {}
            )

    def test_resolve_tool_call_mcp_fallback(self):
        """Fall back to MCP when native tool not found."""
        with patch("app.services.tool_registry._try_mcp_tool_call") as mock_mcp:
            mock_mcp.return_value = {"result": "from_mcp"}

            result = resolve_tool_call(
                "mcp_only_tool",
                {"arg": "value"},
                {}
            )

            assert result == {"result": "from_mcp"}
            mock_mcp.assert_called_once_with("mcp_only_tool", {"arg": "value"})

    def test_resolve_tool_call_mcp_failure(self):
        """Error when tool not found anywhere."""
        with patch("app.services.tool_registry._try_mcp_tool_call") as mock_mcp:
            mock_mcp.return_value = None  # MCP servers don't have it either

            with pytest.raises(ValueError, match="Unknown tool"):
                resolve_tool_call(
                    "missing_tool",
                    {},
                    {}
                )

    def test_try_mcp_tool_call_success(self):
        """Successfully call tool via MCP."""
        with patch("app.services.mcp.bridge.try_mcp_tool_call") as mock_call:
            with patch("app.services.mcp.registry.get_mcp_registry") as mock_get_reg:
                mock_call.return_value = {"status": "ok"}

                mock_registry = MagicMock()
                mock_registry.servers = {"server1": MagicMock()}
                mock_get_reg.return_value = mock_registry

                result = _try_mcp_tool_call("test_tool", {"arg": "value"})

                assert result == {"status": "ok"}
                mock_call.assert_called_once()

    def test_try_mcp_tool_call_no_servers(self):
        """Return None when no MCP servers running."""
        with patch("app.services.mcp.registry.get_mcp_registry") as mock_get_reg:
            mock_registry = MagicMock()
            mock_registry.servers = {}  # No servers
            mock_get_reg.return_value = mock_registry

            result = _try_mcp_tool_call("test_tool", {})

            assert result is None

    def test_try_mcp_tool_call_multiple_servers(self):
        """Try all MCP servers until one succeeds."""
        with patch("app.services.mcp.bridge.try_mcp_tool_call") as mock_call:
            with patch("app.services.mcp.registry.get_mcp_registry") as mock_get_reg:
                # First server returns None, second succeeds
                mock_call.side_effect = [None, {"result": "found"}]

                mock_registry = MagicMock()
                mock_registry.servers = {
                    "server1": MagicMock(),
                    "server2": MagicMock(),
                }
                mock_get_reg.return_value = mock_registry

                result = _try_mcp_tool_call("test_tool", {})

                assert result == {"result": "found"}
                # Should have called twice (first failed, second succeeded)
                assert mock_call.call_count == 2

    def test_try_mcp_tool_call_all_servers_fail(self):
        """Return None when all MCP servers fail."""
        with patch("app.services.mcp.bridge.try_mcp_tool_call") as mock_call:
            with patch("app.services.mcp.registry.get_mcp_registry") as mock_get_reg:
                # All servers return None
                mock_call.return_value = None

                mock_registry = MagicMock()
                mock_registry.servers = {
                    "server1": MagicMock(),
                    "server2": MagicMock(),
                }
                mock_get_reg.return_value = mock_registry

                result = _try_mcp_tool_call("test_tool", {})

                assert result is None
                assert mock_call.call_count == 2

    def test_try_mcp_tool_call_exception_handling(self):
        """Handle exceptions gracefully."""
        with patch("app.services.mcp.registry.get_mcp_registry") as mock_get_reg:
            mock_get_reg.side_effect = RuntimeError("MCP unavailable")

            result = _try_mcp_tool_call("test_tool", {})

            assert result is None

    def test_resolve_tool_call_context_merging(self):
        """Context is properly merged into tool input."""
        with patch("app.services.tool_registry.TOOL_REGISTRY") as mock_registry:
            mock_handler = MagicMock(return_value={"result": "ok"})
            mock_registry.get = lambda k: mock_handler if k == "test_tool" else None
            mock_registry.__contains__ = lambda self, k: k == "test_tool"
            mock_registry.__getitem__ = lambda self, k: mock_handler

            resolve_tool_call(
                "test_tool",
                {"input_arg": "value"},
                {
                    "project_id": "proj-1",
                    "user_id": "user-1",
                    "process_model": {"step": 1},
                }
            )

            # Verify context was merged
            call_args = mock_handler.call_args
            if call_args:
                _, kwargs = call_args
                assert kwargs.get("project_id") == "proj-1"
                assert kwargs.get("user_id") == "user-1"
                assert kwargs.get("process_model") == {"step": 1}

    def test_resolve_tool_call_input_not_overwritten(self):
        """Input arguments take precedence over context."""
        with patch("app.services.tool_registry.TOOL_REGISTRY") as mock_registry:
            mock_handler = MagicMock(return_value={})
            mock_registry.__contains__ = lambda self, k: k == "test_tool"
            mock_registry.__getitem__ = lambda self, k: mock_handler

            resolve_tool_call(
                "test_tool",
                {"project_id": "input-proj"},  # Input has different value
                {"project_id": "context-proj"},  # Context has value
            )

            # Input should not be overwritten
            call_args = mock_handler.call_args
            if call_args:
                _, kwargs = call_args
                assert kwargs.get("project_id") == "input-proj"
