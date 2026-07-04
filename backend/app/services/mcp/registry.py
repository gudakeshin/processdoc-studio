"""MCP server lifecycle management and stdio transport."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


# ==================== Data Models ====================

@dataclass
class MCPServerInstance:
    """Running instance of an MCP server."""

    server_id: str
    process: subprocess.Popen
    config: dict[str, Any]
    request_counter: int = field(default=0)

    # Async stdio wrappers (populated after spawn)
    stdin_writer: asyncio.StreamWriter | None = field(default=None)
    stdout_reader: asyncio.StreamReader | None = field(default=None)


class MCPRegistry:
    """Manages lifecycle of MCP server processes."""

    def __init__(self) -> None:
        self.configs: dict[str, dict[str, Any]] = {}
        self.servers: dict[str, MCPServerInstance] = {}
        self._lock = asyncio.Lock()

    def load_configs(self, config_path: str | Path) -> None:
        """Load MCP server configs from JSON file."""
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"MCP config not found at {config_path}, skipping")
            return

        try:
            with path.open() as f:
                configs = json.load(f)

            if not isinstance(configs, list):
                logger.error("MCP config must be a JSON array")
                return

            for cfg in configs:
                if not isinstance(cfg, dict):
                    logger.warning("Skipping non-dict MCP config entry")
                    continue

                server_id = cfg.get("id")
                if not server_id:
                    logger.warning("MCP config missing 'id', skipping")
                    continue

                self.configs[str(server_id)] = cfg
                logger.info(f"MCP: loaded config for {server_id}")

        except Exception as e:
            logger.error(f"Failed to load MCP configs: {e}")

    async def start_server(self, server_id: str) -> MCPServerInstance | None:
        """Spawn MCP server process for given server_id."""
        if server_id not in self.configs:
            logger.error(f"MCP server {server_id} not in configs")
            return None

        cfg = self.configs[server_id]

        try:
            command = cfg.get("command", "")
            args = cfg.get("args", [])
            env_overrides = cfg.get("env", {})

            if not command:
                logger.error(f"MCP server {server_id} missing 'command'")
                return None

            # Merge environment
            env = dict(os.environ)
            for key, value in env_overrides.items():
                # Support ${VAR} substitution
                if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                    var_name = value[2:-1]
                    env[key] = os.getenv(var_name, "")
                else:
                    env[key] = str(value) if value is not None else ""

            # Spawn process
            process = subprocess.Popen(
                [command] + list(args),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=False,  # Binary mode for stdio
            )

            instance = MCPServerInstance(
                server_id=str(server_id),
                process=process,
                config=cfg,
            )

            # Raw blocking pipes are stored; bridge.call_mcp_tool() performs the
            # blocking read/write in a thread executor so the event loop is never
            # stalled (see app/services/mcp/bridge.py).

            self.servers[str(server_id)] = instance
            logger.info(f"MCP: server {server_id} started (PID {process.pid})")
            return instance

        except Exception as e:
            logger.error(f"Failed to start MCP server {server_id}: {e}")
            return None

    async def stop_server(self, server_id: str) -> None:
        """Gracefully stop MCP server process."""
        if server_id not in self.servers:
            return

        instance = self.servers[server_id]

        try:
            # Attempt graceful termination
            instance.process.terminate()

            try:
                loop = asyncio.get_event_loop()
                await asyncio.wait_for(
                    loop.run_in_executor(None, instance.process.wait),
                    timeout=5.0
                )
                logger.info(f"MCP: server {server_id} stopped gracefully")
            except TimeoutError:
                # Force kill if graceful fails
                instance.process.kill()
                logger.warning(f"MCP: server {server_id} force-killed after timeout")

        except Exception as e:
            logger.error(f"Error stopping MCP server {server_id}: {e}")
        finally:
            self.servers.pop(str(server_id), None)

    async def health_check(self, server_id: str) -> bool:
        """Check if MCP server is running and responsive."""
        if server_id not in self.servers:
            return False

        instance = self.servers[server_id]

        try:
            # Check if process is still alive
            return instance.process.poll() is None
        except Exception:
            return False

    async def get_server_info(self) -> dict[str, Any]:
        """Get info about all running servers."""
        info = {}
        for server_id, instance in self.servers.items():
            info[server_id] = {
                "pid": instance.process.pid,
                "config": instance.config,
                "alive": instance.process.poll() is None,
            }
        return info

    async def startup_all(self) -> None:
        """Start all configured servers."""
        async with self._lock:
            for server_id in self.configs:
                await self.start_server(server_id)

    async def shutdown_all(self) -> None:
        """Stop all running servers."""
        async with self._lock:
            for server_id in list(self.servers.keys()):
                await self.stop_server(server_id)


# ==================== Global Registry Instance ====================

_mcp_registry: MCPRegistry | None = None


def get_mcp_registry() -> MCPRegistry:
    """Get or create the global MCP registry."""
    global _mcp_registry
    if _mcp_registry is None:
        _mcp_registry = MCPRegistry()
    return _mcp_registry


# ==================== Lifecycle Functions ====================

async def startup_mcp_servers() -> None:
    """Initialize MCP servers on app startup."""
    if not settings.mcp_enabled:
        logger.info("MCP disabled, skipping server startup")
        return

    try:
        registry = get_mcp_registry()
        config_path = Path(__file__).parent.parent.parent / "config" / "mcp_servers.json"
        registry.load_configs(config_path)

        await registry.startup_all()

        info = await registry.get_server_info()
        logger.info(f"MCP: started {len(info)} server(s)")

    except Exception as e:
        logger.error(f"Failed to start MCP servers: {e}")


async def shutdown_mcp_servers() -> None:
    """Clean up MCP servers on app shutdown."""
    try:
        registry = get_mcp_registry()
        await registry.shutdown_all()
        logger.info("MCP: all servers shut down")
    except Exception as e:
        logger.error(f"Failed to shut down MCP servers: {e}")


# ==================== Legacy Functions ====================

def load_mcp_server_configs() -> list[dict[str, object]]:
    """Load MCP server configs from JSON file (legacy)."""
    path = Path(__file__).resolve().parents[3] / "config" / "mcp_servers.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def list_mcp_servers() -> list[str]:
    """Return list of configured MCP server IDs (legacy)."""
    return [cfg.get("id") for cfg in load_mcp_server_configs() if cfg.get("id")]
