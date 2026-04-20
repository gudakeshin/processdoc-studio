"""Unit tests for MCP protocol module."""

import json

from app.services.mcp.protocol import (
    JSONRPCRequest,
    JSONRPCResponse,
    format_json_rpc_error,
    format_json_rpc_request,
    format_json_rpc_response,
    parse_json_rpc_request,
    parse_json_rpc_response,
)


class TestJSONRPCParsing:
    """Test JSON-RPC message parsing."""

    def test_parse_valid_request(self):
        """Parse valid JSON-RPC request."""
        line = b'{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "test"}, "id": 1}\n'
        req = parse_json_rpc_request(line)

        assert req is not None
        assert req.method == "tools/call"
        assert req.params == {"name": "test"}
        assert req.id == 1

    def test_parse_request_no_params(self):
        """Parse request without params field."""
        line = b'{"jsonrpc": "2.0", "method": "initialize", "id": 1}\n'
        req = parse_json_rpc_request(line)

        assert req is not None
        assert req.method == "initialize"
        assert req.params is None
        assert req.id == 1

    def test_parse_request_no_id(self):
        """Parse notification (no id)."""
        line = b'{"jsonrpc": "2.0", "method": "log", "params": {"msg": "hello"}}\n'
        req = parse_json_rpc_request(line)

        assert req is not None
        assert req.method == "log"
        assert req.id is None

    def test_parse_invalid_json(self):
        """Gracefully handle invalid JSON."""
        line = b'{ invalid json }\n'
        req = parse_json_rpc_request(line)

        assert req is None

    def test_parse_non_object(self):
        """Reject non-object payloads."""
        line = b'[1, 2, 3]\n'
        req = parse_json_rpc_request(line)

        assert req is None

    def test_parse_missing_method(self):
        """Reject message without method."""
        line = b'{"jsonrpc": "2.0", "id": 1}\n'
        req = parse_json_rpc_request(line)

        assert req is None

    def test_parse_response_success(self):
        """Parse successful response."""
        line = b'{"jsonrpc": "2.0", "result": {"data": "ok"}, "id": 1}\n'
        resp = parse_json_rpc_response(line)

        assert resp is not None
        assert resp.result == {"data": "ok"}
        assert resp.error is None
        assert resp.id == 1

    def test_parse_response_error(self):
        """Parse error response."""
        line = b'{"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}, "id": 1}\n'
        resp = parse_json_rpc_response(line)

        assert resp is not None
        assert resp.result is None
        assert resp.error == {"code": -32600, "message": "Invalid Request"}
        assert resp.id == 1

    def test_parse_empty_line(self):
        """Handle empty lines."""
        line = b'\n'
        req = parse_json_rpc_request(line)

        assert req is None

    def test_parse_unicode(self):
        """Handle UTF-8 strings."""
        line = b'{"jsonrpc": "2.0", "method": "test", "params": {"msg": "\\u00e9"}, "id": 1}\n'
        req = parse_json_rpc_request(line)

        assert req is not None
        assert "msg" in req.params


class TestJSONRPCFormatting:
    """Test JSON-RPC message formatting."""

    def test_format_request(self):
        """Format a request."""
        result = format_json_rpc_request("tools/call", {"name": "test"}, 42)

        assert result.endswith("\n")
        obj = json.loads(result)
        assert obj["jsonrpc"] == "2.0"
        assert obj["method"] == "tools/call"
        assert obj["params"] == {"name": "test"}
        assert obj["id"] == 42

    def test_format_request_no_params(self):
        """Format request without params."""
        result = format_json_rpc_request("initialize", None, "uuid-1")

        obj = json.loads(result)
        assert obj["method"] == "initialize"
        assert obj["params"] == {}
        assert obj["id"] == "uuid-1"

    def test_format_response(self):
        """Format a response."""
        result = format_json_rpc_response({"status": "ok"}, 42)

        obj = json.loads(result)
        assert obj["jsonrpc"] == "2.0"
        assert obj["result"] == {"status": "ok"}
        assert obj["id"] == 42

    def test_format_error(self):
        """Format an error response."""
        result = format_json_rpc_error(-32600, "Invalid Request", 42)

        obj = json.loads(result)
        assert obj["jsonrpc"] == "2.0"
        assert obj["error"]["code"] == -32600
        assert obj["error"]["message"] == "Invalid Request"
        assert obj["id"] == 42

    def test_roundtrip_request(self):
        """Format and parse request."""
        formatted = format_json_rpc_request("test", {"x": 1}, 1)
        parsed = parse_json_rpc_request(formatted.encode())

        assert parsed is not None
        assert parsed.method == "test"
        assert parsed.params == {"x": 1}
        assert parsed.id == 1

    def test_roundtrip_response(self):
        """Format and parse response."""
        formatted = format_json_rpc_response({"result": 123}, 1)
        parsed = parse_json_rpc_response(formatted.encode())

        assert parsed is not None
        assert parsed.result == {"result": 123}
        assert parsed.error is None
        assert parsed.id == 1


class TestJSONRPCDataTypes:
    """Test JSON-RPC data type handling."""

    def test_request_dataclass(self):
        """Verify JSONRPCRequest dataclass."""
        req = JSONRPCRequest(method="test", params={"x": 1}, id=1)
        assert req.method == "test"
        assert req.params == {"x": 1}
        assert req.id == 1

    def test_response_dataclass(self):
        """Verify JSONRPCResponse dataclass."""
        resp = JSONRPCResponse(result={"ok": True}, error=None, id=1)
        assert resp.result == {"ok": True}
        assert resp.error is None
        assert resp.id == 1

    def test_request_with_string_id(self):
        """Support string request IDs."""
        line = b'{"jsonrpc": "2.0", "method": "test", "id": "uuid-123"}\n'
        req = parse_json_rpc_request(line)

        assert req is not None
        assert req.id == "uuid-123"

    def test_request_with_large_params(self):
        """Handle large parameter objects."""
        large_params = {f"key_{i}": f"value_{i}" for i in range(100)}
        formatted = format_json_rpc_request("test", large_params, 1)
        parsed = parse_json_rpc_request(formatted.encode())

        assert parsed is not None
        assert len(parsed.params) == 100

    def test_null_params(self):
        """Handle null params field."""
        line = b'{"jsonrpc": "2.0", "method": "test", "params": null, "id": 1}\n'
        req = parse_json_rpc_request(line)

        assert req is not None
        assert req.params is None
