
from app.services.skill_document import (
    load_builtin_skills_from_markdown,
    skill_dict_from_markdown_text,
    split_skill_markdown,
)


def test_split_skill_markdown_roundtrip_fields() -> None:
    raw = """---
id: test_skill
version: 1.0.0
domain: Test
display_name: Test Skill
output_types: [docx]
tools: [retrieve_context]
description: Desc
sample_instruction: Do thing
---

Hello **instructions** here.
"""
    fm, body = split_skill_markdown(raw)
    assert fm["id"] == "test_skill"
    assert "Hello" in body
    d = skill_dict_from_markdown_text(raw, custom=True)
    assert d is not None
    assert d["id"] == "test_skill"
    assert d["custom"] is True
    assert "instructions" in d["prompt_instructions"]


def test_load_builtin_skills_from_markdown_non_empty() -> None:
    items = load_builtin_skills_from_markdown()
    assert len(items) >= 1
    assert all(isinstance(x.get("prompt_instructions"), str) for x in items)
    paths = [x.get("_skill_md_path") for x in items]
    assert all(isinstance(p, str) and p.endswith("SKILL.md") for p in paths if p)
