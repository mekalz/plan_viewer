#!/bin/bash
#
# Claude Code Hook: Plan Reviewer Notifier
#
# This hook notifies the Plan Reviewer browser UI when Claude Code
# creates or updates plans, or when a session stops.
#
# Installation:
#   Add to ~/.claude/settings.json under "hooks":
#
#   {
#     "hooks": {
#       "Stop": [
#         {
#           "type": "command",
#           "command": "bash /path/to/plan-reviewer/hooks/notify.sh stop"
#         }
#       ],
#       "PostToolUse": [
#         {
#           "type": "command",
#           "command": "bash /path/to/plan-reviewer/hooks/notify.sh tool"
#         }
#       ]
#     }
#   }

REVIEWER_PORT="${PLAN_REVIEWER_PORT:-3456}"
REVIEWER_URL="http://localhost:${REVIEWER_PORT}/api/hook-trigger"
EVENT_TYPE="${1:-unknown}"

# Read hook input from stdin (Claude Code sends JSON)
INPUT=$(cat)

# Extract relevant info
TOOL_NAME=""
if [ "$EVENT_TYPE" = "tool" ]; then
  TOOL_NAME=$(echo "$INPUT" | grep -o '"tool_name":"[^"]*"' | head -1 | cut -d'"' -f4 2>/dev/null)
fi

# Send notification to the reviewer (non-blocking, ignore errors)
curl -s -X POST "$REVIEWER_URL" \
  -H "Content-Type: application/json" \
  -d "{\"event\":\"$EVENT_TYPE\",\"tool\":\"$TOOL_NAME\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" \
  --connect-timeout 1 \
  --max-time 2 \
  > /dev/null 2>&1 &

# Output valid JSON for Claude Code hooks
echo '{"continue": true}'
