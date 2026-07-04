"""claude_generate_with_thinking: fallback from legacy "enabled" thinking config
to "adaptive" + output_config.effort for models that reject the old shape
(discovered via a live validation run against claude-opus-4-8)."""
from __future__ import annotations

import httpx
import pytest
from anthropic import BadRequestError

from app.services import claude as claude_module


def _bad_request_error(message: str) -> BadRequestError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(400, request=request, json={"error": {"message": message}})
    return BadRequestError(message, response=response, body=None)


class _FakeMessage:
    content = [type("Block", (), {"type": "text", "text": "ok"})()]
    usage = None
    model = "claude-opus-4-8"


class _FakeStream:
    def __init__(self, message: _FakeMessage) -> None:
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def __iter__(self):
        return iter(())

    def get_final_message(self):
        return self._message


class _FakeMessages:
    def __init__(self, calls: list[dict]) -> None:
        self._calls = calls

    def stream(self, **kwargs):
        self._calls.append(kwargs)
        if len(self._calls) == 1:
            raise _bad_request_error(
                '"thinking.type.enabled" is not supported for this model. '
                'Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.'
            )
        return _FakeStream(_FakeMessage())


class _FakeClient:
    def __init__(self, *_, **__) -> None:
        self.calls: list[dict] = []
        self.messages = _FakeMessages(self.calls)


@pytest.fixture(autouse=True)
def _no_circuit_breaker(monkeypatch):
    monkeypatch.setattr(claude_module, "_guard_circuit", lambda: None)
    monkeypatch.setattr(claude_module, "_record_failure", lambda: None)
    monkeypatch.setattr(claude_module, "_record_success", lambda: None)
    monkeypatch.setattr(claude_module, "_record_message_usage", lambda _msg: None)
    monkeypatch.setattr(claude_module, "is_claude_enabled", lambda: True)
    monkeypatch.setattr(claude_module.settings, "anthropic_api_key", "test-key", raising=False)


def test_retries_with_adaptive_thinking_on_legacy_type_rejection(monkeypatch):
    fake_client = _FakeClient()
    monkeypatch.setattr("anthropic.Anthropic", lambda **_: fake_client)

    result = claude_module.claude_generate_with_thinking(
        system="sys", user="hi", model="claude-opus-4-8", budget_tokens=6000,
    )

    assert result["text"] == "ok"
    assert len(fake_client.calls) == 2
    first, second = fake_client.calls
    assert first["thinking"] == {"type": "enabled", "budget_tokens": 6000}
    assert "output_config" not in first
    assert second["thinking"] == {"type": "adaptive"}
    assert second["output_config"] == {"effort": "medium"}


def test_does_not_retry_on_unrelated_bad_request(monkeypatch):
    class _AlwaysFails(_FakeClient):
        def __init__(self, *_, **__):
            super().__init__()

            def _raise(**kwargs):
                self.calls.append(kwargs)
                raise _bad_request_error("max_tokens is too large")

            self.messages.stream = _raise

    fake_client = _AlwaysFails()
    monkeypatch.setattr("anthropic.Anthropic", lambda **_: fake_client)

    with pytest.raises(BadRequestError):
        claude_module.claude_generate_with_thinking(system="sys", user="hi", budget_tokens=6000)
    assert len(fake_client.calls) == 1
