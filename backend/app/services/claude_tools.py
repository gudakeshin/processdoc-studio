"""Claude Messages API loops with Anthropic Bash and Text Editor tools."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterable

from app.core.config import settings
from app.services.bash_executor import get_bash_executor, new_session_id
from app.services.claude import is_claude_enabled
from app.services.text_editor_executor import execute_text_editor_tool
from app.services.observability import increment
from app.services.langfuse_tracing import langfuse_span
from app.services.tool_registry import resolve_tool_call, tool_result_to_text

_LOG = logging.getLogger(__name__)

BASH_TOOL: dict[str, Any] = {"type": "bash_20250124", "name": "bash"}
TEXT_EDITOR_TOOL: dict[str, Any] = {
    "type": "text_editor_20250728",
    "name": "str_replace_based_edit_tool",
}


def _trace_preview_for_tool(tool_name: str, output_text: str) -> dict[str, Any] | None:
    """Return a compact, UI-friendly preview for known tool outputs.

    Fail-open: any parse error returns ``None`` so we still emit the default
    ``output_chars`` / ``is_error`` summary without blocking the round.
    """

    if not output_text:
        return None
    previewable = {"web_capture"}
    if tool_name not in previewable:
        return None
    try:
        payload = json.loads(output_text)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if tool_name == "web_capture":
        url = str(payload.get("url") or "").strip()
        title = str(payload.get("title") or "").strip()
        text = str(payload.get("text") or "").strip()
        ok = bool(payload.get("ok"))
        error = str(payload.get("error") or "").strip() or None
        truncated = bool(payload.get("truncated"))
        snippet_source = text or error or ""
        snippet = snippet_source[:320]
        if len(snippet_source) > 320:
            snippet = snippet.rstrip() + "…"
        preview: dict[str, Any] = {
            "kind": "web_capture",
            "url": url,
            "title": title[:180],
            "snippet": snippet,
            "ok": ok,
            "truncated": truncated,
        }
        if error:
            preview["error"] = error[:240]
        return preview
    return None


def _assistant_blocks_to_params(content: Iterable[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in content:
        if hasattr(block, "model_dump"):
            d = block.model_dump(mode="json")
        elif isinstance(block, dict):
            d = dict(block)
        else:
            d = {"type": "text", "text": str(block)}
        out.append(d)
    return out


def _extract_final_text_from_message(msg: Any) -> str:
    parts: list[str] = []
    for block in getattr(msg, "content", []) or []:
        t = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
        if t == "text":
            txt = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else "")
            if txt:
                parts.append(str(txt))
    return "".join(parts).strip()


def run_claude_bash_tool_loop(
    *,
    system: str,
    messages: list[dict[str, Any]],
    project_id: str,
    allow_bash: bool,
    user_id: str | None,
    session_id: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Run `beta.messages` with optional Anthropic Bash tool (internal hook + API).

    Keep ``allow_bash=False`` unless ``BASH_TOOL_ENABLED`` and policy allow it.
    Returns keys: ``text``, ``session_id``, ``tool_trace``, ``model``, ``rounds``.
    """
    if not is_claude_enabled():
        raise RuntimeError("Claude disabled: missing ANTHROPIC_API_KEY")
    return run_claude_tools_loop(
        system=system,
        messages=messages,
        project_id=project_id,
        allow_bash=allow_bash,
        allow_text_editor=False,
        allow_write=False,
        user_id=user_id,
        session_id=session_id,
        max_tokens=max_tokens,
    )


