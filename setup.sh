#!/bin/bash
#
# Claude Code Plan Reviewer - Setup Script
#
# This script:
# 1. Creates necessary directories
# 2. Auto-installs hooks in Claude Code settings
# 3. Copies plan_viewer.md and adds reference in CLAUDE.md
# 4. Creates a sample plan for testing
# 5. Starts the Python server
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
PLANS_DIR="$CLAUDE_DIR/plans"
REVIEWS_DIR="$CLAUDE_DIR/plan-reviews"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"
PORT="${PLAN_REVIEWER_PORT:-3456}"

# ── Uninstall mode ──
if [ "${1:-}" = "--uninstall" ]; then
  echo "🗑  Uninstalling Plan Reviewer hooks..."
  python3 - "$SETTINGS_FILE" "$SCRIPT_DIR/notify.sh" << 'PYEOF'
import json, sys, os

settings_file = sys.argv[1]
notify_script = sys.argv[2]

if not os.path.exists(settings_file):
    print("   No settings file found, nothing to do.")
    sys.exit(0)

with open(settings_file, "r") as f:
    settings = json.load(f)

hooks = settings.get("hooks", {})
removed = False
for event_name in list(hooks.keys()):
    entries = hooks[event_name]
    filtered = []
    for e in entries:
        keep = True
        for h in e.get("hooks", []):
            if isinstance(h, dict) and notify_script in h.get("command", ""):
                keep = False
                removed = True
        if keep:
            filtered.append(e)
    if filtered:
        hooks[event_name] = filtered
    else:
        del hooks[event_name]

if not hooks:
    settings.pop("hooks", None)

with open(settings_file, "w") as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)

if removed:
    print("   ✓ Hooks removed from " + settings_file)
else:
    print("   No plan reviewer hooks found.")
PYEOF
  echo "   Done. Restart Claude Code for changes to take effect."
  exit 0
fi

echo "╔══════════════════════════════════════════════════════╗"
echo "║  🔍 Claude Code Plan Reviewer - Setup               ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# 0. Check Python3
if ! command -v python3 &>/dev/null; then
  echo "❌ python3 not found. Please install Python 3.8+."
  exit 1
fi
echo "   ✓ Python3 found: $(python3 --version)"

# 1. Create directories
echo ""
echo "📁 Creating directories..."
mkdir -p "$PLANS_DIR"
mkdir -p "$REVIEWS_DIR"
echo "   ✓ $PLANS_DIR"
echo "   ✓ $REVIEWS_DIR"

# 2. Make hook executable
chmod +x "$SCRIPT_DIR/notify.sh"
echo "   ✓ Hook script is executable"

# 3. Generate hooks settings file
#    Claude Code has no CLI command for managing hooks (unlike `claude mcp add`).
#    The `/hooks` menu is interactive and not scriptable.
#    So we generate a hooks JSON file and merge it into ~/.claude/settings.json.
#    Run `./setup.sh --uninstall` to cleanly remove the hooks.
echo ""
echo "🔗 Installing hooks into Claude Code settings..."

HOOK_STOP="bash $SCRIPT_DIR/notify.sh stop"
HOOK_TOOL="bash $SCRIPT_DIR/notify.sh tool"

python3 - "$SETTINGS_FILE" "$HOOK_STOP" "$HOOK_TOOL" << 'PYEOF'
import json, sys, os

settings_file = sys.argv[1]
hook_stop = sys.argv[2]
hook_tool = sys.argv[3]

# Load or create settings
settings = {}
if os.path.exists(settings_file):
    with open(settings_file, "r") as f:
        try:
            settings = json.load(f)
        except json.JSONDecodeError:
            import shutil
            shutil.copy2(settings_file, settings_file + ".bak")
            print(f"   ⚠ Backed up corrupted settings to {settings_file}.bak")
            settings = {}

hooks = settings.setdefault("hooks", {})

def ensure_hook(event_name, command):
    """Add a hook entry using the current Claude Code format.
    See https://code.claude.com/docs/en/hooks for the schema.
    """
    entries = hooks.setdefault(event_name, [])
    for e in entries:
        if isinstance(e, dict):
            for h in e.get("hooks", []):
                if isinstance(h, dict) and h.get("command") == command:
                    return False
    entries.append({"hooks": [{"type": "command", "command": command}]})
    return True

added_stop = ensure_hook("Stop", hook_stop)
added_tool = ensure_hook("PostToolUse", hook_tool)

with open(settings_file, "w") as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)

if added_stop or added_tool:
    print("   ✓ Hooks installed in " + settings_file)
else:
    print("   ✓ Hooks already present (skipped)")
PYEOF

# 4. Copy plan_viewer.md and add reference in CLAUDE.md
echo ""
echo "📝 CLAUDE.md integration..."

