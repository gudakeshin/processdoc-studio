from __future__ import annotations

import json
import re
import base64
import threading
import time
from typing import Any, Optional

from app.core.config import settings
from app.services.run_budget import charge_llm_usage, extract_usage_counts

_CB_LOCK = threading.Lock()
_CB_FAIL_COUNT = 0
_CB_OPEN_UNTIL = 0.0


def _guard_circuit() -> None:
    with _CB_LOCK:
        open_until = _CB_OPEN_UNTIL
    if open_until > time.time():
        raise RuntimeError("Claude circuit breaker is open")


def _record_success() -> None:
    global _CB_FAIL_COUNT, _CB_OPEN_UNTIL
    with _CB_LOCK:
        _CB_FAIL_COUNT = 0
        _CB_OPEN_UNTIL = 0.0


def _record_failure() -> None:
    global _CB_FAIL_COUNT, _CB_OPEN_UNTIL
    with _CB_LOCK:
        _CB_FAIL_COUNT += 1
        if _CB_FAIL_COUNT >= max(1, int(settings.anthropic_circuit_breaker_failures)):
            _CB_OPEN_UNTIL = time.time() + max(1, int(settings.anthropic_circuit_breaker_reset_sec))


def _extract_first_json_object(text: str) -> Any:
    """Best-effort extraction of a single JSON object from a model response."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Empty model response")

    # Strip common code fences.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.I | re.S)
    if fenced:
        return json.loads(fenced.group(1))

    # Fallback: take from first '{' to last '}'.
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return json.loads(raw[start : end + 1])

    return json.loads(raw)


def _block_type(block: Any) -> str | None:
    t = getattr(block, "type", None)
    if t is not None:
        return str(t)
    if isinstance(block, dict):
        return str(block.get("type") or "") or None
    return None


def _extract_text(message: Any) -> str:
    """Anthropic SDK returns content blocks; this extracts concatenated text blocks."""
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return str(getattr(message, "content", "") or message)

    parts: list[str] = []
    for block in content:
        if _block_type(block) == "text":
            txt = getattr(block, "text", None) if not isinstance(block, dict) else block.get("text")
            parts.append(str(txt or ""))
    return "".join(parts).strip()


def extract_thinking_and_text(message: Any) -> tuple[str, str]:
    """Split extended-thinking responses into thinking trace and visible assistant text."""
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return "", str(getattr(message, "content", "") or "").strip()

    thinking_parts: list[str] = []
    text_parts: list[str] = []
    for block in content:
        bt = _block_type(block)
        if bt == "thinking":
            raw = getattr(block, "thinking", None) if not isinstance(block, dict) else block.get("thinking")
            if raw is not None:
                thinking_parts.append(str(raw))
        elif bt == "text":
            txt = getattr(block, "text", None) if not isinstance(block, dict) else block.get("text")
            text_parts.append(str(txt or ""))
    return "".join(thinking_parts).strip(), "".join(text_parts).strip()


def is_claude_enabled() -> bool:
    return bool(getattr(settings, "anthropic_api_key", "") and settings.anthropic_api_key.strip())


def _record_message_usage(message: Any) -> None:
    inp, out = extract_usage_counts(message)
    if inp or out:
        charge_llm_usage(input_tokens=inp, output_tokens=out)


def claude_generate(
    *,
    system: str,
    user: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """Low-level Claude call; returns raw text."""
    if not is_claude_enabled():
        raise RuntimeError("Claude disabled: missing ANTHROPIC_API_KEY")

    # Lazy import so unit tests can run without the dependency installed/configured.
    from anthropic import Anthropic  # type: ignore

    client = Anthropic(api_key=settings.anthropic_api_key)
    _guard_circuit()
    try:
        msg = client.messages.create(
            model=model or settings.anthropic_claude_model,
            max_tokens=max_tokens or settings.anthropic_max_tokens,
            temperature=temperature if temperature is not None else settings.anthropic_temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
            timeout=max(1, float(settings.anthropic_timeout_sec)),
        )
    except Exception:
        _record_failure()
        raise
    _record_message_usage(msg)
    _record_success()
    return _extract_text(msg)


def claude_generate_with_thinking(
    *,
    system: str,
    user: str,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    budget_tokens: Optional[int] = None,
) -> dict[str, Any]:
    """
    Messages API call with extended thinking enabled.

    Does not accept ``temperature``: extended thinking is incompatible with temperature
    or top_k overrides on the Messages API.

    Returns keys: ``thinking_text``, ``text`` (assistant visible text), ``raw_message``.
    """
    if not is_claude_enabled():
        raise RuntimeError("Claude disabled: missing ANTHROPIC_API_KEY")

    from anthropic import Anthropic  # type: ignore

    budget = int(budget_tokens if budget_tokens is not None else settings.anthropic_thinking_budget_tokens)
    cap = max_tokens if max_tokens is not None else settings.anthropic_coordinator_plan_max_tokens
    if cap <= budget:
        cap = budget + 2048

    client = Anthropic(api_key=settings.anthropic_api_key)
    _guard_circuit()
    try:
        msg = client.messages.create(
            model=model or settings.anthropic_claude_model,
            max_tokens=cap,
            system=system,
            messages=[{"role": "user", "content": user}],
            thinking={"type": "enabled", "budget_tokens": budget},
            timeout=max(1, float(settings.anthropic_timeout_sec)),
        )
    except Exception:
        _record_failure()
        raise
    _record_message_usage(msg)
    _record_success()
    thinking_text, visible = extract_thinking_and_text(msg)
    if not visible.strip():
        visible = _extract_text(msg)
    return {"thinking_text": thinking_text, "text": visible, "raw_message": msg}


def claude_generate_json(
    *,
    system: str,
    user: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Any:
    """Claude call that expects a JSON object response."""
    text = claude_generate(
        system=system,
        user=user,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return _extract_first_json_object(text)


def claude_generate_json_with_images(
    *,
    system: str,
    user: str,
    image_bytes: list[bytes],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Any:
    """Claude multimodal JSON response with image inputs."""
    if not is_claude_enabled():
        raise RuntimeError("Claude disabled: missing ANTHROPIC_API_KEY")
    if not image_bytes:
        raise ValueError("At least one image is required for multimodal generation")

    from anthropic import Anthropic  # type: ignore

    content_blocks: list[dict[str, Any]] = [{"type": "text", "text": user}]
    for blob in image_bytes:
        content_blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(blob).decode("ascii"),
                },
            }
        )

    client = Anthropic(api_key=settings.anthropic_api_key)
    _guard_circuit()
    try:
        msg = client.messages.create(
            model=model or settings.anthropic_claude_model,
            max_tokens=max_tokens or settings.anthropic_max_tokens,
            temperature=temperature if temperature is not None else settings.anthropic_temperature,
            system=system,
            messages=[{"role": "user", "content": content_blocks}],
            timeout=max(1, float(settings.anthropic_timeout_sec)),
        )
    except Exception:
        _record_failure()
        raise
    _record_message_usage(msg)
    _record_success()
    return _extract_first_json_object(_extract_text(msg))

