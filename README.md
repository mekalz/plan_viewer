# Plan Viewer

A browser-based viewer for Claude Code plans — view, annotate, and comment on plans directly from your browser.

## How It Works

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│                  │     │                  │     │                  │
│   Claude Code    │────▶│   Plan Viewer    │◀────│    Browser UI    │
│   (Terminal)     │     │  (Python Server) │     │  (localhost)     │
│                  │     │                  │     │                  │
│  Creates/updates │     │  Watches files   │     │  View plans      │
│  plan .md files  │     │  Serves UI       │     │  Add comments    │
│  Reads comments  │     │  Manages reviews │     │  Approve/reject  │
│  Revises plans   │     │  SSE live reload │     │  Mermaid render  │
│                  │     │                  │     │                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

### The Review Loop

1. **Claude Code** creates a plan in `~/.claude/plans/` (use plan mode: `Shift+Tab`)
2. **Plan Viewer** auto-detects the file and renders it in the browser with Mermaid diagrams
3. **You** review the plan — click section `+` buttons for section-level comments, or select text for inline comments (💬 Comment, 💡 Suggestion, ❓ Question, ✅ Approve, ❌ Reject)
4. Comments are **written back into the plan `.md` file** under a `## 📝 Review Comments` section
5. **Claude Code** reads the updated plan (it re-reads plan files), sees your comments, and revises accordingly
6. Tell Claude: *"Check the plan file for review comments and address them"*

## Quick Start

```bash
# Clone to your machine
git clone git@github.com:mekalz/plan_viewer.git ~/plan-viewer
cd ~/plan-viewer

# Run setup (creates dirs, installs hooks, appends CLAUDE.md, starts server)
bash setup.sh

# Open in browser
open http://localhost:3456
```

**That's it.** No pip install, no build step. Pure Python 3 standard library, zero dependencies.

The setup script handles everything automatically:
- Creates `~/.claude/plans/` and `~/.claude/plan-reviews/` directories
- Installs Claude Code hooks into `~/.claude/settings.json` (Stop + PostToolUse)
- Appends review instructions to `~/.claude/CLAUDE.md`
- Creates a sample plan for testing
- Starts the server on port 3456

To uninstall the hooks:

```bash
bash setup.sh --uninstall
```

## Manual Setup (Optional)

If you prefer not to run `setup.sh`, or need to configure things individually:

### 1. Directory Structure

The tool uses these directories:

| Path | Purpose |
|------|---------|
| `~/.claude/plans/` | Claude Code's plan files (auto-created) |
| `~/.claude/plan-reviews/` | Comment metadata storage (JSON) |

### 2. Claude Code Hooks

For real-time notifications when Claude finishes a task, add hooks to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/plan-viewer/notify.sh stop"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/plan-viewer/notify.sh tool"
          }
        ]
      }
    ]
  }
}
```

### 3. CLAUDE.md Integration

So Claude Code understands how to respond to your review comments, append the review instructions to your global CLAUDE.md:

```bash
cat ~/plan-viewer/CLAUDE.md >> ~/.claude/CLAUDE.md
```

This teaches Claude to:
- Recognize the `## 📝 Review Comments` section
- Understand comment types (approve/reject/suggestion/question)
- Respond appropriately to each type

## Usage Workflow

### Typical Session

```bash
# Terminal 1: Start the viewer
cd ~/plan-viewer && python3 server.py

# Terminal 2: Start Claude Code in plan mode
cd ~/my-project
claude
# Press Shift+Tab to switch to plan mode
# Ask: "Create an architecture plan for the auth system"

# Browser: http://localhost:3456
# Review the plan, add comments
# Back in Terminal 2:
# Tell Claude: "Read the review comments in the plan file and revise"
```

### Comment Types

| Type | Emoji | Effect |
|------|-------|--------|
| **Comment** | 💬 | General feedback for Claude to consider |
| **Suggestion** | 💡 | Specific change request with details |
| **Question** | ❓ | Claude should answer in the plan |
| **Approve** | ✅ | Section/plan is good, proceed |
| **Reject** | ❌ | Needs significant revision before proceeding |

### What Gets Written to Plan Files

When you add a section-level comment, it's appended under a Review Comments section:

```markdown
---

## 📝 Review Comments

### 💡 SUGGESTION (re: "Database Design")

> Consider using a composite index on (user_id, created_at)
> for the sessions table to optimize timeline queries.

_— Reviewer, 2026/01/15 15:30_
```

When you select text and add an inline comment, it's inserted right after the paragraph containing the selection:

```markdown
### 💬 COMMENT (on: "JWT-based session management")

> Have we considered token revocation strategies for compromised tokens?

_— Reviewer, 2026/01/15 15:35_
```

Claude Code reads these directly since they're part of the plan file.

## Features

- **Zero dependencies** — Pure Python 3 server, single HTML file
- **Live reload** — SSE-based, browser auto-updates when files change
- **Mermaid rendering** — Flowcharts, sequence diagrams, Gantt charts, etc.
- **Section-level comments** — Click the `+` button on any heading
- **Text-selection comments** — Select any text to add an inline comment with context
- **Comment highlighting** — Selected text with comments is highlighted in the content pane
- **Dark / Light themes** — Toggle with smooth transitions, persisted in localStorage
- **Syntax highlighting** — Code blocks highlighted via highlight.js (theme-aware)
- **Comment sidebar** — Comments displayed with linked context previews
- **Bidirectional comment sync** — JSON metadata and markdown blocks kept in sync
- **Hook integration** — Optional Claude Code hooks for real-time notifications
- **Auto-reconnect** — SSE connection auto-recovers on disconnect

## Architecture

```
plan-viewer/
├── server.py          # Python HTTP server (zero deps)
│                      #   - File watcher (polling ~1s interval)
│                      #   - SSE for live updates
│                      #   - REST API for plans & comments
│                      #   - Bidirectional comment sync (JSON ↔ markdown)
│
├── index.html         # Single-file frontend
│                      #   - marked.js for Markdown
│                      #   - beautiful-mermaid for diagrams
│                      #   - highlight.js for code
│                      #   - Text-selection + section-level comments
│
├── setup.sh           # One-click setup & uninstall
├── notify.sh          # Claude Code hook script
├── icon.svg           # Project logo
├── CLAUDE.md          # Review instructions for Claude Code
├── CONTRIBUTING.md    # Contribution guidelines
├── LICENSE            # MIT License
└── README.md
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serve frontend |
| `GET` | `/api/plans` | List all plans with metadata |
| `GET` | `/api/plans/:id` | Get plan content and comments |
| `POST` | `/api/plans/:id/comments` | Add a comment to a plan |
| `POST` | `/api/comments/:id/resolve` | Mark a comment as resolved |
| `POST` | `/api/comments/:id/delete` | Delete a comment |
| `GET` | `/api/events` | SSE stream for live updates |
| `GET` | `/api/session` | Latest Claude Code session info |
| `POST` | `/api/hook-trigger` | Receive hook notifications |

## Customization

### Change Port

```bash
PLAN_REVIEWER_PORT=8080 python3 server.py
# or
python3 server.py --port 8080
```

### Watch Additional Directories

The server watches `~/.claude/plans/` and `~/.claude/plan-reviews/` by default. You can modify `server.py` to watch project-specific plan directories.

## Limitations

- Comments are appended to plan files — the file grows over multiple review rounds
- No authentication (localhost only)
- Mermaid rendering depends on CDN availability (or bundle locally)
- Claude Code needs to be told to re-read the plan file for comments

## License

MIT
