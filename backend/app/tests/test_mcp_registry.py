"""Unit tests for MCP registry module."""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.mcp.registry import (
    MCPRegistry,
    MCPServerInstance,
    get_mcp_registry,
)


class TestMCPRegistry:
    """Test MCP registry functionality."""

    @pytest.fixture
    def registry(self):
        """Create a fresh registry for each test."""
        return MCPRegistry()

    @pytest.fixture
    def sample_config(self, tmp_path):
        """Create a sample MCP servers config file."""
        config = [
            {
                "id": "test-server",
                "command": "python",
                "args": ["-m", "mcp_test_server"],
                "env": {"TEST_VAR": "test_value"},
            },
            {
                "id": "onedrive",
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-onedrive"],
                "env": {"ONEDRIVE_TENANT_ID": "${ONEDRIVE_TENANT_ID}"},
            },
        ]

        config_file = tmp_path / "mcp_servers.json"
        config_file.write_text(json.dumps(config))
        return config_file

    def test_load_configs_valid(self, registry, sample_config):
        """Load valid MCP configs."""
        registry.load_configs(sample_config)

        assert len(registry.configs) == 2
        assert "test-server" in registry.configs
        assert "onedrive" in registry.configs
        assert registry.configs["test-server"]["command"] == "python"

    def test_load_configs_missing_file(self, registry, tmp_path):
        """Handle missing config file gracefully."""
        missing_file = tmp_path / "missing.json"
        registry.load_configs(missing_file)

        assert len(registry.configs) == 0

    def test_load_configs_invalid_json(self, registry, tmp_path):
        """Handle invalid JSON gracefully."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ invalid json }")
        registry.load_configs(bad_file)

        assert len(registry.configs) == 0

    def test_load_configs_not_array(self, registry, tmp_path):
        """Handle non-array JSON gracefully."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text('{"id": "test"}')
        registry.load_configs(bad_file)

        assert len(registry.configs) == 0

    def test_load_configs_missing_id(self, registry, tmp_path):
        """Skip configs without id field."""
        config = [
            {"command": "test"},  # Missing id
            {"id": "valid", "command": "test"},  # Valid
        ]
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))
        registry.load_configs(config_file)

        assert len(registry.configs) == 1
        assert "valid" in registry.configs

    @pytest.mark.asyncio
    async def test_start_server_not_configured(self, registry):
        """Fail gracefully when starting unconfigured server."""
        result = await registry.start_server("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_start_server_missing_command(self, registry):
        """Fail when config lacks command."""
        registry.configs["bad"] = {"id": "bad"}  # No command
        result = await registry.start_server("bad")

        assert result is None

    @pytest.mark.asyncio
    async def test_start_server_success(self, registry, sample_config):
        """Successfully spawn a server."""
        registry.load_configs(sample_config)

        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.poll.return_value = None
            mock_popen.return_value = mock_process

            result = await registry.start_server("test-server")

            assert result is not None
            assert result.server_id == "test-server"
            assert result.process == mock_process
            assert "test-server" in registry.servers

    @pytest.mark.asyncio
    async def test_health_check_alive(self, registry, sample_config):
        """Health check returns True for alive server."""
        registry.load_configs(sample_config)

        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.poll.return_value = None  # Alive
            mock_popen.return_value = mock_process

            await registry.start_server("test-server")
            alive = await registry.health_check("test-server")

            assert alive is True

    @pytest.mark.asyncio
    async def test_health_check_dead(self, registry, sample_config):
        """Health check returns False for dead server."""
        registry.load_configs(sample_config)

        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.poll.return_value = 1  # Process has exited
            mock_popen.return_value = mock_process

            await registry.start_server("test-server")
            alive = await registry.health_check("test-server")

            assert alive is False

    @pytest.mark.asyncio
    async def test_health_check_nonexistent(self, registry):
        """Health check returns False for nonexistent server."""
        alive = await registry.health_check("nonexistent")

        assert alive is False

    @pytest.mark.asyncio
    async def test_stop_server_graceful(self, registry, sample_config):
        """Stop server gracefully."""
        registry.load_configs(sample_config)

        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.poll.return_value = None
            mock_popen.return_value = mock_process

            await registry.start_server("test-server")
            assert "test-server" in registry.servers

            await registry.stop_server("test-server")

            # Should call terminate
            mock_process.terminate.assert_called_once()
            assert "test-server" not in registry.servers

    @pytest.mark.asyncio
    async def test_startup_all(self, registry, sample_config):
        """Start all configured servers."""
        registry.load_configs(sample_config)

        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.poll.return_value = None
            mock_popen.return_value = mock_process

            await registry.startup_all()

            assert len(registry.servers) == 2
            assert "test-server" in registry.servers
            assert "onedrive" in registry.servers

    @pytest.mark.asyncio
    async def test_shutdown_all(self, registry, sample_config):
        """Shutdown all running servers."""
        registry.load_configs(sample_config)

        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.poll.return_value = None
            mock_popen.return_value = mock_process

            await registry.startup_all()
            assert len(registry.servers) == 2

            await registry.shutdown_all()
            assert len(registry.servers) == 0

    @pytest.mark.asyncio
    async def test_get_server_info(self, registry, sample_config):
        """Get info about all running servers."""
        registry.load_configs(sample_config)

        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.poll.return_value = None
            mock_popen.return_value = mock_process

            await registry.start_server("test-server")
            info = await registry.get_server_info()

            assert "test-server" in info
            assert info["test-server"]["pid"] == 12345
            assert info["test-server"]["alive"] is True

    def test_get_global_registry(self):
        """Get global registry instance."""
        registry = get_mcp_registry()
        assert registry is not None

        # Should return same instance
        registry2 = get_mcp_registry()
        assert registry2 is registry


class TestMCPServerInstance:
    """Test MCPServerInstance dataclass."""

    def test_dataclass_creation(self):
        """Create MCPServerInstance with defaults."""
        from unittest.mock import MagicMock

        mock_process = MagicMock()
        instance = MCPServerInstance(
            server_id="test",
            process=mock_process,
            config={"id": "test"},
        )

        assert instance.server_id == "test"
        assert instance.process == mock_process
        assert instance.request_counter == 0
        assert instance.stdin_writer is None
        assert instance.stdout_reader is None
