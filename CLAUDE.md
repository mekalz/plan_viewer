# Plan Viewer Integration

## How the Review System Works

When working in plan mode, a browser-based Plan Viewer may be active.
Human reviewers can add comments directly to plan files in `~/.claude/plans/`.

## Recognizing Review Comments

Review comments appear in plan files under a `## 📝 Review Comments` section (at the bottom for section-level comments) or inline after the relevant paragraph (for text-selection comments).

Each comment has a type indicator:

- ✅ **APPROVE** — The reviewer approves this section/plan. Proceed.
- 💬 **COMMENT** — General feedback. Consider and acknowledge.
- 💡 **SUGGESTION** — A specific change suggestion. Evaluate and apply if reasonable.
- ❓ **QUESTION** — The reviewer needs clarification. Answer in the plan.
- ❌ **REJECT** — The reviewer disagrees with this approach. Revise before proceeding.

## How to Respond to Comments

When you see review comments in a plan file:

1. **Read all comments** before making changes
2. **For APPROVE**: Acknowledge and proceed with implementation
3. **For SUGGESTION/COMMENT**: Update the relevant plan section to address the feedback
4. **For QUESTION**: Add an answer below the question in the plan
5. **For REJECT**: Substantially revise the rejected section and explain changes
6. After addressing comments, add a brief response note under each comment

## Comment Format in Plan Files

Section-level comments use `(re: "Section Title")`:

```markdown
### 💡 SUGGESTION (re: "Database Design")

> Consider using a composite index on (user_id, created_at) instead of separate indexes.

_— Reviewer, 2026/01/15 15:30_
```

Text-selection comments use `(on: "selected text...")`:

```markdown
### 💬 COMMENT (on: "JWT-based session management")

> Have we considered token revocation strategies?

_— Reviewer, 2026/01/15 15:35_
```

When responding, add your response directly below:

```markdown
**Claude's Response**: Good suggestion. Updated the index strategy in the Database Design section
to use a composite index. This should improve query performance for the user timeline queries.
```
