import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.models import Membership, User
from app.main import app
from app.tests.plan_helpers import confirm_plan_for_project


def auth_header(client: TestClient, email: str, password: str = "secret123") -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def login_token(client: TestClient, email: str, password: str = "secret123") -> str:
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_drawio_ws_lock_and_broadcast() -> None:
    client = TestClient(app)

    owner_email = "owner_ws@admin.com"
    editor_email = "editor_ws@admin.com"
    viewer_email = "viewer_ws@admin.com"
    password = "secret123"

    owner_headers = auth_header(client, owner_email, password=password)
    _ = auth_header(client, editor_email, password=password)
    _ = auth_header(client, viewer_email, password=password)

    # Create project + run (owner is the creator).
    project_resp = client.post("/api/projects", json={"name": "WS Collab"}, headers=owner_headers)
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    conv_id, plan_hash = confirm_plan_for_project(client, owner_headers, project_id)
    run_resp = client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "conversation_id": conv_id,
            "plan_hash": plan_hash,
            "instruction": "Build a process map",
            "output_types": ["process_map"],
        },
        headers=owner_headers,
    )
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]

    # Add Editor/Viewer memberships directly in the DB (no public endpoints for role changes yet).
    editor_token = login_token(client, editor_email, password=password)
    viewer_token = login_token(client, viewer_email, password=password)
    owner_token = login_token(client, owner_email, password=password)

    # Resolve user ids from DB and insert memberships.
    session = SessionLocal()
    try:
        owner_user = session.scalar(select(User).where(User.email == owner_email))
        editor_user = session.scalar(select(User).where(User.email == editor_email))
        viewer_user = session.scalar(select(User).where(User.email == viewer_email))
        assert owner_user is not None
        assert editor_user is not None
        assert viewer_user is not None

        session.add(
            Membership(
                id=f"m_{uuid.uuid4().hex[:10]}",
                project_id=project_id,
                user_id=editor_user.id,
                role="Editor",
            )
        )
        session.add(
            Membership(
                id=f"m_{uuid.uuid4().hex[:10]}",
                project_id=project_id,
                user_id=viewer_user.id,
                role="Viewer",
            )
        )
        session.commit()
    finally:
        session.close()

    ws_owner = client.websocket_connect(f"/api/drawio/{project_id}/{run_id}/ws?token={owner_token}")
    ws_editor = client.websocket_connect(f"/api/drawio/{project_id}/{run_id}/ws?token={editor_token}")
    ws_viewer = client.websocket_connect(f"/api/drawio/{project_id}/{run_id}/ws?token={viewer_token}")

    with ws_owner as w_owner, ws_editor as w_editor, ws_viewer as w_viewer:
        # Bootstrap messages.
        b_owner = w_owner.receive_json()
        b_editor = w_editor.receive_json()
        b_viewer = w_viewer.receive_json()
        assert b_owner["type"] == "bootstrap"
        assert b_editor["type"] == "bootstrap"
        assert b_viewer["type"] == "bootstrap"

        # Owner requests the lock.
        w_owner.send_json({"type": "request_lock"})
        m_owner = w_owner.receive_json()
        m_editor = w_editor.receive_json()
        m_viewer = w_viewer.receive_json()

        assert m_owner["type"] == "lock_update"
        assert m_editor["type"] == "lock_update"
        assert m_viewer["type"] == "lock_update"
        assert m_owner["locked_by"]["email"] == owner_email

        # Editor cannot take the lock while it is held by the owner.
        w_editor.send_json({"type": "request_lock"})
        m_editor_denied = w_editor.receive_json()
        assert m_editor_denied["type"] == "lock_denied"
        assert m_editor_denied["locked_by"]["email"] == owner_email

        # Viewer is rejected (Viewer role should be read-only).
        w_viewer.send_json({"type": "request_lock"})
        m_viewer_denied = w_viewer.receive_json()
        assert m_viewer_denied["type"] == "lock_denied"
        assert m_viewer_denied.get("reason") == "insufficient_role"

        # Lock-holder autosave should broadcast to all clients.
        xml = "<mxGraphModel><root/></mxGraphModel>"
        w_owner.send_json({"type": "autosave", "xml": xml})

        u_owner = w_owner.receive_json()
        u_editor = w_editor.receive_json()
        u_viewer = w_viewer.receive_json()

        for u in (u_owner, u_editor, u_viewer):
            assert u["type"] == "drawio_update"
            assert u["xml"] == xml

