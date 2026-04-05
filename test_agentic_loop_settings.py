#!/usr/bin/env python3
"""
Test script to verify agentic loop settings are being loaded correctly.
Run this before starting the backend to diagnose configuration issues.
"""

import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

print("=" * 80)
print("AGENTIC LOOP SETTINGS DIAGNOSTIC")
print("=" * 80)

# Load dotenv like the app does
from dotenv import load_dotenv

repo_root = Path(__file__).parent
backend_root = repo_root / "backend"

print(f"\n📁 Repository root: {repo_root}")
print(f"📁 Backend root: {backend_root}")

print(f"\n📄 Loading .env files...")
print(f"  1. Root: {repo_root / '.env'}")
load_dotenv(repo_root / ".env")
print(f"     ✓ Loaded")

print(f"  2. Backend: {backend_root / '.env'}")
load_dotenv(backend_root / ".env", override=True)
print(f"     ✓ Loaded (override=True)")

print(f"\n🔍 Checking environment variables...")
coordinator_agentic = os.getenv("COORDINATOR_AGENTIC_LOOP_ENABLED", "NOT_SET")
subprocess_execution = os.getenv("SUBPROCESS_EXECUTION_ENABLED", "NOT_SET")

print(f"  COORDINATOR_AGENTIC_LOOP_ENABLED = {coordinator_agentic}")
print(f"  SUBPROCESS_EXECUTION_ENABLED = {subprocess_execution}")

print(f"\n⚙️  Loading Settings object...")
try:
    from app.core.config import Settings, settings
    print(f"  ✓ Settings imported successfully")

    print(f"\n📊 Settings object values:")
    print(f"  coordinator_agentic_loop_enabled = {settings.coordinator_agentic_loop_enabled} (type: {type(settings.coordinator_agentic_loop_enabled).__name__})")
    print(f"  subprocess_execution_enabled = {settings.subprocess_execution_enabled} (type: {type(settings.subprocess_execution_enabled).__name__})")

    print(f"\n🔎 All 'coordinator' attributes in settings:")
    coordinator_attrs = [attr for attr in dir(settings) if 'coordinator' in attr.lower()]
    if coordinator_attrs:
        for attr in coordinator_attrs:
            value = getattr(settings, attr, "ERROR")
            print(f"    - {attr}: {value}")
    else:
        print(f"    (none found)")

    # Test the boolean conversion
    print(f"\n🧪 Testing boolean conversion:")
    agentic_enabled = bool(settings.coordinator_agentic_loop_enabled)
    print(f"  bool(settings.coordinator_agentic_loop_enabled) = {agentic_enabled}")

    if agentic_enabled:
        print(f"\n✅ RESULT: AGENTIC LOOP WOULD BE ENABLED")
    else:
        print(f"\n❌ RESULT: AGENTIC LOOP WOULD BE DISABLED (old path)")
        print(f"\n⚠️  DIAGNOSIS:")
        print(f"   The setting is False, but should be True.")
        print(f"   Possible causes:")
        print(f"   1. Environment variable not properly loaded from .env")
        print(f"   2. Settings object not reading from environment")
        print(f"   3. Field name mismatch between .env and config.py")

except Exception as e:
    print(f"  ❌ Error loading settings: {e}")
    import traceback
    traceback.print_exc()

print(f"\n" + "=" * 80)
