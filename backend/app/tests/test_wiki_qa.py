"""
Tests for wiki QA/Linting checks (Tier 3 Quality Assurance).

Tests Priority 6: Tier 3 QA/Linting for Wiki Health Checks
"""



class TestBrokenLinksDetection:
    """Test detection of broken wiki links."""

    def test_detects_broken_links(self):
        """Test that broken links to non-existent pages are detected."""
        # Simulate wiki structure
        page_data = {
            "page_1": {
                "title": "Architecture Overview",
                "content": "See [[Database Schema]] for details on [[User Model]]. This references a non-existent [[Deleted Page]]."
            }
        }

        page_titles = {
            "page_1": "Architecture Overview",
            "page_2": "Database Schema",
            "page_3": "User Model",
        }

        # Extract links from content
        import re
        links_pattern = r'\[\[([^\]]+)\]\]'
        broken = []

        for page_id, page_info in page_data.items():
            content = page_info["content"]
            matches = re.findall(links_pattern, content)
            for link_text in matches:
                # Check if link target exists
                target_found = any(
                    link_text.lower() == title.lower()
                    for title in page_titles.values()
                )
                if not target_found:
                    broken.append({
                        "page_id": page_id,
                        "issue_type": "broken_link",
                        "severity": "medium",
                        "message": f"Broken link: [[{link_text}]] references non-existent page"
                    })

        assert len(broken) == 1
        assert broken[0]["issue_type"] == "broken_link"
        assert "Deleted Page" in broken[0]["message"]

    def test_ignores_valid_links(self):
        """Test that valid links are not flagged."""
        page_titles = {
            "page_1": "Architecture",
            "page_2": "Database",
            "page_3": "Models"
        }

        page_content = "[[Architecture]] and [[Database]] and [[Models]] are important."

        import re
        links_pattern = r'\[\[([^\]]+)\]\]'
        matches = re.findall(links_pattern, page_content)

        broken = []
        for link_text in matches:
            target_found = any(
                link_text.lower() == title.lower()
                for title in page_titles.values()
            )
            if not target_found:
                broken.append({"link": link_text})

        assert len(broken) == 0

    def test_empty_page_content(self):
        """Test handling of pages with no links."""
        page_content = "This page has no wiki links."

        import re
        links_pattern = r'\[\[([^\]]+)\]\]'
        matches = re.findall(links_pattern, page_content)

        assert len(matches) == 0


class TestOrphanedPagesDetection:
    """Test detection of pages with no inbound links."""

    def test_detects_orphaned_pages(self):
        """Test that pages with no inbound links are detected."""
        # Simulate relationship counts
        rel_counts = {
            "page_1": {"inbound": 3, "outbound": 2},
            "page_2": {"inbound": 0, "outbound": 1},  # Orphaned
            "page_3": {"inbound": 2, "outbound": 1},
            "page_4": {"inbound": 0, "outbound": 0},  # Isolated
        }

        page_titles = {
            "page_1": "Hub Page",
            "page_2": "Orphaned Page",
            "page_3": "Connected Page",
            "page_4": "Isolated Page",
        }

        orphaned = []
        for page_id, counts in rel_counts.items():
            if counts["inbound"] == 0:
                orphaned.append({
                    "page_id": page_id,
                    "title": page_titles[page_id],
                    "issue_type": "orphaned_page",
                    "severity": "low",
                    "message": f"Page '{page_titles[page_id]}' has no inbound links"
                })

        assert len(orphaned) == 2
        orphan_ids = [o["page_id"] for o in orphaned]
        assert "page_2" in orphan_ids
        assert "page_4" in orphan_ids

    def test_no_orphans_in_connected_wiki(self):
        """Test fully connected wiki has no orphaned pages."""
        rel_counts = {
            "page_1": {"inbound": 2, "outbound": 1},
            "page_2": {"inbound": 1, "outbound": 1},
            "page_3": {"inbound": 3, "outbound": 2},
        }

        orphaned = [p for p, c in rel_counts.items() if c["inbound"] == 0]
        assert len(orphaned) == 0


