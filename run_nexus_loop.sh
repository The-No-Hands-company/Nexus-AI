#!/usr/bin/env bash
set -euo pipefail

# ── Nexus AI Autonomous Loop Bootstrap ──────────────────────────────────────
# Persists progress across context window resets. If the agent crashes or
# hits a token limit, a fresh instance picks up where the last one left off
# by reading LOOP_STATE.md from disk.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_FILE="$SCRIPT_DIR/LOOP_STATE.md"
BACKEND_URL="${NEXUS_URL:-http://localhost:8000}"
MAX_CYCLES="${MAX_CYCLES:-50}"
COOLDOWN="${COOLDOWN_SECONDS:-10}"

echo "══════════════════════════════════════════════════════════════"
echo "  Nexus AI Autonomous Loop Engine"
echo "  Backend: $BACKEND_URL"
echo "  Max cycles: $MAX_CYCLES"
echo "  State file: $STATE_FILE"
echo "══════════════════════════════════════════════════════════════"

# Initialize state if it doesn't exist
if [ ! -f "$STATE_FILE" ]; then
  cat > "$STATE_FILE" <<'EOF'
# Nexus Loop State
status: IDLE
current_target: none
cycle_count: 0
last_updated:
history: []
EOF
  echo "📝 Created fresh LOOP_STATE.md"
fi

# Check backend health
check_backend() {
  curl -sf --max-time 5 "$BACKEND_URL/health" > /dev/null 2>&1
}

# Wait for backend if not running
if ! check_backend; then
  echo "⏳ Backend not reachable. Starting Nexus AI..."
  cd "$SCRIPT_DIR" && python main.py &
  sleep 8
  if ! check_backend; then
    echo "❌ Backend failed to start. Check logs."
    exit 1
  fi
fi

echo "✅ Backend healthy at $BACKEND_URL"

# ── Main Loop ────────────────────────────────────────────────────────────────
cycle=0
while [ $cycle -lt $MAX_CYCLES ]; do
  cycle=$((cycle + 1))
  echo ""
  echo "──────────────────────────────────────────────────────────"
  echo "  🔄 CYCLE $cycle / $MAX_CYCLES — $(date '+%H:%M:%S')"
  echo "──────────────────────────────────────────────────────────"

  # Check if all tasks are complete
  if grep -q "status: COMPLETED_ALL" "$STATE_FILE" 2>/dev/null; then
    echo "✅ All roadmap tasks completed. Exiting."
    break
  fi

  # Update cycle count in state
  if command -v python3 &>/dev/null; then
    python3 -c "
import re, datetime
with open('$STATE_FILE', 'r') as f:
    content = f.read()
content = re.sub(r'cycle_count: \d+', f'cycle_count: $cycle', content)
content = re.sub(r'last_updated: .*', f'last_updated: {datetime.datetime.utcnow().isoformat()}Z', content)
content = re.sub(r'status: IDLE', 'status: RUNNING', content)
with open('$STATE_FILE', 'w') as f:
    f.write(content)
" 2>/dev/null || true
  fi

  # Read current state and determine next action
  CURRENT_TARGET=$(grep "current_target:" "$STATE_FILE" 2>/dev/null | cut -d: -f2- | xargs || echo "none")
  CURRENT_STATUS=$(grep "status:" "$STATE_FILE" 2>/dev/null | head -1 | cut -d: -f2- | xargs || echo "IDLE")

  echo "  Status: $CURRENT_STATUS | Target: $CURRENT_TARGET"

  # ── Phase 1: Triage — find next feature to work on ───────────────────────
  if [ "$CURRENT_STATUS" = "RUNNING" ] && [ "$CURRENT_TARGET" != "none" ]; then
    echo "  📋 Resuming work on: $CURRENT_TARGET"
  else
    echo "  🔍 Triaging backlog for next feature..."
    # Use nostack classify + sprint to pick the next feature
    curl -sf --max-time 10 -X POST "$BACKEND_URL/nostack/skills/classify" \
      -H "Content-Type: application/json" \
      -d '{"task": "Read ROADMAP.md and identify the highest priority unimplemented feature"}' \
      > /dev/null 2>&1 || true
  fi

  # ── Phase 2: Run the sprint ──────────────────────────────────────────────
  # The sprint uses nostack skills: plan → implement → verify → review → ship
  # Each skill persists state in LOOP_STATE.md so crashes don't lose progress

  echo "  🚀 Launching development sprint..."
  SPRINT_RESPONSE=$(curl -sf --max-time 10 -X POST "$BACKEND_URL/nostack/sprint" \
    -H "Content-Type: application/json" \
    -d "{
      \"task\": \"$CURRENT_TARGET\",
      \"template\": \"feature\"
    }" 2>&1) || SPRINT_RESPONSE=""

  if echo "$SPRINT_RESPONSE" | grep -q "sprint_id"; then
    SPRINT_ID=$(echo "$SPRINT_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('sprint_id',''))" 2>/dev/null || echo "")
    echo "  Sprint started: $SPRINT_ID"

    # Poll sprint status
    POLLS=0
    while [ $POLLS -lt 120 ]; do
      POLLS=$((POLLS + 1))
      sleep 5
      STATUS=$(curl -sf --max-time 5 "$BACKEND_URL/nostack/sprint/$SPRINT_ID" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','running'))" 2>/dev/null || echo "running")
      case "$STATUS" in
        completed)
          echo "  ✅ Sprint completed successfully."
          break
          ;;
        failed|crashed|cancelled)
          echo "  ⚠️ Sprint $STATUS at $(date '+%H:%M:%S'). Will retry."
          break
          ;;
        *)
          if [ $((POLLS % 6)) -eq 0 ]; then
            echo "  ⏳ Sprint running... ($((POLLS * 5))s)"
          fi
          ;;
      esac
    done
  else
    echo "  ⚠️ Sprint API unavailable. Will retry next cycle."
  fi

  # ── Phase 3: Cooldown ────────────────────────────────────────────────────
  echo "  💤 Cooling down for ${COOLDOWN}s..."
  sleep "$COOLDOWN"
done

echo ""
echo "══════════════════════════════════════════════════════════════"
echo "  Loop engine finished after $cycle cycles."
echo "  Final status: $(grep 'status:' "$STATE_FILE" 2>/dev/null | head -1 || echo 'unknown')"
echo "══════════════════════════════════════════════════════════════"
