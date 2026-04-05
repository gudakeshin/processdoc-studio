#!/usr/bin/env python3
"""
Diagnostic script to test if .env loading works correctly.
Run this from the backend directory: python test_env_loading.py
"""

import os
import sys
from pathlib import Path

print("=" * 80)
print("ENV LOADING DIAGNOSTIC")
print("=" * 80)

# Show current working directory
print(f"\n1. Current working directory: {os.getcwd()}")

# Show Python version
print(f"2. Python version: {sys.version}")

# Check if dotenv is installed
try:
    from dotenv import load_dotenv
    print("3. ✓ dotenv module is installed")
except ImportError:
    print("3. ✗ dotenv module NOT found!")
    sys.exit(1)

# Show what we're about to load
backend_dir = Path(__file__).parent
repo_root = backend_dir.parent

print(f"\n4. Backend directory: {backend_dir}")
print(f"5. Repo root: {repo_root}")

backend_env_path = backend_dir / ".env"
root_env_path = repo_root / ".env"

print(f"\n6. Root .env exists: {root_env_path.exists()}")
if root_env_path.exists():
    with open(root_env_path) as f:
        print(f"   Content (first 10 lines):")
        for i, line in enumerate(f):
            if i >= 10:
                break
            if "COORDINATOR" in line or "SUBPROCESS" in line:
                print(f"   {line.rstrip()}")

print(f"\n7. Backend .env exists: {backend_env_path.exists()}")
if backend_env_path.exists():
    with open(backend_env_path) as f:
        print(f"   Content (looking for COORDINATOR_AGENTIC_LOOP_ENABLED):")
        for line in f:
            if "COORDINATOR_AGENTIC_LOOP_ENABLED" in line or "SUBPROCESS_EXECUTION_ENABLED" in line:
                print(f"   {line.rstrip()}")

# Check what env vars are currently set
print(f"\n8. Current os.environ state:")
print(f"   COORDINATOR_AGENTIC_LOOP_ENABLED = {os.getenv('COORDINATOR_AGENTIC_LOOP_ENABLED', 'NOT SET')}")
print(f"   SUBPROCESS_EXECUTION_ENABLED = {os.getenv('SUBPROCESS_EXECUTION_ENABLED', 'NOT SET')}")

# Now load the .env files
print(f"\n9. Loading .env files...")
print(f"   load_dotenv({root_env_path}, override=False)")
result1 = load_dotenv(root_env_path, override=False)
print(f"   Result: {result1}")

print(f"   load_dotenv({backend_env_path}, override=True)")
result2 = load_dotenv(backend_env_path, override=True)
print(f"   Result: {result2}")

# Check what env vars are now set
print(f"\n10. After load_dotenv():")
coordinator_value = os.getenv('COORDINATOR_AGENTIC_LOOP_ENABLED', 'NOT SET')
subprocess_value = os.getenv('SUBPROCESS_EXECUTION_ENABLED', 'NOT SET')
print(f"    COORDINATOR_AGENTIC_LOOP_ENABLED = {coordinator_value}")
print(f"    SUBPROCESS_EXECUTION_ENABLED = {subprocess_value}")

# Parse the boolean value
print(f"\n11. Boolean parsing:")
env_var = os.getenv("COORDINATOR_AGENTIC_LOOP_ENABLED", "false").lower().strip()
agentic_from_env = env_var in ("true", "1", "yes", "on")
print(f"    Raw value: '{coordinator_value}'")
print(f"    Lowercased & stripped: '{env_var}'")
print(f"    Is in ('true', '1', 'yes', 'on'): {agentic_from_env}")

print("\n" + "=" * 80)
if agentic_from_env:
    print("✓ SUCCESS: COORDINATOR_AGENTIC_LOOP_ENABLED would be True")
else:
    print("✗ FAILED: COORDINATOR_AGENTIC_LOOP_ENABLED would be False")
print("=" * 80)
