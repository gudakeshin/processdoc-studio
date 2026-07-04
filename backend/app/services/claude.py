from __future__ import annotations

import base64
import json
import re
import threading
import time
from typing import Any

from app.core.config import settings
from app.core.run_control import RunAborted, poll_abort
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
        if max(1, int(settings.anthropic_circuit_breaker_failures)) <= _CB_FAIL_COUNT:
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
    inp, out = extract_usage_counts(message)  # billed weighted totals for budget check
    usage = getattr(message, "usage", None)
    raw_inp = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0) if usage else 0
    cache_create = int(getattr(usage, "cache_creation_input_tokens", 0) or 0) if usage else 0
    if inp or out:
        charge_llm_usage(
            input_tokens=raw_inp,
            output_tokens=out,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_create,
        )


def _build_cached_system(system: str) -> list[dict[str, Any]]:
    """Wrap a system prompt as a cacheable content block."""
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def claude_generate(
    *,
    system: str,
    user: str,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    cache_system: bool = True,
) -> str:
    """Low-level Claude call; returns raw text."""
    if not is_claude_enabled():
        raise RuntimeError("Claude disabled: missing ANTHROPIC_API_KEY")

    # Pre-call budget checking and compression
    if getattr(settings, "prompt_compression_enabled", True):
        from app.services.token_budgets import TokenBudgetChecker, TokenBudgetExceeded

        needed_output = max_tokens or settings.anthropic_max_tokens
        fits, budget_info = TokenBudgetChecker.check_budget(system, user, needed_output)

        if not fits and budget_info.get("remaining_budget", 0) > 1000:
            # Compress to fit remaining budget
            target_tokens = max(
                500,
                budget_info["remaining_budget"] - 200,  # safety margin
            )
            system, user, compression_info = TokenBudgetChecker.compress_prompt_for_budget(
                system=system,
                user=user,
                target_tokens=target_tokens,
                compression_strategy=getattr(settings, "prompt_compression_strategy", "aggressive"),
            )
            if getattr(settings, "prompt_compression_log_verbose", True):
                import logging

                logger = logging.getLogger(__name__)
                logger.info(
                    f"Compressed prompt: {compression_info['original_tokens']} → "
                    f"{compression_info['compressed_tokens']} tokens "
                    f"({compression_info['compression_ratio']:.1%}), "
                    f"tiers: {', '.join(compression_info['tiers_applied'])}"
                )
        elif not fits:
            # Budget exceeded and can't compress enough
            raise TokenBudgetExceeded(
                f"Prompt requires {budget_info['prompt_tokens']} tokens but only "
                f"{budget_info['remaining_budget']} remaining (output needs {needed_output})"
            )

    # Lazy import so unit tests can run without the dependency installed/configured.
    from anthropic import Anthropic  # type: ignore

    client = Anthropic(api_key=settings.anthropic_api_key)
    _guard_circuit()
    try:
        kwargs: dict[str, Any] = dict(
            model=model or settings.anthropic_claude_model,
            max_tokens=max_tokens or settings.anthropic_max_tokens,
            temperature=temperature if temperature is not None else settings.anthropic_temperature,
            messages=[{"role": "user", "content": user}],
            timeout=max(1, float(settings.anthropic_timeout_sec)),
        )
        if cache_system:
            kwargs["system"] = _build_cached_system(system)
        else:
            kwargs["system"] = system
        with client.messages.stream(**kwargs) as stream:
            for _ in stream:
                poll_abort()
            msg = stream.get_final_message()
    except RunAborted:
        raise
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
    model: str | None = None,
    max_tokens: int | None = None,
    budget_tokens: int | None = None,
) -> dict[str, Any]:
    """
    Messages API call with extended thinking enabled.

    Does not accept ``temperature``: extended thinking is incompatible with temperature
    or top_k overrides on the Messages API.

    Returns keys: ``thinking_text``, ``text`` (assistant visible text), ``raw_message``.
    """
    if not is_claude_enabled():
        raise RuntimeError("Claude disabled: missing ANTHROPIC_API_KEY")

    from anthropic import Anthropic, BadRequestError  # type: ignore

    budget = int(budget_tokens if budget_tokens is not None else settings.anthropic_thinking_budget_tokens)
    cap = max_tokens if max_tokens is not None else settings.anthropic_coordinator_plan_max_tokens
    if cap <= budget:
        cap = budget + 2048

    client = Anthropic(api_key=settings.anthropic_api_key)
    _guard_circuit()
    resolved_model = model or settings.anthropic_claude_model
    create_kwargs = dict(
        model=resolved_model,
        max_tokens=cap,
        system=_build_cached_system(system),
        messages=[{"role": "user", "content": user}],
        timeout=max(1, float(settings.anthropic_timeout_sec)),
    )
    try:
        try:
            with client.messages.stream(
                thinking={"type": "enabled", "budget_tokens": budget},
                **create_kwargs,
            ) as stream:
                for _ in stream:
                    poll_abort()
                msg = stream.get_final_message()
        except BadRequestError as exc:
            # Newer models (e.g. claude-opus-4-8) dropped "enabled"/budget_tokens
            # in favor of "adaptive" thinking + an output_config effort tier.
            if "thinking.type" not in str(exc):
                raise
            effort = "low" if budget < 4000 else "medium" if budget < 10000 else "high" if budget < 20000 else "max"
            with client.messages.stream(
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                **create_kwargs,
            ) as stream:
                for _ in stream:
                    poll_abort()
                msg = stream.get_final_message()
    except RunAborted:
        raise
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
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
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
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
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
        with client.messages.stream(
            model=model or settings.anthropic_claude_model,
            max_tokens=max_tokens or settings.anthropic_max_tokens,
            temperature=temperature if temperature is not None else settings.anthropic_temperature,
            system=system,
            messages=[{"role": "user", "content": content_blocks}],
            timeout=max(1, float(settings.anthropic_timeout_sec)),
        ) as stream:
            for _ in stream:
                poll_abort()
            msg = stream.get_final_message()
    except RunAborted:
        raise
    except Exception:
        _record_failure()
        raise
    _record_message_usage(msg)
    _record_success()
    return _extract_first_json_object(_extract_text(msg))

