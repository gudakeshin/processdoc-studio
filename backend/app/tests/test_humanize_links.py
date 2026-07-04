"""Deliverable boundary must strip internal wiki-link grammar / pipeline filenames."""
from __future__ import annotations

from app.core.deliverable_utils import humanize_deep, humanize_wiki_links


def test_humanize_keeps_human_label() -> None:
    assert humanize_wiki_links("[[guidebook_tier_mapping|Apex Bank Ltd]]") == "Apex Bank Ltd"
    assert humanize_wiki_links("[[lp://bifsg|BFSI banking sector]]") == "BFSI banking sector"
    assert humanize_wiki_links("[[wiki://proj_1/page_9|Infosys Finacle]]") == "Infosys Finacle"


def test_humanize_strips_schemes_and_internal_files() -> None:
    assert "wiki://" not in humanize_wiki_links("See wiki://proj/page_42 for detail")
    assert "index.md" not in humanize_wiki_links("graph rebuilt; index.md regenerated")
    assert "log.md" not in humanize_wiki_links("log.md entry appended")


def test_humanize_leaves_plain_text_untouched() -> None:
    assert humanize_wiki_links("Plain sentence, no markup.") == "Plain sentence, no markup."


def test_humanize_deep_walks_nested_payload() -> None:
    payload = {"title": "[[p|Hello]]", "items": ["[[q|World]]", 7], "n": None}
    out = humanize_deep(payload)
    assert out == {"title": "Hello", "items": ["World", 7], "n": None}


def test_no_link_tokens_survive_a_slide_payload() -> None:
    slides = [
        {"slide_type": "bullets", "title": "Linkage",
         "bullets": ["[[page_id|Human Title]] weaves sources", "[[wiki://p/x|Cross-project]] links"]},
    ]
    cleaned = humanize_deep(slides)
    blob = str(cleaned)
    assert "[[" not in blob and "]]" not in blob and "://" not in blob
