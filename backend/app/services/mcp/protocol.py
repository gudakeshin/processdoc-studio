"""JSON-RPC 2.0 message protocol for MCP stdio transports."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ==================== Data Models ====================

@dataclass
class JSONRPCRequest:
    """JSON-RPC 2.0 request message."""
    method: str
    params: dict[str, Any] | None
    id: int | str | None


@dataclass
class JSONRPCResponse:
    """JSON-RPC 2.0 response message."""
    result: Any | None
    error: dict[str, Any] | None
    id: int | str | None


# ==================== Parsing ====================

def parse_json_rpc_request(line: bytes) -> JSONRPCRequest | None:
    """Parse JSON-RPC 2.0 request from line (including non-request messages)."""
    data = parse_json_rpc_line(line)
    if not data:
        return None

    # Extract request fields
    method = data.get("method")
    if not method:
        return None

    return JSONRPCRequest(
        method=str(method),
        params=data.get("params"),
        id=data.get("id"),
    )


def parse_json_rpc_response(line: bytes) -> JSONRPCResponse | None:
    """Parse JSON-RPC 2.0 response from line."""
    data = parse_json_rpc_line(line)
    if not data:
        return None

    return JSONRPCResponse(
        result=data.get("result"),
        error=data.get("error"),
        id=data.get("id"),
    )


def parse_json_rpc_line(line: bytes) -> dict[str, Any] | None:
    """Generic JSON-RPC line parser."""
    try:
        text = line.decode("utf-8").strip()
        if not text:
            return None
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except (UnicodeDecodeError, json.JSONDecodeError, Exception):
        return None


# ==================== Formatting ====================

def format_json_rpc_request(
    method: str,
    params: dict[str, Any] | None,
    request_id: int | str,
) -> str:
    """Format JSON-RPC 2.0 request for stdio (newline-terminated)."""
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": request_id,
    }
    return json.dumps(payload, ensure_ascii=False) + "\n"


def format_json_rpc_response(
    result: Any,
    request_id: int | str,
) -> str:
    """Format JSON-RPC 2.0 response for stdio (newline-terminated)."""
    payload = {
        "jsonrpc": "2.0",
        "result": result,
        "id": request_id,
    }
    return json.dumps(payload, ensure_ascii=False) + "\n"


def format_json_rpc_error(
    error_code: int,
    error_message: str,
    request_id: int | str,
) -> str:
    """Format JSON-RPC 2.0 error response for stdio (newline-terminated)."""
    payload = {
        "jsonrpc": "2.0",
        "error": {
            "code": error_code,
            "message": error_message,
        },
        "id": request_id,
    }
    return json.dumps(payload, ensure_ascii=False) + "\n"


# ==================== Legacy Compatibility ====================

def json_rpc_request(method: str, params: dict[str, Any] | None, req_id: int | str) -> bytes:
    """Legacy function for backward compatibility."""
    return format_json_rpc_request(method, params, req_id).encode("utf-8")
