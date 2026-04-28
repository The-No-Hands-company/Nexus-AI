#!/usr/bin/env python3
"""
FEATURE_INVENTORY_CORRECTIONS_SCRIPT.py

This script applies corrections identified in the 2026-04-17 audit.
It reclassifies 332 items from [x] to [ ] where no code pointers exist.

IMPORTANT: Run this in the Nexus AI workspace root directory.
BACKUP: Creates FEATURE_INVENTORY.md.backup before modifying.

Usage:
    python3 docs/FEATURE_INVENTORY_CORRECTIONS_SCRIPT.py
"""

import re
import shutil
from pathlib import Path

INVENTORY_FILE = Path("docs/FEATURE_INVENTORY.md")
BACKUP_FILE = Path("docs/FEATURE_INVENTORY.md.backup")

def has_code_pointer(line: str) -> bool:
    """Check if a line has a code pointer (Pointers: ... or module= ...)"""
    return "Pointers:" in line or "module=" in line or "tool=" in line

def should_reclassify(line: str, next_lines: list[str], index: int) -> bool:
    """
    Determine if a [x] item should be reclassified to [ ]
    
    Rules:
    - Must be marked [x]
    - Must NOT have code pointer on this line
    - If next line is continuation (starts with spaces), check it too
    - Unless it's in the list of 24 known working items
    """
    if not line.strip().startswith("- [x]"):
        return False
    
    # Check if this line or continuation has code pointers
    if has_code_pointer(line):
        return False
    
    # Check next line if it's a continuation
    if index + 1 < len(next_lines):
        next_line = next_lines[index + 1]
        if next_line.startswith("  ") and has_code_pointer(next_line):
            return False
    
    # Known working items - keep as [x]
    known_working = [
        "FastAPI application factory",
        "main.py entry-point",
        "CORS middleware",
        "Static file serving",
        "Startup / shutdown event hooks",
        "Environment variable configuration",
        "Docker Compose",
        "Railway deploy",
        "Health check endpoint",
        "System resource endpoint",
        "SQLite default backend",
        "PostgreSQL backend",
        "Chat history table",
        "Usage records table",
        "User accounts table",
        "JWT-based authentication",
        "POST /auth/register",
        "POST /auth/login",
        "GET /auth/me",
        "GET /admin/users",
        "PATCH /admin/users",
        "MULTI_USER=false",
        "POST /auth/logout",
        "POST /auth/refresh",
    ]
    
    for item in known_working:
        if item.lower() in line.lower():
            return False
    
    return True

def apply_corrections():
    """Apply corrections to FEATURE_INVENTORY.md"""
    
    if not INVENTORY_FILE.exists():
        print(f"ERROR: {INVENTORY_FILE} not found")
        return False
    
    # Create backup
    print(f"Creating backup: {BACKUP_FILE}")
    shutil.copy(INVENTORY_FILE, BACKUP_FILE)
    
    # Read file
    with open(INVENTORY_FILE, 'r') as f:
        lines = f.readlines()
    
    # Process lines
    reclassified_count = 0
    modified_lines = []
    
    for i, line in enumerate(lines):
        if should_reclassify(line, lines, i):
            # Change [x] to [ ]
            modified_line = line.replace("- [x]", "- [ ]", 1)
            modified_lines.append(modified_line)
            reclassified_count += 1
            
            # Add audit comment if not already present
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if not next_line.strip().startswith("<!-- Audit"):
                    # Insert comment on next line
                    pass
        else:
            modified_lines.append(line)
    
    # Write corrected file
    with open(INVENTORY_FILE, 'w') as f:
        f.writelines(modified_lines)
    
    print(f"✓ Reclassified {reclassified_count} items from [x] to [ ]")
    print(f"✓ Modified file: {INVENTORY_FILE}")
    print(f"✓ Backup saved: {BACKUP_FILE}")
    
    return True

if __name__ == "__main__":
    print("Nexus AI Feature Inventory Audit Corrections")
    print("=" * 50)
    print()
    
    success = apply_corrections()
    
    if success:
        print()
        print("NEXT STEPS:")
        print("1. Review the changes: git diff docs/FEATURE_INVENTORY.md")
        print("2. Test: pytest tests/")
        print("3. Commit: git add docs/FEATURE_INVENTORY.md && git commit -m 'audit: correct inventory status from audit findings'")
        print("4. If issues, restore: cp docs/FEATURE_INVENTORY.md.backup docs/FEATURE_INVENTORY.md")
    else:
        print("ERROR: Corrections failed")
