from app.services.tool_registry import check_brand_compliance, retrieve_context, validate_references


def test_validate_references_detects_missing_markers() -> None:
    res = validate_references("This has no source markers.")
    assert res["passed"] is False
    assert isinstance(res["issues"], list) and res["issues"]


def test_check_brand_compliance_flags_promotional_language() -> None:
    res = check_brand_compliance("This is a revolutionary and guaranteed approach.")
    assert res["passed"] is False
    assert any("Promotional phrase" in issue for issue in res["issues"])


def test_retrieve_context_returns_empty_without_project() -> None:
    res = retrieve_context(query="test")
    assert res["chunks"] == []
    assert res["context_text"] == ""