def run_claude_tools_loop(
    *,
    system: str,
    messages: list[dict[str, Any]],
    project_id: str,
    allow_bash: bool,
    allow_text_editor: bool,
    allow_write: bool,
    user_id: str | None,
    session_id: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Run `beta.messages` with optional Bash and Text Editor tools.

    Keep all allow_* flags false by default and elevate only per endpoint policy.
    """
    if allow_bash and not settings.bash_tool_enabled:
        raise ValueError("Bash tool requested but BASH_TOOL_ENABLED is false")
    if allow_text_editor and not settings.text_editor_tool_enabled:
        raise ValueError("Text editor tool requested but TEXT_EDITOR_TOOL_ENABLED is false")

    from anthropic import Anthropic  # type: ignore

    chosen_model = settings.anthropic_claude_model
    if allow_text_editor and settings.text_editor_tool_model.strip():
        chosen_model = settings.text_editor_tool_model.strip()
    elif allow_bash and settings.bash_tool_model.strip():
        chosen_model = settings.bash_tool_model.strip()
    model = chosen_model
    client = Anthropic(api_key=settings.anthropic_api_key)

    sid = session_id or new_session_id()
    executor = get_bash_executor()
    msg_history: list[dict[str, Any]] = list(messages)
    tools: list[dict[str, Any]] = []
    if allow_bash:
        tools.append(BASH_TOOL)
    if allow_text_editor:
        editor_tool = dict(TEXT_EDITOR_TOOL)
        editor_tool["max_characters"] = settings.text_editor_max_characters
        tools.append(editor_tool)
    trace_summary: list[dict[str, Any]] = []
    final_text = ""
    rounds_completed = 0

    for round_i in range(settings.bash_max_tool_rounds):
        rounds_completed = round_i + 1
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or settings.anthropic_max_tokens,
            "temperature": settings.anthropic_temperature,
            "system": system,
            "messages": msg_history,
        }
        if tools:
            kwargs["tools"] = tools

        msg = client.beta.messages.create(**kwargs)

        stop = str(getattr(msg, "stop_reason", "") or "")
        assistant_blocks = _assistant_blocks_to_params(msg.content)
        msg_history.append({"role": "assistant", "content": assistant_blocks})

        final_text = _extract_final_text_from_message(msg)

        if stop != "tool_use":
            break

        tool_result_blocks: list[dict[str, Any]] = []
        for block in msg.content:
            btype = getattr(block, "type", None)
            name = getattr(block, "name", None)
            if btype != "tool_use" or name not in {"bash", "str_replace_based_edit_tool"}:
                continue
            tid = getattr(block, "id", "")
            raw_input = getattr(block, "input", None) or {}
            if not isinstance(raw_input, dict):
                raw_input = {}
            if name == "bash":
                restart = bool(raw_input.get("restart"))
                command = raw_input.get("command")
                command_str = command if isinstance(command, str) else None
                increment("bash_tool_calls_total")
                out_text, is_err = executor.execute(
                    project_id=project_id,
                    session_id=sid,
                    command=command_str,
                    restart=restart,
                    user_id=user_id,
                )
                if is_err:
                    if "timed out" in out_text.lower():
                        increment("bash_tool_timeouts_total")
                    increment("bash_tool_failures_total")
                trace_summary.append(
                    {
                        "tool": "bash",
                        "tool_use_id": tid,
                        "restart": restart,
                        "command_preview": (command_str or "")[:200],
                        "is_error": is_err,
                        "output_chars": len(out_text),
                    }
                )
            else:
                increment("text_editor_tool_calls_total")
                out_text, is_err = execute_text_editor_tool(
                    project_id=project_id,
                    tool_input=raw_input,
                    allow_write=allow_write,
                    user_id=user_id,
                )
                if is_err:
                    increment("text_editor_tool_failures_total")
                    if "allow_write=true" in out_text:
                        increment("text_editor_tool_write_rejections_total")
                trace_summary.append(
                    {
                        "tool": "str_replace_based_edit_tool",
                        "tool_use_id": tid,
                        "command": str(raw_input.get("command") or ""),
                        "path_preview": str(raw_input.get("path") or "")[:200],
                        "is_error": is_err,
                        "output_chars": len(out_text),
                    }
                )
            tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": out_text,
                    "is_error": is_err,
                }
            )

        if not tool_result_blocks:
            _LOG.warning("stop_reason=tool_use but no supported tool_use blocks; stopping loop")
            break
        msg_history.append({"role": "user", "content": tool_result_blocks})

    return {
        "text": final_text,
        "session_id": sid,
        "tool_trace": trace_summary,
        "model": model,
        "rounds": rounds_completed,
    }


def run_subagent_tool_loop(
    *,
    system: str,
    user: str,
    project_id: str,
    tool_defs: list[dict[str, Any]],
    native_context: dict[str, Any],
    max_rounds: int | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    agent_id: str = "subagent",
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Multi-round Messages API loop using custom registry tools (no bash/text_editor).

    ``tool_defs`` must be Anthropic-style entries from ``tool_to_anthropic_schema`` / ``anthropic_tool_definitions``.
    """
    if not is_claude_enabled():
        raise RuntimeError("Claude disabled: missing ANTHROPIC_API_KEY")
    if not tool_defs:
        from app.services.claude import claude_generate

        return {
            "text": claude_generate(
                system=system,
                user=user,
                max_tokens=max_tokens or settings.subagent_tool_max_tokens,
            ),
            "tool_trace": [],
            "model": settings.anthropic_claude_model,
            "rounds": 1,
        }

    from anthropic import Anthropic  # type: ignore

    cap = max_rounds if max_rounds is not None else settings.subagent_tool_max_rounds
    client = Anthropic(api_key=settings.anthropic_api_key)
    model = settings.anthropic_claude_model
    msg_history: list[dict[str, Any]] = [{"role": "user", "content": user}]
    trace_summary: list[dict[str, Any]] = []
    final_text = ""
    rounds_completed = 0
    allowed = {str(t.get("name") or "") for t in tool_defs if isinstance(t, dict)}

    for round_i in range(cap):
        rounds_completed = round_i + 1
        tm = str(native_context.get("swarm_teammate_id") or "").strip()
        rid = str(native_context.get("run_id") or run_id or "").strip()
        if (
            tm
            and rid
            and bool(getattr(settings, "swarm_orchestration_enabled", False))
        ):
            from app.services.swarm import format_swarm_mailbox_for_teammate

            block = format_swarm_mailbox_for_teammate(run_id=rid, teammate_id=tm, limit=18)
            if block:
                if round_i == 0:
                    u0 = msg_history[0]["content"]
                    if isinstance(u0, str):
                        msg_history[0]["content"] = f"{block}\n---\n{u0}"
                    elif isinstance(u0, list):
                        msg_history[0]["content"] = [{"type": "text", "text": f"{block}\n---\n"}] + u0
                else:
                    msg_history.append({"role": "user", "content": block})
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens or settings.subagent_tool_max_tokens,
            temperature=temperature if temperature is not None else settings.anthropic_temperature,
            system=system,
            messages=msg_history,
            tools=tool_defs,
        )
        stop = str(getattr(msg, "stop_reason", "") or "")
        assistant_blocks = _assistant_blocks_to_params(msg.content)
        msg_history.append({"role": "assistant", "content": assistant_blocks})
        final_text = _extract_final_text_from_message(msg)

        if stop != "tool_use":
            break

        tool_result_blocks: list[dict[str, Any]] = []
        for block in msg.content:
            btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
            name = getattr(block, "name", None) or (block.get("name") if isinstance(block, dict) else None)
            if btype != "tool_use" or not name:
                continue
            tid = getattr(block, "id", None) or (block.get("id") if isinstance(block, dict) else "")
            raw_input = getattr(block, "input", None) or (block.get("input") if isinstance(block, dict) else None)
            if not isinstance(raw_input, dict):
                raw_input = {}
            name_str = str(name)
            if name_str not in allowed:
                out_text = json.dumps({"error": f"Tool {name_str!r} not enabled for this agent"})
                is_err = True
            else:
                try:
                    result = resolve_tool_call(name_str, raw_input, native_context)
                    out_text = tool_result_to_text(result)
                    is_err = False
                except Exception as exc:  # noqa: BLE001
                    out_text = json.dumps({"error": str(exc)[:800]})
                    is_err = True
            trace_entry: dict[str, Any] = {
                "round": rounds_completed,
                "tool": name_str,
                "tool_use_id": tid,
                "is_error": is_err,
                "output_chars": len(out_text),
            }
            preview = _trace_preview_for_tool(name_str, out_text) if not is_err else None
            if preview:
                trace_entry["preview"] = preview
            trace_summary.append(trace_entry)
            tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": out_text,
                    "is_error": is_err,
                }
            )

        if emit_event:
            emit_event(
                "agent_tool_round",
                {
                    "agent": agent_id,
                    "run_id": run_id,
                    "round": rounds_completed,
                    "trace": trace_summary[-len(tool_result_blocks) :] if tool_result_blocks else [],
                },
            )
        if run_id:
            langfuse_span(
                trace_id=run_id,
                name="agent.tool_round",
                input_payload={"agent_id": agent_id, "round": rounds_completed},
                output_payload={"tool_calls": len(tool_result_blocks), "errors": sum(1 for t in trace_summary if t.get("is_error"))},
            )

        if not tool_result_blocks:
            _LOG.warning("stop_reason=tool_use but no tool_use blocks; stopping subagent loop")
            break
        msg_history.append({"role": "user", "content": tool_result_blocks})

    return {
        "text": final_text,
        "tool_trace": trace_summary,
        "model": model,
        "rounds": rounds_completed,
    }


def run_claude_text_only(
    *,
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """Internal helper: single-turn beta message without tools (for callers that avoid claude_generate)."""
    if not is_claude_enabled():
        raise RuntimeError("Claude disabled: missing ANTHROPIC_API_KEY")
    from anthropic import Anthropic  # type: ignore

    client = Anthropic(api_key=settings.anthropic_api_key)
    m = model or settings.anthropic_claude_model
    msg = client.beta.messages.create(
        model=m,
        max_tokens=max_tokens or settings.anthropic_max_tokens,
        temperature=temperature if temperature is not None else settings.anthropic_temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return _extract_final_text_from_message(msg)
