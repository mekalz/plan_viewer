#!/usr/bin/env python3
"""
Claude Code Plan Reviewer — Local Server

A zero-dependency Python server that:
  1. Watches ~/.claude/plans/ for plan files
  2. Serves a browser UI for reviewing plans with Mermaid rendering
  3. Accepts inline comments/annotations
  4. Writes comments back into plan .md files for Claude Code to read
  5. Pushes live updates to the browser via SSE

Usage:
    python3 server.py [--port 3456]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import string
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
from urllib.parse import urlparse, unquote

# ── Configuration ────────────────────────────────────────────

CLAUDE_DIR = Path.home() / ".claude"
PLANS_DIR = CLAUDE_DIR / "plans"
COMMENTS_DIR = CLAUDE_DIR / "plan-reviews"
INDEX_HTML = Path(__file__).parent / "index.html"

# ── SSE Client Registry ─────────────────────────────────────

sse_clients: list = []
sse_lock = threading.Lock()


def broadcast_sse(event: str, data: dict):
    msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    with sse_lock:
        dead = []
        for wfile in sse_clients:
            try:
                wfile.write(msg.encode())
                wfile.flush()
            except Exception:
                dead.append(wfile)
        for w in dead:
            sse_clients.remove(w)


# ── File Watcher (polling, no dependencies) ──────────────────

class FileWatcher(threading.Thread):
    """Polls directories for .md file changes and broadcasts SSE events."""

    def __init__(self, dirs: list[Path], interval: float = 1.0):
        super().__init__(daemon=True)
        self.dirs = dirs
        self.interval = interval
        self._snapshots: dict[Path, dict[str, float]] = {}
        for d in dirs:
            self._snapshots[d] = self._scan(d)

    @staticmethod
    def _scan(directory: Path) -> dict[str, float]:
        result = {}
        if directory.is_dir():
            for f in directory.iterdir():
                if f.suffix == ".md":
                    try:
                        result[f.name] = f.stat().st_mtime
                    except OSError:
                        pass
        return result

    def run(self):
        while True:
            time.sleep(self.interval)
            for d in self.dirs:
                current = self._scan(d)
                prev = self._snapshots.get(d, {})
                # Detect new or modified files
                for name, mtime in current.items():
                    if name not in prev or prev[name] != mtime:
                        broadcast_sse("file-change", {
                            "dir": d.name, "file": name, "event": "change"
                        })
                # Detect deleted files
                for name in set(prev) - set(current):
                    broadcast_sse("file-change", {
                        "dir": d.name, "file": name, "event": "delete"
                    })
                self._snapshots[d] = current


# ── Plan & Comment Operations ────────────────────────────────

def list_plans() -> list[dict]:
    plans = []
    if PLANS_DIR.is_dir():
        for f in PLANS_DIR.iterdir():
            if f.suffix == ".md":
                stat = f.stat()
                comments = load_comments(f.name)
                plans.append({
                    "id": f.stem,
                    "name": f.name,
                    "path": str(f),
                    "content": f.read_text(encoding="utf-8", errors="replace"),
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "size": stat.st_size,
                    "commentCount": len(comments),
                    "source": "plans",
                })
    plans.sort(key=lambda p: p["modified"], reverse=True)
    return plans


def get_plan(plan_id: str) -> dict | None:
    fp = PLANS_DIR / f"{plan_id}.md"
    if not fp.exists():
        return None
    stat = fp.stat()
    content = fp.read_text(encoding="utf-8", errors="replace")
    comments = sync_comments_with_plan(plan_id, content)
    return {
        "id": plan_id,
        "name": fp.name,
        "path": str(fp),
        "content": content,
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "comments": comments,
    }


def comments_file(plan_filename: str) -> Path:
    return COMMENTS_DIR / plan_filename.replace(".md", ".comments.json")


def load_comments(plan_filename: str) -> list[dict]:
    cf = comments_file(plan_filename)
    if not cf.exists():
        return []
    try:
        return json.loads(cf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_comments(plan_filename: str, comments: list[dict]):
    cf = comments_file(plan_filename)
    cf.write_text(json.dumps(comments, indent=2, ensure_ascii=False), encoding="utf-8")


def build_comment_block(comment: dict) -> str:
    """Reconstruct the markdown block that was injected into the plan file."""
    type_emoji = {
        "comment": "\U0001f4ac",
        "suggestion": "\U0001f4a1",
        "question": "\u2753",
        "approve": "\u2705",
        "reject": "\u274c",
    }
    emoji = type_emoji.get(comment.get("type", "comment"), "\U0001f4ac")

    selected_text = comment.get("selectedText", "")

    block = f'### {emoji} {comment.get("type", "comment").upper()}'
    if selected_text:
        excerpt = selected_text[:80] + ("..." if len(selected_text) > 80 else "")
        block += f' (on: "{excerpt}")'
    elif comment.get("sectionTitle"):
        block += f' (re: "{comment["sectionTitle"]}")'
    if comment.get("lineNumber"):
        block += f' [Line {comment["lineNumber"]}]'

    quoted_text = "\n> ".join(comment.get("text", "").split("\n"))
    block += f"\n\n> {quoted_text}\n\n"

    ts = datetime.fromisoformat(comment["createdAt"]).strftime("%Y/%m/%d %H:%M")
    block += f"_\u2014 Reviewer, {ts}_\n\n"
    return block


def parse_comments_from_plan(plan_id: str, content: str) -> list[dict]:
    """Parse comment blocks from the plan .md file into structured dicts."""
    type_by_emoji = {
        "\U0001f4ac": "comment",
        "\U0001f4a1": "suggestion",
        "\u2753": "question",
        "\u2705": "approve",
        "\u274c": "reject",
    }

    # Match comment blocks: ### {emoji} TYPE [optional context]\n[\n]> text\n\n_— Reviewer, timestamp_
    pattern = (
        r'### (' + '|'.join(re.escape(e) for e in type_by_emoji) + r') (\w+)'
        r'(?: \(on: "(.+?)"\))?'
        r'(?: \(re: "(.+?)"\))?'
        r'(?: \[Line (\d+)\])?'
        r'\n\n?((?:>.*\n)+)\n'
        r'_\u2014 Reviewer, (\d{4}/\d{2}/\d{2} \d{2}:\d{2})_'
    )

    found = []
    for m in re.finditer(pattern, content):
        emoji = m.group(1)
        comment_type = type_by_emoji.get(emoji, "comment")
        on_text = m.group(3) or ""
        re_section = m.group(4) or ""
        line_num = int(m.group(5)) if m.group(5) else None
        raw_quoted = m.group(6)
        ts_str = m.group(7)

        # Strip "> " or ">" prefix from each line
        lines = []
        for line in raw_quoted.rstrip("\n").split("\n"):
            if line.startswith("> "):
                lines.append(line[2:])
            elif line.startswith(">"):
                lines.append(line[1:])
            else:
                lines.append(line)
        text = "\n".join(lines)

        # Convert timestamp back to ISO format
        dt = datetime.strptime(ts_str, "%Y/%m/%d %H:%M").replace(tzinfo=timezone.utc)

        found.append({
            "type": comment_type,
            "selectedText": on_text,
            "sectionTitle": re_section,
            "lineNumber": line_num,
            "text": text,
            "createdAt": dt.isoformat(),
            "ts_str": ts_str,  # for matching
        })

    return found


def sync_comments_with_plan(plan_id: str, content: str) -> list[dict]:
    """Bidirectional sync: remove JSON comments not in plan, add plan comments not in JSON."""
    plan_filename = f"{plan_id}.md"
    comments = load_comments(plan_filename)
    changed = False

    # Direction 1: remove JSON entries whose block is no longer in the plan file
    synced = []
    for c in comments:
        pattern = build_comment_removal_pattern(c)
        if pattern.search(content):
            synced.append(c)
    if len(synced) != len(comments):
        changed = True
    comments = synced

    # Direction 2: add plan-file comments that are missing from JSON
    plan_comments = parse_comments_from_plan(plan_id, content)
    existing_blocks = {build_comment_block(c) for c in comments}

    for pc in plan_comments:
        # Build a block from the parsed data to check if it already exists in JSON
        candidate = build_comment_block(pc)
        if candidate not in existing_blocks:
            rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
            new_comment = {
                "id": f"comment-{int(time.time() * 1000)}-{rand}",
                "planId": plan_id,
                "lineNumber": pc.get("lineNumber"),
                "lineContent": "",
                "sectionTitle": pc.get("sectionTitle", ""),
                "selectedText": pc.get("selectedText", ""),
                "text": pc["text"],
                "type": pc["type"],
                "status": "pending",
                "createdAt": pc["createdAt"],
            }
            comments.append(new_comment)
            existing_blocks.add(candidate)
            changed = True

    if changed:
        save_comments(plan_filename, comments)

    return comments


def add_comment(plan_id: str, comment_data: dict) -> dict:
    plan_filename = f"{plan_id}.md"
    comments = load_comments(plan_filename)

    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    now = datetime.now(tz=timezone.utc).isoformat()

    new_comment = {
        "id": f"comment-{int(time.time() * 1000)}-{rand}",
        "planId": plan_id,
        "lineNumber": comment_data.get("lineNumber"),
        "lineContent": comment_data.get("lineContent", ""),
        "sectionTitle": comment_data.get("sectionTitle", ""),
        "selectedText": comment_data.get("selectedText", ""),
        "text": comment_data["text"],
        "type": comment_data.get("type", "comment"),
        "status": "pending",
        "createdAt": now,
    }

    comments.append(new_comment)
    save_comments(plan_filename, comments)
    inject_comment_into_plan(plan_id, new_comment)
    broadcast_sse("comment-added", {"planId": plan_id, "comment": new_comment})
    return new_comment


def resolve_comment(plan_id: str, comment_id: str) -> dict | None:
    plan_filename = f"{plan_id}.md"
    comments = load_comments(plan_filename)
    for c in comments:
        if c["id"] == comment_id:
            c["status"] = "resolved"
            c["resolvedAt"] = datetime.now(tz=timezone.utc).isoformat()
            save_comments(plan_filename, comments)
            return c
    return None


def delete_comment(plan_id: str, comment_id: str) -> bool:
    plan_filename = f"{plan_id}.md"
    comments = load_comments(plan_filename)

    # Find the comment before removing it so we can clean the plan file
    target = None
    for c in comments:
        if c["id"] == comment_id:
            target = c
            break

    comments = [c for c in comments if c["id"] != comment_id]
    save_comments(plan_filename, comments)

    if target:
        remove_comment_from_plan(plan_id, target)

    return True


def build_comment_removal_pattern(comment: dict) -> re.Pattern:
    """Build a regex that matches the comment block in the plan file,
    tolerating whitespace variations (e.g. \\n vs \\n\\n between heading and text)."""
    type_emoji = {
        "comment": "\U0001f4ac",
        "suggestion": "\U0001f4a1",
        "question": "\u2753",
        "approve": "\u2705",
        "reject": "\u274c",
    }
    emoji = type_emoji.get(comment.get("type", "comment"), "\U0001f4ac")
    selected_text = comment.get("selectedText", "")

    header = re.escape(f'### {emoji} {comment.get("type", "comment").upper()}')
    if selected_text:
        excerpt = selected_text[:80] + ("..." if len(selected_text) > 80 else "")
        header += re.escape(f' (on: "{excerpt}")')
    elif comment.get("sectionTitle"):
        header += re.escape(f' (re: "{comment["sectionTitle"]}")')
    if comment.get("lineNumber"):
        header += re.escape(f' [Line {comment["lineNumber"]}]')

    # Build quoted text pattern line-by-line, making trailing whitespace optional
    # so "> " (blank quoted line) also matches ">" (no trailing space)
    text_lines = comment.get("text", "").split("\n")
    quoted_line_patterns = []
    for line in text_lines:
        if line:
            quoted_line_patterns.append(re.escape(f"> {line}") + r" *")
        else:
            quoted_line_patterns.append(r"> ?")
    quoted_escaped = r"\n".join(quoted_line_patterns)

    ts = datetime.fromisoformat(comment["createdAt"]).strftime("%Y/%m/%d %H:%M")
    ts_escaped = re.escape(f"_\u2014 Reviewer, {ts}_")

    # Allow 1-2 newlines between heading and quoted text, and between text and timestamp
    return re.compile(
        r'\n*' + header + r'\n{1,2}' + quoted_escaped + r'\n{1,2}' + ts_escaped + r'\n*'
    )


def remove_comment_from_plan(plan_id: str, comment: dict):
    """Remove an injected review comment block from the plan .md file."""
    fp = PLANS_DIR / f"{plan_id}.md"
    if not fp.exists():
        return

    content = fp.read_text(encoding="utf-8", errors="replace")
    pattern = build_comment_removal_pattern(comment)
    new_content = pattern.sub("\n\n", content, count=1)

    # Clean up: if the Review Comments section is now empty, remove it too
    review_marker = "## \U0001f4dd Review Comments"
    if review_marker in new_content:
        marker_pos = new_content.find(review_marker)
        after_marker = new_content[marker_pos + len(review_marker):].strip()
        if not after_marker:
            before = new_content[:marker_pos].rstrip()
            if before.endswith("---"):
                before = before[:-3].rstrip()
            new_content = before + "\n"

    if new_content != content:
        fp.write_text(new_content, encoding="utf-8")


def inject_comment_into_plan(plan_id: str, comment: dict):
    """Write a review comment into the plan .md file so Claude Code can read it.

    For text-selection comments (those with selectedText), the comment is inserted
    inline right after the paragraph containing the selected text.
    For section-level comments, the comment is appended under the Review Comments
    section at the bottom of the file.
    """
    fp = PLANS_DIR / f"{plan_id}.md"
    if not fp.exists():
        return

    content = fp.read_text(encoding="utf-8", errors="replace")

    type_emoji = {
        "comment": "💬",
        "suggestion": "💡",
        "question": "❓",
        "approve": "✅",
        "reject": "❌",
    }
    emoji = type_emoji.get(comment["type"], "💬")

    selected_text = comment.get("selectedText", "")

    block = f'### {emoji} {comment["type"].upper()}'
    if selected_text:
        # Show a short excerpt of the selected text (max 80 chars)
        excerpt = selected_text[:80] + ("..." if len(selected_text) > 80 else "")
        block += f' (on: "{excerpt}")'
    elif comment.get("sectionTitle"):
        block += f' (re: "{comment["sectionTitle"]}")'
    if comment.get("lineNumber"):
        block += f' [Line {comment["lineNumber"]}]'

    quoted_text = "\n> ".join(comment["text"].split("\n"))
    block += f"\n\n> {quoted_text}\n\n"

    ts = datetime.fromisoformat(comment["createdAt"]).strftime("%Y/%m/%d %H:%M")
    block += f"_— Reviewer, {ts}_\n\n"

    if selected_text:
        # Insert inline after the paragraph containing the selected text
        pos = content.find(selected_text)
        if pos != -1:
            # Find the end of the line/paragraph containing the match
            end_of_match = pos + len(selected_text)
            # Look for the next blank line or end of file
            next_blank = content.find("\n\n", end_of_match)
            if next_blank == -1:
                # No blank line found — append at end of content
                insert_pos = len(content)
            else:
                insert_pos = next_blank
            content = content[:insert_pos] + "\n\n" + block + content[insert_pos:]
        else:
            # Fallback: selected text not found (e.g. plan was edited), append at bottom
            review_marker = "## 📝 Review Comments"
            if review_marker in content:
                content += block
            else:
                content += f"\n\n---\n\n{review_marker}\n\n{block}"
    else:
        # Section-level comment: append at bottom
        review_marker = "## 📝 Review Comments"
        if review_marker in content:
            content += block
        else:
            content += f"\n\n---\n\n{review_marker}\n\n{block}"

    fp.write_text(content, encoding="utf-8")


# ── Latest Session Info ──────────────────────────────────────

def get_latest_session() -> dict | None:
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.is_dir():
        return None

    latest, latest_time = None, 0.0
    try:
        for proj_dir in projects_dir.iterdir():
            if not proj_dir.is_dir():
                continue
            for f in proj_dir.iterdir():
                if f.suffix == ".jsonl":
                    mt = f.stat().st_mtime
                    if mt > latest_time:
                        latest_time = mt
                        latest = {
                            "project": proj_dir.name,
                            "session": f.stem,
                            "modified": datetime.fromtimestamp(mt, tz=timezone.utc).isoformat(),
                        }
    except OSError:
        pass
    return latest


# ── HTTP Handler ─────────────────────────────────────────────

class PlanReviewerHandler(BaseHTTPRequestHandler):
    """Single-class HTTP handler for API + static files + SSE."""

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            # Browser closed connection (e.g. SSE disconnect, page refresh) — ignore
            pass

    def log_message(self, fmt, *args):
        # Quieter logging: only errors
        if args and isinstance(args[0], str) and args[0].startswith("GET /api/events"):
            return
        super().log_message(fmt, *args)

    # ── Helpers ──

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def send_404(self):
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not found")

    # ── CORS ──

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── GET ──

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # SSE endpoint
        if path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            # Send connected event
            msg = f'event: connected\ndata: {json.dumps({"time": datetime.now(tz=timezone.utc).isoformat()})}\n\n'
            self.wfile.write(msg.encode())
            self.wfile.flush()

            with sse_lock:
                sse_clients.append(self.wfile)

            # Keep connection open
            try:
                while True:
                    time.sleep(30)
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                with sse_lock:
                    if self.wfile in sse_clients:
                        sse_clients.remove(self.wfile)
            return

        # API: list plans
        if path == "/api/plans":
            self.send_json(list_plans())
            return

        # API: get single plan
        if path.startswith("/api/plans/") and not path.endswith("/comments"):
            plan_id = unquote(path[len("/api/plans/"):])
            plan = get_plan(plan_id)
            if plan:
                self.send_json(plan)
            else:
                self.send_404()
            return

        # API: latest session
        if path == "/api/session":
            self.send_json(get_latest_session())
            return

        # Serve frontend
        if path in ("/", "/index.html"):
            if INDEX_HTML.exists():
                body = INDEX_HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"index.html not found")
            return

        # Serve icon
        if path == "/icon.svg":
            icon_path = INDEX_HTML.parent / "icon.svg"
            if icon_path.exists():
                body = icon_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_404()
            return

        self.send_404()

    # ── POST ──

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # API: add comment
        if path.startswith("/api/plans/") and path.endswith("/comments"):
            plan_id = unquote(path[len("/api/plans/"):-len("/comments")])
            try:
                data = json.loads(self.read_body())
                result = add_comment(plan_id, data)
                self.send_json(result, 201)
            except Exception as e:
                self.send_json({"error": str(e)}, 400)
            return

        # API: resolve comment
        if "/api/comments/" in path and path.endswith("/resolve"):
            parts = path.strip("/").split("/")
            comment_id = parts[2]  # api/comments/<id>/resolve
            try:
                data = json.loads(self.read_body())
                result = resolve_comment(data["planId"], comment_id)
                self.send_json(result or {"error": "not found"})
            except Exception as e:
                self.send_json({"error": str(e)}, 400)
            return

        # API: delete comment
        if "/api/comments/" in path and path.endswith("/delete"):
            parts = path.strip("/").split("/")
            comment_id = parts[2]  # api/comments/<id>/delete
            try:
                data = json.loads(self.read_body())
                delete_comment(data["planId"], comment_id)
                broadcast_sse("comment-deleted", {"planId": data["planId"], "commentId": comment_id})
                self.send_json({"ok": True})
            except Exception as e:
                self.send_json({"error": str(e)}, 400)
            return

        # API: hook trigger
        if path == "/api/hook-trigger":
            try:
                data = json.loads(self.read_body())
                broadcast_sse("hook-trigger", data)
            except Exception:
                pass
            self.send_json({"ok": True})
            return

        self.send_404()


# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Claude Code Plan Reviewer")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PLAN_REVIEWER_PORT", 3456)))
    args = parser.parse_args()

    # Ensure directories exist
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    COMMENTS_DIR.mkdir(parents=True, exist_ok=True)

    # Start file watcher
    watcher = FileWatcher([PLANS_DIR, COMMENTS_DIR])
    watcher.start()

    # Start HTTP server
    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    server = ThreadingHTTPServer(("127.0.0.1", args.port), PlanReviewerHandler)
    server.request_queue_size = 32

    print(f"""
╔══════════════════════════════════════════════╗
║   🔍 Claude Code Plan Reviewer              ║
║                                              ║
║   Open: http://localhost:{args.port}               ║
║                                              ║
║   Plans:   {PLANS_DIR}
║   Reviews: {COMMENTS_DIR}
║                                              ║
║   Ctrl+C to stop                             ║
╚══════════════════════════════════════════════╝
""")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