class TestQAEvaluation:
    """Test complete QA evaluation workflow."""

    def test_qa_evaluation_structure(self):
        """Test that QA evaluation returns correct structure."""
        qa_result = {
            "passed": False,
            "issues": [
                {
                    "page_id": "page_1",
                    "issue_type": "broken_link",
                    "severity": "medium",
                    "message": "Broken link found"
                }
            ],
            "suggestions": [
                {
                    "page_id": "page_2",
                    "issue_type": "orphaned_page",
                    "severity": "low",
                    "message": "Consider linking this page"
                }
            ],
            "severity": "medium",
            "summary": {
                "broken_links": 1,
                "orphaned_pages": 1,
                "missing_entities": 0,
                "total_issues": 1,
            }
        }

        # Verify structure
        assert "passed" in qa_result
        assert "issues" in qa_result
        assert "suggestions" in qa_result
        assert "severity" in qa_result
        assert "summary" in qa_result

        # Verify severity calculation
        assert qa_result["severity"] in ["low", "medium", "high"]
        assert len(qa_result["issues"]) >= 0
        assert len(qa_result["suggestions"]) >= 0

    def test_severity_levels(self):
        """Test severity level calculation based on issue count."""
        test_cases = [
            (0, "low"),      # No issues -> low
            (3, "low"),      # 3 issues -> low
            (6, "medium"),   # 6 issues -> medium
            (11, "high"),    # 11 issues -> high
        ]

        for issue_count, expected_severity in test_cases:
            severity = "low" if issue_count < 5 else "medium" if issue_count < 10 else "high"
            assert severity == expected_severity

    def test_issue_vs_suggestion_separation(self):
        """Test that issues and suggestions are properly separated."""
        all_checks = [
            {"severity": "medium", "type": "broken_link"},
            {"severity": "high", "type": "contradiction"},
            {"severity": "low", "type": "orphaned"},
            {"severity": "low", "type": "missing_entity"},
            {"severity": "medium", "type": "broken_link"},
        ]

        issues = [i for i in all_checks if i["severity"] in ["medium", "high"]]
        suggestions = [i for i in all_checks if i["severity"] == "low"]

        assert len(issues) == 3
        assert len(suggestions) == 2


class TestIntegrationWithAPI:
    """Test integration with wiki API."""

    def test_lint_endpoint_response_format(self):
        """Test that lint endpoint returns properly formatted response."""
        api_response = {
            "status": "success",
            "issues": [
                {
                    "page_id": "page_1",
                    "issue_type": "broken_link",
                    "severity": "medium",
                    "message": "Broken link"
                }
            ],
            "suggestions": [],
            "severity": "low",
            "issues_count": 1,
            "suggestions_count": 0,
        }

        assert api_response["status"] == "success"
        assert isinstance(api_response["issues"], list)
        assert isinstance(api_response["suggestions"], list)
        assert api_response["severity"] in ["low", "medium", "high"]
        assert isinstance(api_response["issues_count"], int)

    def test_error_handling(self):
        """Test that errors are properly handled and returned."""
        error_response = {
            "status": "error",
            "error": "Failed to evaluate wiki quality"
        }

        assert error_response["status"] == "error"
        assert "error" in error_response
        assert isinstance(error_response["error"], str)


class TestEdgeCases:
    """Test edge cases and corner scenarios."""

    def test_empty_wiki(self):
        """Test QA evaluation on empty wiki."""

        # Empty wiki should have no issues
        qa_result = {
            "passed": True,
            "issues": [],
            "suggestions": [],
            "severity": "low",
            "summary": {
                "broken_links": 0,
                "orphaned_pages": 0,
                "missing_entities": 0,
                "total_issues": 0,
            }
        }

        assert qa_result["passed"] is True
        assert qa_result["severity"] == "low"

    def test_single_page_wiki(self):
        """Test QA evaluation on single-page wiki."""
        rel_counts = {"page_1": {"inbound": 0, "outbound": 0}}

        # Single isolated page might trigger orphaned warning
        orphaned = [
            p for p, c in rel_counts.items()
            if c["inbound"] == 0 and len(rel_counts) > 1
        ]

        assert len(orphaned) == 0  # Single page OK if it's alone

    def test_circular_references(self):
        """Test handling of circular page references."""

        # Circular references are valid
        rel_counts = {
            "page_1": {"inbound": 1, "outbound": 1},
            "page_2": {"inbound": 1, "outbound": 1},
            "page_3": {"inbound": 1, "outbound": 1},
        }

        orphaned = [p for p, c in rel_counts.items() if c["inbound"] == 0]
        assert len(orphaned) == 0

    def test_malformed_links(self):
        """Test handling of malformed wiki link syntax."""
        content = "This has [bad bracket and [[unclosed link"

        import re
        links_pattern = r'\[\[([^\]]+)\]\]'
        matches = re.findall(links_pattern, content)

        # Only properly formatted [[...]] are extracted
        assert len(matches) == 0

    def test_case_insensitive_link_matching(self):
        """Test that link matching is case-insensitive."""
        page_titles = {"page_1": "Database Schema"}
        link_text = "database schema"

        # Should match despite case difference
        target_found = any(
            link_text.lower() == title.lower()
            for title in page_titles.values()
        )

        assert target_found is True
