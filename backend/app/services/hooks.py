"""Hook protocol and boundary execution for run lifecycle."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from app.core.tz import IST
from typing import Any, Literal

from sqlalchemy import select

from app.db.models import HookControl, HookExecution
from app.services.observability import increment

HookOutcomeType = Literal["ABORT", "WARN", "SKIP", "OK"]
HookPoint = Literal["pre_run_execution", "post_skill_selection", "post_output_generation", "post_finalization"]
HookCallable = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]


@dataclass
class HookResult:
    hook_name: str
    outcome: HookOutcomeType
    message: str = ""
    payload: dict[str, Any] | None = None


@dataclass
class HookRegistration:
    hook_name: str
    hook: HookCallable
    source: str  # platform|project|builtin
    order: int
    idempotency_key: str | None = None
    max_concurrency: int = 1
    advisory: bool = False


_HOOK_REGISTRY_PLATFORM: dict[HookPoint, list[HookRegistration]] = {
    "pre_run_execution": [],
    "post_skill_selection": [],
    "post_output_generation": [],
    "post_finalization": [],
}
_HOOK_REGISTRY_PROJECT: dict[str, dict[HookPoint, list[HookRegistration]]] = {}
_HOOK_INFLIGHT: dict[str, int] = {}
_HOOK_DISABLED: set[str] = set()
_HOOK_LOCK = threading.RLock()


def register_hook(
    point: HookPoint,
    hook_name: str,
    hook: HookCallable,
    *,
    project_id: str | None = None,
    source: str = "platform",
    order: int = 100,
    idempotency_key: str | None = None,
    max_concurrency: int = 1,
    advisory: bool = False,
) -> None:
    reg = HookRegistration(
        hook_name=hook_name,
        hook=hook,
        source=("project" if project_id else source),
        order=int(order),
        idempotency_key=idempotency_key,
        max_concurrency=max(1, int(max_concurrency)),
        advisory=bool(advisory),
    )
    with _HOOK_LOCK:
        if project_id:
            per_proj = _HOOK_REGISTRY_PROJECT.setdefault(project_id, {
                "pre_run_execution": [],
                "post_skill_selection": [],
                "post_output_generation": [],
                "post_finalization": [],
            })
            per_proj.setdefault(point, []).append(reg)
            return
        _HOOK_REGISTRY_PLATFORM.setdefault(point, []).append(reg)


async def run_hooks(
    point: HookPoint,
    run_context: dict[str, Any],
    *,
    timeout_sec: float = 10.0,
    project_id: str | None = None,
) -> list[HookResult]:
    results: list[HookResult] = []
    hooks: list[HookRegistration] = []
    with _HOOK_LOCK:
        hooks.extend(_HOOK_REGISTRY_PLATFORM.get(point, []))
        if project_id and project_id in _HOOK_REGISTRY_PROJECT:
            hooks.extend(_HOOK_REGISTRY_PROJECT[project_id].get(point, []))
    hooks = sorted(hooks, key=lambda h: (h.order, h.hook_name))
    seen_idempotency: set[str] = set()
    for reg in hooks:
        hook_name = reg.hook_name
        with _HOOK_LOCK:
            hook_disabled = hook_name in _HOOK_DISABLED
        if hook_disabled:
            increment("hook_skip_total")
            results.append(HookResult(hook_name=hook_name, outcome="SKIP", message="hook_disabled"))
            continue
        hook = reg.hook
        if reg.idempotency_key and reg.idempotency_key in seen_idempotency:
            increment("hook_skip_total")
            results.append(HookResult(hook_name=hook_name, outcome="SKIP", message="idempotent_skip"))
            continue
        if reg.idempotency_key:
            seen_idempotency.add(reg.idempotency_key)
        inflight_key = f"{point}:{hook_name}"
        with _HOOK_LOCK:
            inflight = int(_HOOK_INFLIGHT.get(inflight_key, 0))
            if inflight < reg.max_concurrency:
                _HOOK_INFLIGHT[inflight_key] = inflight + 1
        if inflight >= reg.max_concurrency:
            increment("hook_skip_total")
            results.append(HookResult(hook_name=hook_name, outcome="SKIP", message="max_concurrency_reached"))
            continue
        try:
            payload = await asyncio.wait_for(hook(run_context), timeout=timeout_sec)
            outcome = str((payload or {}).get("outcome") or "OK").upper()
            if outcome not in {"ABORT", "WARN", "SKIP", "OK"}:
                outcome = "WARN"
            results.append(
                HookResult(
                    hook_name=hook_name,
                    outcome=outcome,  # type: ignore[arg-type]
                    message=str((payload or {}).get("message") or ""),
                    payload=payload if isinstance(payload, dict) else None,
                )
            )
        except TimeoutError:
            increment("hook_timeout_total")
            if reg.advisory:
                results.append(HookResult(hook_name=hook_name, outcome="WARN", message="hook_timeout"))
            else:
                results.append(HookResult(hook_name=hook_name, outcome="ABORT", message="hook_timeout"))
        except Exception as exc:  # noqa: BLE001
            if reg.advisory:
                results.append(HookResult(hook_name=hook_name, outcome="WARN", message=f"hook_error:{exc}"))
            else:
                results.append(HookResult(hook_name=hook_name, outcome="ABORT", message=f"hook_error:{exc}"))
        finally:
            with _HOOK_LOCK:
                _HOOK_INFLIGHT[inflight_key] = max(0, int(_HOOK_INFLIGHT.get(inflight_key, 1)) - 1)
    return results


def run_hooks_sync(
    point: HookPoint,
    run_context: dict[str, Any],
    *,
    timeout_sec: float = 10.0,
    project_id: str | None = None,
) -> list[HookResult]:
    """Run hooks from synchronous code even if an event loop already exists."""
    coro = run_hooks(point, run_context, timeout_sec=timeout_sec, project_id=project_id)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_holder: dict[str, Any] = {}
    err_holder: dict[str, Exception] = {}

    def _runner() -> None:
        try:
            result_holder["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            err_holder["error"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    if "error" in err_holder:
        raise err_holder["error"]
    return result_holder.get("value", [])


def hook_execution_exists(session, *, run_id: str, hook_exec_id_value: str) -> bool:
    count = session.scalar(
        select(HookExecution.id).where(
            HookExecution.run_id == run_id,
            HookExecution.hook_exec_id == hook_exec_id_value,
        ).limit(1)
    )
    return count is not None


def record_hook_execution(
    session,
    *,
    run_id: str,
    hook_point: str,
    hook_name: str,
    hook_exec_id_value: str,
    idempotency_key: str | None,
    outcome: str,
) -> None:
    row = HookExecution(
        run_id=run_id,
        hook_point=hook_point,
        hook_name=hook_name,
        hook_exec_id=hook_exec_id_value,
        idempotency_key=idempotency_key,
        outcome=outcome,
    )
    session.add(row)


def list_registered_hooks() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with _HOOK_LOCK:
        platform = {k: list(v) for k, v in _HOOK_REGISTRY_PLATFORM.items()}
        project_hooks = {pk: {k: list(v) for k, v in pv.items()} for pk, pv in _HOOK_REGISTRY_PROJECT.items()}
        disabled_hooks = set(_HOOK_DISABLED)
    for point, regs in platform.items():
        for reg in regs:
            out.append(
                {
                    "hook_point": point,
                    "hook_name": reg.hook_name,
                    "source": reg.source,
                    "order": reg.order,
                    "idempotency_key": reg.idempotency_key,
                    "max_concurrency": reg.max_concurrency,
                    "advisory": reg.advisory,
                    "disabled": reg.hook_name in disabled_hooks,
                }
            )
    for project_id, per_point in project_hooks.items():
        for point, regs in per_point.items():
            for reg in regs:
                out.append(
                    {
                        "project_id": project_id,
                        "hook_point": point,
                        "hook_name": reg.hook_name,
                        "source": reg.source,
                        "order": reg.order,
                        "idempotency_key": reg.idempotency_key,
                        "max_concurrency": reg.max_concurrency,
                        "advisory": reg.advisory,
                        "disabled": reg.hook_name in disabled_hooks,
                    }
                )
    return out


def disable_hook(hook_name: str) -> None:
    with _HOOK_LOCK:
        _HOOK_DISABLED.add(str(hook_name))


def is_hook_disabled(hook_name: str) -> bool:
    with _HOOK_LOCK:
        return str(hook_name) in _HOOK_DISABLED


def sync_disabled_hooks_from_db(session, *, project_id: str | None = None) -> None:
    rows = session.scalars(select(HookControl).where(HookControl.disabled.is_(True))).all()
    now = datetime.now(IST).replace(tzinfo=None)
    active: set[str] = set()
    for row in rows:
        if row.expires_at and row.expires_at <= now:
            continue
        if row.project_id and project_id and row.project_id != project_id:
            continue
        active.add(str(row.hook_name))
    with _HOOK_LOCK:
        _HOOK_DISABLED.clear()
        _HOOK_DISABLED.update(active)


def upsert_hook_control(
    session,
    *,
    hook_name: str,
    disabled: bool,
    actor: str | None = None,
    reason: str | None = None,
    project_id: str | None = None,
) -> HookControl:
    row = session.scalar(
        select(HookControl).where(
            HookControl.hook_name == str(hook_name),
            HookControl.project_id == project_id,
        ).limit(1)
    )
    if row is None:
        row = HookControl(
            hook_name=str(hook_name),
            project_id=project_id,
            disabled=bool(disabled),
            actor=actor,
            reason=reason,
            updated_at=datetime.now(IST).replace(tzinfo=None),
        )
        session.add(row)
    else:
        row.disabled = bool(disabled)
        row.actor = actor
        row.reason = reason
        row.updated_at = datetime.now(IST).replace(tzinfo=None)
    return row

