"""
Load versioned deliverable quality contracts and the skill→contract registry.

Contracts live under config/quality_contracts/*.json; bindings are declared in
registry.json so skills only reference an optional quality_contract_id override.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings

_REGISTRY_CACHE: dict[str, tuple[int, dict[str, Any]]] = {}
_CONTRACT_CACHE: dict[str, tuple[int, dict[str, Any]]] = {}


def _default_contracts_root() -> Path:
    custom = (getattr(settings, "quality_contracts_dir", None) or "").strip()
    if custom:
        return Path(custom).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "config" / "quality_contracts"


def _load_json_cached(path: Path, cache: dict[str, tuple[int, dict[str, Any]]]) -> dict[str, Any]:
    key = str(path)
    st = path.stat()
    ent = cache.get(key)
    if ent and ent[0] == st.st_mtime_ns:
        return ent[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        data = {}
    cache[key] = (st.st_mtime_ns, data)
    return data


def load_registry() -> dict[str, Any]:
    root = _default_contracts_root()
    reg_path = root / "registry.json"
    if not reg_path.is_file():
        return {}
    return _load_json_cached(reg_path, _REGISTRY_CACHE)


def ot_normalized(output_type: str) -> str:
    return str(output_type or "").strip().lower()


def load_contract(contract_id: str) -> dict[str, Any] | None:
    cid = (contract_id or "").strip()
    if not cid:
        return None
    path = _default_contracts_root() / f"{cid}.json"
    if not path.is_file():
        return None
    data = _load_json_cached(path, _CONTRACT_CACHE)
    return dict(data) if isinstance(data, dict) else None


def resolve_contract_id(*, skill_id: str, output_type: str, skill_card: dict[str, Any] | None) -> str | None:
    """Pick contract id from skill frontmatter override, else registry binding."""
    sid = (skill_id or "").strip()
    ot = (output_type or "").strip().lower()
    if not sid or not ot:
        return None

    if isinstance(skill_card, dict):
        ov = skill_card.get("quality_contract_id")
        if isinstance(ov, str) and ov.strip():
            cid = ov.strip()
            if load_contract(cid):
                return cid

    reg = load_registry()
    bindings = reg.get("bindings")
    if not isinstance(bindings, list):
        return None
    for b in bindings:
        if not isinstance(b, dict):
            continue
        if str(b.get("skill_id") or "").strip() != sid:
            continue
        types = b.get("output_types")
        if not isinstance(types, list):
            continue
        if ot not in {str(x).strip().lower() for x in types}:
            continue
        cid = str(b.get("contract_id") or "").strip()
        if cid and load_contract(cid):
            return cid
    return None


def build_prompt_bundle(*, skill_id: str, output_type: str, skill_card: dict[str, Any] | None) -> dict[str, Any] | None:
    """Sections + constraints for generation prompts (e.g. proposal DOCX)."""
    cid = resolve_contract_id(skill_id=skill_id, output_type=output_type, skill_card=skill_card)
    if not cid:
        return None
    contract = load_contract(cid)
    if not contract:
        return None
    prompt = contract.get("prompt")
    if not isinstance(prompt, dict):
        return {"output_type": ot_normalized(output_type), "sections": [], "constraints": [], "contract_id": cid}
    sections = prompt.get("sections")
    constraints = prompt.get("constraints")
    if not isinstance(sections, list):
        sections = []
    if not isinstance(constraints, list):
        constraints = []
    return {
        "output_type": ot_normalized(output_type),
        "sections": [str(s).strip() for s in sections if str(s).strip()],
        "constraints": [str(c).strip() for c in constraints if str(c).strip()],
        "contract_id": cid,
        "display_name": str(contract.get("display_name") or ""),
    }


def contract_for_outputs(
    *,
    primary_skills_by_output: dict[str, dict[str, Any]],
    wanted: list[str],
) -> dict[str, dict[str, Any]]:
    """
    Map state output keys (docx_markdown, …) to loaded contract dicts where applicable.
    """
    key_map = {
        "docx": "docx_markdown",
        "pptx": "pptx_slides",
        "pdf": "pdf_markdown",
        "xlsx": "xlsx_markdown",
        "process_map": "drawio_xml",
    }
    out: dict[str, dict[str, Any]] = {}
    for fmt in wanted:
        ot = str(fmt).strip().lower()
        card = primary_skills_by_output.get(ot)
        if not isinstance(card, dict):
            continue
        sid = str(card.get("id") or "").strip()
        if not sid:
            continue
        cid = resolve_contract_id(skill_id=sid, output_type=ot, skill_card=card)
        if not cid:
            continue
        loaded = load_contract(cid)
        if not loaded:
            continue
        st_key = key_map.get(ot)
        if st_key:
            out[st_key] = dict(loaded)
            out[st_key]["_contract_id"] = cid
            out[st_key]["_output_type"] = ot
            out[st_key]["_skill_id"] = sid
    return out
