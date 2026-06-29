#!/usr/bin/env bash
# ── Nexus AI Autonomous Loop Bootstrap ──────────────────────────────────────
# Wraps the Python loop engine with crash-resume capability.
# If the Python process crashes, it restarts and reads LOOP_STATE.md to resume.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOOP_ENGINE="$SCRIPT_DIR/nostack/bin/nexus-loop"

if [ ! -f "$LOOP_ENGINE" ]; then
  echo "❌ Loop engine not found at $LOOP_ENGINE"
  exit 1
fi

echo "🚀 Launching Nexus Autonomous Loop Engine..."
echo "   Engine: $LOOP_ENGINE"
echo "   State:  $SCRIPT_DIR/LOOP_STATE.md"

cd "$SCRIPT_DIR"
exec python3 "$LOOP_ENGINE"
