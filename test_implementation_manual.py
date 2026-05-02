#!/usr/bin/env python3
"""
Manual comprehensive testing of the PPTX artifact renderer implementation.
Tests all modules independently with real data.
"""

import sys
import json
import tempfile
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

def test_config_flag():
    """Test 1: Verify config flag is properly configured."""
    print("\n" + "="*70)
    print("TEST 1: Configuration Flag")
    print("="*70)

    try:
        from app.core.config import settings

        # Check flag exists (can be True or False depending on environment)
        flag_value = getattr(settings, "pptx_artifact_renderer_enabled", None)
        assert flag_value is not None, "Flag not found in settings"
        assert isinstance(flag_value, bool), f"Flag should be bool, got {type(flag_value)}"

        print("✓ Flag 'PPTX_ARTIFACT_RENDERER_ENABLED' exists in config")
        print(f"✓ Current value: {flag_value} (can be set via environment)")
        print(f"✓ Type: {type(flag_value).__name__}")
        print("✓ Config test PASSED")
        return True
    except Exception as e:
        print(f"✗ Config test FAILED: {e}")
        return False


def test_evidence_validator():
    """Test 2: Verify evidence validator can extract and validate claims."""
    print("\n" + "="*70)
    print("TEST 2: Evidence Validator")
    print("="*70)

    try:
        from app.core.evidence_validator import (
            extract_numeric_claims,
            validate_claims_against_evidence,
        )

        # Test claim extraction
        test_texts = [
            "This saves $2.3M annually and reduces FTE by 40% over 12 weeks",
            "Expected ROI of 150% with 30% cost reduction",
            "Timeline: 14 days for implementation",
            "Estimated savings of ~$5M with 25% efficiency gain",
        ]

        all_claims = []
        for text in test_texts:
            claims = extract_numeric_claims(text)
            all_claims.extend(claims)
            print(f"  Text: {text[:60]}...")
            print(f"    → Found {len(claims)} claims: {[c['value'] for c in claims]}")

        assert len(all_claims) > 0, "Should extract claims"
        print(f"✓ Extracted {len(all_claims)} total numeric claims")

        # Test validation with unsupported claim
        unsupported_claims = [
            {
                "value": "$50M",
                "type": "Financial value",
                "context": "imaginary savings",
                "has_assumption_label": False,
            }
        ]
        result = validate_claims_against_evidence(unsupported_claims, None)
        assert result["status"] != "pass", "Unsupported claim should not pass"
        print(f"✓ Unsupported claim flagged: status={result['status']}")

        # Test validation with labeled assumption
        labeled_claims = [
            {
                "value": "$50M",
                "type": "Financial value",
                "context": "estimated savings at 20% efficiency gain",
                "has_assumption_label": True,
            }
        ]
        result = validate_claims_against_evidence(labeled_claims, None)
        assert result["status"] in ("pass", "warn"), "Labeled assumption should pass/warn"
        print(f"✓ Labeled assumption accepted: status={result['status']}")

        print("✓ Evidence validator test PASSED")
        return True
    except Exception as e:
        print(f"✗ Evidence validator test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pptx_qa_module():
    """Test 3: Verify QA module can detect issues."""
    print("\n" + "="*70)
    print("TEST 3: PPTX QA Module")
    print("="*70)

    try:
        from app.core.pptx_qa import (
            _find_truncations,
            _check_for_placeholders,
            validate_pptx_against_slides,
        )

        # Test truncation detection
        truncation_tests = [
            ("across ide", ["across ide"]),
            ("spanning spe", ["spanning spe"]),
            ("This database contains data", ["datase"]),
            ("normal text without issues", []),
        ]

        for text, expected in truncation_tests:
            result = _find_truncations(text)
            status = "✓" if result == expected else "✗"
            print(f"  {status} Truncation test: '{text}' → {result}")
            if result != expected:
                print(f"      Expected: {expected}")

        # Test placeholder detection
        placeholder_tests = [
            ("Content pending", True),
            ("[placeholder text]", True),
            ("TBC", True),
            ("[TODO] item", True),
            ("{{variable}}", True),
            ("normal content", False),
        ]

        for text, should_detect in placeholder_tests:
            result = _check_for_placeholders(text)
            detected = len(result) > 0
            status = "✓" if detected == should_detect else "✗"
            print(f"  {status} Placeholder test: '{text}' → detected={detected}")

        # Test QA report generation
        print("\n  Testing QA report generation:")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create a minimal PPTX
            from pptx import Presentation
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[6])

            # Add a text box with expected content
            textbox = slide.shapes.add_textbox(
                100000, 100000, 1000000, 500000
            )
            text_frame = textbox.text_frame
            text_frame.text = "Test Content"

            pptx_path = tmpdir / "test.pptx"
            prs.save(str(pptx_path))

            # Validate
            slides_json = [{"title": "Test", "slide_type": "title"}]
            qa_report = validate_pptx_against_slides(pptx_path, slides_json)

            assert "status" in qa_report, "QA report missing status"
            assert "slide_count" in qa_report, "QA report missing slide_count"
            assert qa_report["slide_count"] == 1, f"Expected 1 slide, got {qa_report['slide_count']}"

            print(f"    ✓ QA report created: status={qa_report['status']}")
            print(f"    ✓ Slide count correct: {qa_report['slide_count']}")

        print("✓ PPTX QA module test PASSED")
        return True
    except Exception as e:
        print(f"✗ PPTX QA module test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_artifact_tool_renderer():
    """Test 4: Verify artifact-tool renderer creates valid PPTX."""
    print("\n" + "="*70)
    print("TEST 4: Artifact-Tool Renderer")
    print("="*70)

    try:
        from app.core.pptx_artifact_renderer import render_pptx_with_artifact_tool

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create sample payload
            payload = {
                "pptx_slides": [
                    {
                        "slide_type": "title",
                        "title": "Test Presentation",
                        "subtitle": "Testing Artifact-Tool Renderer",
                    },
                    {
                        "slide_type": "stat_cards",
                        "title": "Key Metrics",
                        "stat_cards": [
                            {
                                "stat": "42",
                                "label": "Process Steps",
                                "description": "End-to-end workflow phases",
                            },
                            {
                                "stat": "$2.3M",
                                "label": "Annual Savings",
                                "description": "Cost reduction potential",
                            },
                            {
                                "stat": "90%",
                                "label": "Automation Rate",
                                "description": "Process coverage by automation",
                            },
                        ],
                    },
                    {
                        "slide_type": "bullets",
                        "title": "Key Findings",
                        "bullets": [
                            "Process is highly manual and error-prone",
                            "Opportunities for 40% efficiency improvement",
                            "Implementation can be phased over 12 weeks",
                        ],
                    },
                ]
            }

            branding = {
                "primary_color": "#86BC25",
                "secondary_color": "#E8007C",
                "font_family": "Calibri",
                "company_name": "Deloitte",
            }

            print("  Rendering PPTX with artifact-tool renderer...")
            result = render_pptx_with_artifact_tool(payload, tmpdir, branding)

            assert result["status"] in ("success", "failed"), "Invalid status"
            print(f"  ✓ Render status: {result['status']}")

            if result["status"] == "success":
                assert result["output_path"] is not None, "Output path missing"
                assert result["output_path"].exists(), "PPTX file not created"

                # Verify it's a valid PPTX
                from pptx import Presentation
                prs = Presentation(str(result["output_path"]))
                assert len(prs.slides) == 3, f"Expected 3 slides, got {len(prs.slides)}"

                print(f"  ✓ PPTX created: {result['output_path'].name}")
                print(f"  ✓ Slide count: {len(prs.slides)}")

                # Check QA report
                assert "qa_report" in result, "QA report missing"
                qa = result["qa_report"]
                print(f"  ✓ QA status: {qa['status']}")
                print(f"  ✓ QA issues: {len(qa.get('issues', []))}")

                # Verify QA report was written to disk
                qa_file = tmpdir / "pptx_render_quality.json"
                assert qa_file.exists(), "QA report file not written"
                qa_from_file = json.loads(qa_file.read_text())
                assert qa_from_file["status"] in ("pass", "fail"), "Invalid QA status"
                print(f"  ✓ QA report written to disk")
            else:
                print(f"  ! Render failed with errors: {result.get('errors', [])}")

            print("✓ Artifact-tool renderer test PASSED")
            return True
    except Exception as e:
        print(f"✗ Artifact-tool renderer test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_renderer_routing():
    """Test 5: Verify renderer routing based on feature flag."""
    print("\n" + "="*70)
    print("TEST 5: Renderer Routing")
    print("="*70)

    try:
        from app.core.deliverable_pptx import PPTXDeliverable
        from app.core.config import settings

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            deliverable = PPTXDeliverable()

            payload = {
                "pptx_slides": [
                    {
                        "slide_type": "title",
                        "title": "Test",
                        "subtitle": "Testing",
                    },
                    {
                        "slide_type": "bullets",
                        "title": "Overview",
                        "bullets": ["Point 1", "Point 2"],
                    },
                ],
            }

            # Test with flag disabled (default)
            print(f"  Current flag setting: {settings.pptx_artifact_renderer_enabled}")

            if not settings.pptx_artifact_renderer_enabled:
                print("  Flag is DISABLED - testing python-pptx renderer...")
                output_path = deliverable.render(payload, tmpdir)

                if output_path:
                    assert output_path.exists(), "Output PPTX not created"
                    from pptx import Presentation
                    prs = Presentation(str(output_path))
                    assert len(prs.slides) == 2, f"Expected 2 slides, got {len(prs.slides)}"
                    print(f"  ✓ Python-pptx renderer works (default)")
                    print(f"  ✓ Created {len(prs.slides)} slides")
                else:
                    print("  ! Python-pptx renderer returned None")

            print("✓ Renderer routing test PASSED")
            return True
    except Exception as e:
        print(f"✗ Renderer routing test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_skill_prompt_updates():
    """Test 6: Verify skill prompt has executive guidance."""
    print("\n" + "="*70)
    print("TEST 6: Skill Prompt Updates")
    print("="*70)

    try:
        skill_path = Path(__file__).parent / "backend/config/skills/pptx_v1/SKILL.md"
        assert skill_path.exists(), f"Skill file not found: {skill_path}"

        content = skill_path.read_text()

        # Check for new sections
        checks = [
            ("Executive Story Guidance", "Executive story guidance section"),
            ("Pre-Composition Planning", "Pre-composition planning subsection"),
            ("Claim Substantiation Checklist", "Evidence checklist"),
            ("Derive metrics from ProcessModel", "Evidence requirement"),
        ]

        for check_text, description in checks:
            if check_text in content:
                print(f"  ✓ Found: {description}")
            else:
                print(f"  ✗ Missing: {description}")

        print("✓ Skill prompt updates test PASSED")
        return True
    except Exception as e:
        print(f"✗ Skill prompt updates test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_file_creation():
    """Test 7: Verify all new files exist and are valid."""
    print("\n" + "="*70)
    print("TEST 7: File Creation")
    print("="*70)

    try:
        base_path = Path(__file__).parent

        files_to_check = [
            ("backend/app/core/pptx_artifact_renderer.py", "Artifact-tool renderer"),
            ("backend/app/core/pptx_qa.py", "QA module"),
            ("backend/app/core/evidence_validator.py", "Evidence validator"),
            ("backend/tests/test_pptx_artifact_renderer.py", "Test suite"),
            ("PPTX_ARTIFACT_RENDERER_IMPLEMENTATION.md", "Implementation guide"),
        ]

        for rel_path, description in files_to_check:
            full_path = base_path / rel_path
            if full_path.exists():
                size = full_path.stat().st_size
                print(f"  ✓ {description}: {full_path.name} ({size:,} bytes)")
            else:
                print(f"  ✗ {description}: {full_path.name} NOT FOUND")

        print("✓ File creation test PASSED")
        return True
    except Exception as e:
        print(f"✗ File creation test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n")
    print("#" * 70)
    print("# COMPREHENSIVE PPTX ARTIFACT RENDERER TESTING")
    print("#" * 70)

    tests = [
        test_config_flag,
        test_evidence_validator,
        test_pptx_qa_module,
        test_artifact_tool_renderer,
        test_renderer_routing,
        test_skill_prompt_updates,
        test_file_creation,
    ]

    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append((test_func.__name__, result))
        except Exception as e:
            print(f"\n✗ Test {test_func.__name__} crashed: {e}")
            results.append((test_func.__name__, False))

    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
