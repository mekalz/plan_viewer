# Contributing to Plan Viewer

Thanks for your interest in contributing!

## Getting Started

1. Fork and clone the repo
2. Run `bash setup.sh` to start the server
3. Open `http://localhost:3456` in your browser

## Project Structure

- `server.py` — Python HTTP server (zero dependencies)
- `index.html` — Single-file frontend (HTML + CSS + JS)
- `notify.sh` — Claude Code hook script
- `setup.sh` — One-click setup script
- `CLAUDE.md` — Instructions that get appended to Claude Code's CLAUDE.md

## Guidelines

- **Zero dependencies** — The server must remain pure Python 3 stdlib. The frontend uses CDN-loaded libraries only.
- **Single-file frontend** — Keep everything in `index.html`. No build step, no bundler.
- **Keep it simple** — This is a lightweight tool. Avoid over-engineering.

## Submitting Changes

1. Create a branch for your change
2. Test with both dark and light themes
3. Verify comment round-trip works (add comment in UI, check it appears in the `.md` file)
4. Open a pull request with a clear description

## Reporting Issues

Open an issue with:
- What you expected to happen
- What actually happened
- Browser and OS info
- Steps to reproduce