cp "$SCRIPT_DIR/plan_viewer.md" "$CLAUDE_DIR/plan_viewer.md"
echo "   ✓ Copied plan_viewer.md to $CLAUDE_DIR/plan_viewer.md"

REFERENCE_LINE="Read ~/.claude/plan_viewer.md for Plan Viewer integration instructions."
if [ -f "$CLAUDE_MD" ] && grep -qF "$REFERENCE_LINE" "$CLAUDE_MD"; then
  echo "   ✓ Reference already in CLAUDE.md (skipped)"
else
  echo "" >> "$CLAUDE_MD"
  echo "$REFERENCE_LINE" >> "$CLAUDE_MD"
  echo "   ✓ Added reference to $CLAUDE_MD"
fi

# 5. Create a sample plan for testing
SAMPLE_PLAN="$PLANS_DIR/sample-architecture-plan.md"
if [ ! -f "$SAMPLE_PLAN" ]; then
  echo ""
  echo "📄 Creating sample plan for testing..."
  cat > "$SAMPLE_PLAN" << 'PLAN_EOF'
# Architecture Plan: User Authentication System

## Overview

Design and implement a secure authentication system supporting OAuth2, 
JWT tokens, and multi-factor authentication (MFA).

## Goals

- Support email/password and social login (Google, GitHub)
- Implement JWT-based session management
- Add TOTP-based MFA as an optional security layer
- Maintain sub-200ms authentication response times

## System Architecture

```mermaid
flowchart TD
    Client[Client App] --> Gateway[API Gateway]
    Gateway --> AuthService[Auth Service]
    AuthService --> UserDB[(User Database)]
    AuthService --> TokenStore[(Token Store / Redis)]
    AuthService --> MFAService[MFA Service]
    
    Gateway --> OAuthProvider[OAuth Providers]
    OAuthProvider --> Google[Google OAuth]
    OAuthProvider --> GitHub[GitHub OAuth]
    
    AuthService --> EventBus[Event Bus]
    EventBus --> AuditLog[Audit Logger]
    EventBus --> NotifService[Notification Service]
```

## Database Design

### Users Table

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| email | VARCHAR(255) | Unique, indexed |
| password_hash | VARCHAR(255) | bcrypt |
| mfa_enabled | BOOLEAN | Default false |
| mfa_secret | VARCHAR(255) | Encrypted TOTP secret |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### Sessions Table

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| user_id | UUID | Foreign key |
| token_hash | VARCHAR(255) | SHA-256 of JWT |
| expires_at | TIMESTAMP | |
| ip_address | INET | |

## API Endpoints

### POST /auth/login
- Accept email + password
- Return JWT access token + refresh token
- Set httpOnly cookie for refresh token

### POST /auth/oauth/callback
- Handle OAuth2 callback
- Create or link user account
- Return JWT tokens

### POST /auth/mfa/verify
- Verify TOTP code
- Upgrade session to MFA-verified

### POST /auth/refresh
- Accept refresh token
- Return new access token

## Security Considerations

1. **Rate Limiting**: 5 login attempts per minute per IP
2. **Token Rotation**: Refresh tokens are single-use
3. **Password Policy**: Minimum 12 chars, breach database check
4. **Audit Logging**: All auth events logged with IP and user-agent

## Implementation Timeline

```mermaid
gantt
    title Authentication System Implementation
    dateFormat  YYYY-MM-DD
    section Core Auth
    User model & DB setup    :a1, 2026-02-01, 3d
    Login/Register endpoints :a2, after a1, 4d
    JWT token service        :a3, after a1, 3d
    section OAuth
    OAuth2 integration       :b1, after a2, 5d
    Google provider          :b2, after b1, 2d
    GitHub provider          :b3, after b2, 2d
    section MFA
    TOTP implementation      :c1, after a3, 4d
    MFA enrollment flow      :c2, after c1, 3d
    section Testing
    Integration tests        :d1, after b3, 5d
    Security audit           :d2, after d1, 3d
```

## Open Questions

- Should we support WebAuthn/passkeys in v1 or defer to v2?
- Redis cluster vs single instance for token store?
- Self-hosted vs managed OAuth (Auth0/Clerk)?
PLAN_EOF
  echo "   ✓ Created sample plan: $SAMPLE_PLAN"
fi

# 6. Kill existing server on the same port
EXISTING_PID=$(lsof -ti :"$PORT" 2>/dev/null)
if [ -n "$EXISTING_PID" ]; then
  echo "🔄 Stopping existing server on port $PORT (PID $EXISTING_PID)..."
  kill "$EXISTING_PID" 2>/dev/null
  sleep 1
  echo "   ✓ Stopped"
fi

# 7. Start server
echo ""
echo "🚀 Starting Plan Reviewer server..."
echo ""
python3 "$SCRIPT_DIR/server.py" --port "$PORT"
