"""Helpers for tests that start runs after the confirmed-plan gate."""

from fastapi.testclient import TestClient

DEFAULT_PLAN_USER_MESSAGE = (
    "Build a detailed narrative proposal report for the executive steering committee "
    "including timeline scope and deck outline for delivery."
)


def confirm_plan_for_project(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    *,
    content: str | None = None,
) -> tuple[str, str]:
    """Post a coworker message, confirm the plan, return (conversation_id, plan_hash)."""
    msg = client.post(
        f"/api/projects/{project_id}/conversation/messages",
        json={"content": (content or DEFAULT_PLAN_USER_MESSAGE).strip()},
        headers=headers,
    )
    assert msg.status_code == 200, msg.text
    body = msg.json()
    conv_id = body["conversation_id"]
    plan_hash = body["plan_hash"]

    # Newer conversation flow may require explicit decision answers before confirm.
    if not body.get("ready_for_confirmation"):
        prompts = body.get("decision_prompts") if isinstance(body, dict) else []
        unresolved = set(body.get("unresolved_prompt_ids") or [])
        answers: list[dict[str, object]] = []
        if isinstance(prompts, list):
            for prompt in prompts:
                if not isinstance(prompt, dict):
                    continue
                prompt_id = str(prompt.get("id") or "").strip()
                if not prompt_id or prompt_id not in unresolved:
                    continue
                options = prompt.get("options") if isinstance(prompt.get("options"), list) else []
                first = options[0] if options and isinstance(options[0], dict) else {}
                first_value = str(first.get("value") or "").strip()
                if not first_value:
                    continue
                answers.append({"prompt_id": prompt_id, "selected_values": [first_value]})
        if answers:
            decision_resp = client.post(
                f"/api/projects/{project_id}/conversation/decisions",
                json={
                    "conversation_id": conv_id,
                    "plan_hash": plan_hash,
                    "answers": answers,
                },
                headers=headers,
            )
            assert decision_resp.status_code == 200, decision_resp.text
            body = decision_resp.json()
            conv_id = body["conversation_id"]
            plan_hash = body["plan_hash"]

    assert body.get("ready_for_confirmation"), body
    conf = client.post(
        f"/api/projects/{project_id}/conversation/confirm",
        json={"conversation_id": conv_id, "plan_hash": plan_hash},
        headers=headers,
    )
    assert conf.status_code == 200, conf.text
    return conv_id, plan_hash
