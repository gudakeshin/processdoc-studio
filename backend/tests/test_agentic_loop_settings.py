#!/usr/bin/env python3
"""
Verify agentic loop settings load correctly.

Run as a script for full console diagnostics: ``python backend/tests/test_agentic_loop_settings.py``
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(_BACKEND_ROOT))


def run_diagnostic() -> None:
    from dotenv import load_dotenv

    print("=" * 80)
    print("AGENTIC LOOP SETTINGS DIAGNOSTIC")
    print("=" * 80)

    backend_root = _BACKEND_ROOT
    repo_root = _REPO_ROOT

    print(f"\n📁 Repository root: {repo_root}")
    print(f"📁 Backend root: {backend_root}")

    print("\n📄 Loading .env files...")
    print(f"  1. Root: {repo_root / '.env'}")
    load_dotenv(repo_root / ".env")
    print("     ✓ Loaded")

    print(f"  2. Backend: {backend_root / '.env'}")
    load_dotenv(backend_root / ".env", override=True)
    print("     ✓ Loaded (override=True)")

    print("\n🔍 Checking environment variables...")
    coordinator_agentic = os.getenv("COORDINATOR_AGENTIC_LOOP_ENABLED", "NOT_SET")
    subprocess_execution = os.getenv("SUBPROCESS_EXECUTION_ENABLED", "NOT_SET")

    print(f"  COORDINATOR_AGENTIC_LOOP_ENABLED = {coordinator_agentic}")
    print(f"  SUBPROCESS_EXECUTION_ENABLED = {subprocess_execution}")

    print("\n⚙️  Loading Settings object...")
    try:
        from app.core.config import settings

        print("  ✓ Settings imported successfully")

        print("\n📊 Settings object values:")
        print(
            f"  coordinator_agentic_loop_enabled = {settings.coordinator_agentic_loop_enabled} "
            f"(type: {type(settings.coordinator_agentic_loop_enabled).__name__})"
        )
        print(
            f"  subprocess_execution_enabled = {settings.subprocess_execution_enabled} "
            f"(type: {type(settings.subprocess_execution_enabled).__name__})"
        )

        print("\n🔎 All 'coordinator' attributes in settings:")
        coordinator_attrs = [attr for attr in dir(settings) if "coordinator" in attr.lower()]
        if coordinator_attrs:
            for attr in coordinator_attrs:
                value = getattr(settings, attr, "ERROR")
                print(f"    - {attr}: {value}")
        else:
            print("    (none found)")

        print("\n🧪 Testing boolean conversion:")
        agentic_enabled = bool(settings.coordinator_agentic_loop_enabled)
        print(f"  bool(settings.coordinator_agentic_loop_enabled) = {agentic_enabled}")

        if agentic_enabled:
            print("\n✅ RESULT: AGENTIC LOOP WOULD BE ENABLED")
        else:
            print("\n❌ RESULT: AGENTIC LOOP WOULD BE DISABLED (old path)")
            print("\n⚠️  DIAGNOSIS:")
            print("   The setting is False, but should be True.")
            print("   Possible causes:")
            print("   1. Environment variable not properly loaded from .env")
            print("   2. Settings object not reading from environment")
            print("   3. Field name mismatch between .env and config.py")

    except Exception as e:
        print(f"  ❌ Error loading settings: {e}")
        traceback.print_exc()

    print("\n" + "=" * 80)


def test_agentic_loop_settings_paths_resolve() -> None:
    """Smoke: this test module resolves repo and backend roots used by diagnostics."""
    assert (_REPO_ROOT / "README.md").is_file()
    assert (_BACKEND_ROOT / "app").is_dir()
    assert (_BACKEND_ROOT / "app" / "core").is_dir()


if __name__ == "__main__":
    run_diagnostic()
