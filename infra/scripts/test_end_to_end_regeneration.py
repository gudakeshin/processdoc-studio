#!/usr/bin/env python3.11
"""End-to-end test: Regenerate TestEng2 deck and validate Phase 1 fixes."""

import json
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.agents.coordinator import Coordinator
from app.services.deliverable_quality import _validate_pptx_completeness


def test_regenerate_testeng2_deck():
    """Regenerate the TestEng2 P2P process deck and validate all slides."""

    print("=" * 80)
    print("PHASE 1 END-TO-END TEST: TestEng2 Deck Regeneration")
    print("=" * 80)

    # The TestEng2 process: Procure-to-Pay (P2P)
    raw_text = """
    Process: Procure-to-Pay (P2P)

    Overview:
    End-to-end procurement process from requisition to payment.
    Involves 5 key roles across 3 major systems.
    Annual spend: $450M. Cycle time: 14 days.

    Key Steps:
    1. Department creates purchase request in ME51N
    2. Finance controller counter-signs if >INR 50K
    3. Procurement creates PO in ME21N
    4. Vendor ships material
    5. Storekeeper receives and inspects material
    6. GR (Goods Receipt) posted in MIGO
    7. Invoice received from vendor
    8. 3-way match: PO, GR, Invoice
    9. Material QM check (if configured)
    10. Blocked invoice escalated for gap resolution
    11. Invoice cleared for payment
    12. Payment run created (F110)
    13. Bank payment initiated via portal or file transfer
    14. Reconciliation and audit trail

    Roles:
    - Department Heads / Storesmen: Raise PRs
    - Finance Controller: Approve and countersign
    - Procurement: Create POs and manage vendors
    - Stores: Receive and quality check
    - Treasury: Execute payments
    - Vendors: Supply materials

    Systems:
    - SAP (ME51N, ME21N, MIGO, F110, QM)
    - HDFC Portal (payment execution)
    - Email (communication)

    Key Metrics:
    - 14 steps end-to-end
    - 5 key roles
    - 3 systems integrated
    - $450M annual spend
    - Target cycle time: 10 days
    - Current error rate: 8%

    Critical Gaps:
    - ~300 duplicate vendor codes (no governance)
    - 2-3 day lag between GR and invoice (visibility gap)
    - Manual payment (treasury bottleneck)
    - No QM enforcement (quality risk)

    Recommendations:
    1. Centralize vendor master (remove duplicates, enforce codes)
    2. Activate QM inspection gates (block low-quality material)
    3. Implement OCR + DMEE (straight-through processing)
    """

    print("\n[1/5] Input: P2P Process Description")
    print("-" * 80)
    print(f"Process: Procure-to-Pay")
    print(f"Steps: 14")
    print(f"Roles: 5")
    print(f"Systems: 3")
    print(f"Annual Spend: $450M")

    print("\n[2/5] Running Coordinator with Phase 1 Fixes...")
    print("-" * 80)

    try:
        coordinator = Coordinator()

        state = coordinator.run({
            "raw_text": raw_text,
            "requested_outputs": ["deck"],
            "dpdp_flags": {"enabled": True},
        })

        print("✅ Coordinator execution completed")

    except Exception as e:
        print(f"❌ Coordinator execution failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n[3/5] Extracting PPTX Slides JSON...")
    print("-" * 80)

    # Get the PPTX slides from coordinator output
    pptx_output = state.get("pptx_slides")

    if not pptx_output:
        print("❌ No pptx_slides in coordinator output")
        print(f"Available outputs: {list(state.keys())}")
        return False

    # Convert to JSON structure if needed
    if isinstance(pptx_output, str):
        try:
            pptx_json_data = json.loads(pptx_output)
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse PPTX JSON: {e}")
            return False
    elif isinstance(pptx_output, list):
        # If it's already a list, wrap it in the expected structure
        pptx_json_data = {"slides": pptx_output}
    else:
        pptx_json_data = pptx_output

    print(f"✅ PPTX output extracted")

    # Get slides list
    if isinstance(pptx_json_data, dict):
        slides = pptx_json_data.get("slides", [])
    elif isinstance(pptx_json_data, list):
        slides = pptx_json_data
    else:
        slides = []

    print(f"   Total slides: {len(slides)}")

    print("\n[4/5] Validating Slide Completeness (Phase 1 Fix)...")
    print("-" * 80)

    # Run completeness check
    if isinstance(pptx_json_data, dict):
        pptx_json_str = json.dumps(pptx_json_data)
    else:
        pptx_json_str = json.dumps({"slides": pptx_json_data})

    is_complete, issues = _validate_pptx_completeness(pptx_json_str)

    if is_complete:
        print("✅ COMPLETENESS CHECK PASSED")
        print("   All slides have required content")
    else:
        print("❌ COMPLETENESS CHECK FAILED")
        print("   Issues found:")
        for issue in issues:
            print(f"   - {issue}")
        return False

    print("\n[5/5] Detailed Slide Analysis...")
    print("-" * 80)

    # slides was already extracted above
    all_populated = True

    for i, slide in enumerate(slides, 1):
        slide_type = slide.get("slide_type", "unknown")
        title = slide.get("title", "[No title]")

        # Check if slide has content
        has_content = False
        content_info = ""

        if slide_type == "stat_cards":
            cards = slide.get("stat_cards", [])
            has_content = len(cards) >= 3
            content_info = f"({len(cards)} cards)"
        elif slide_type == "column_cards":
            cards = slide.get("column_cards", [])
            has_content = len(cards) >= 3
            content_info = f"({len(cards)} columns)"
        elif slide_type == "stack_layers":
            layers = slide.get("stack_layers", [])
            has_content = len(layers) >= 1
            content_info = f"({len(layers)} layers)"
        elif slide_type == "table":
            table = slide.get("table", {})
            rows = table.get("rows", [])
            has_content = len(rows) >= 1
            content_info = f"({len(rows)} rows)"
        elif slide_type == "bullets":
            bullets = slide.get("bullets", [])
            has_content = len(bullets) >= 1
            content_info = f"({len(bullets)} bullets)"
        elif slide_type == "title":
            has_content = True
            content_info = "(title slide)"

        status = "✅" if has_content else "❌"

        print(f"Slide {i}: {status} {slide_type:15s} | {title:40s} | {content_info}")

        if not has_content:
            all_populated = False

    print("\n" + "=" * 80)

    if all_populated:
        print("✅ PHASE 1 END-TO-END TEST: PASSED")
        print("=" * 80)
        print("\nSummary:")
        print(f"  ✅ All {len(slides)} slides are populated with content")
        print(f"  ✅ No blank slides detected")
        print(f"  ✅ Completeness validation passed")
        print(f"  ✅ Quality gate passed")
        print("\nConclusion: Phase 1 fixes are working correctly!")
        print("The deck is now presentation-ready for C-suite.")
        return True
    else:
        print("❌ PHASE 1 END-TO-END TEST: FAILED")
        print("=" * 80)
        print("\nSome slides are still blank or incomplete.")
        print("This indicates Phase 1 fixes need refinement.")
        return False


if __name__ == "__main__":
    try:
        success = test_regenerate_testeng2_deck()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n❌ Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
