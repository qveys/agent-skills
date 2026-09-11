---
name: pr-comments-resolver
description: >
  Use when the user asks to resolve or address GitHub pull-request review
  comments/threads, provides a PR URL or number and wants review feedback
  handled, or says "resolve PR comments", "address review feedback",
  "traiter les commentaires de review", "résoudre les threads de la PR", or
  similar in any language.
---

# PR Comments Resolver

Full GitHub PR review response cycle: **fetch → classify → patch → commit →
reply → resolve**. Needs Python 3.9+ (stdlib only), `git` in `PATH`, and a token
— `GITHUB_TOKEN` if set, else `gh auth token` (scopes: `repo`, or
`Contents: write` + `Pull requests: write` for a fine-grained token).

## Tool invocation

One script, always an **absolute path** — the working directory is the PR's repo
checkout, not this skill's folder:

```bash
python3 ~/.claude/skills/pr-comments-resolver/scripts/pr_tool.py '<json_input>'
```

It prints compact JSON to stdout. On any error it prints `{"error": "..."}`
**and** exits 1 — check both. Every operation takes `owner`, `repo`, `prNumber`:

| `kind` | Extra input | Output |
|---|---|---|
| `list_pr_comments` | — | `{ "comments": [...] }` |
| `apply_patch` | `localRepoPath`, `commits: [{commitMessage, files}]` | `{ "commitShas": [...] }` |
| `update_threads` | `updates: [{commentId, threadId, resolved, message}]` | `{ "ok": bool, "results": [...] }` |

`apply_patch` has more modes (batch, unified diffs, `dryRun`, signing, forks)
→ **`references/apply-patch-modes.md`**, read it only when you need them.

## Workflow

**Step 1 — Receive context.** `owner`, `repo`, `prNumber`, plus the path to a
local checkout of the PR head branch (correct branch, no unrelated uncommitted
work) — the rest depends on it.

**Step 2 — Fetch comments.** Call `{"kind":"list_pr_comments", ...}`. The output
is already trimmed to the unresolved root comments — no resolved threads, no
replies, no diff hunks. **Do not ask for more than you need**; the untrimmed
payload runs to 270 KB on a busy PR. Opt back in only on demand:
`includeResolved`, `includeReplies`, `hunkLines: N`.

Empty list → nothing to do. Say so and stop. Otherwise each comment carries
`id`, `threadId` (required to resolve), `path`, `line`, `body`, `user`, and
`position` (`null` = outside the current diff, i.e. outdated).

**Step 3 — Classify each comment.** **Relevant** (patch it): explicit request
(rename, refactor, extract, delete, add); bug, security, performance,
correctness; missing test/doc/config; inconsistency with the rest of the
codebase.

**Not relevant** (no code change): praise or acknowledgement; stylistic
preference with no agreed standard in the project; question already answered by
the code; obsolete comment (`position: null`, file or line gone).

**Step 4 — Delegate the edits, one agent per file.** Group the relevant comments
**by `path`**, then dispatch one `builder` agent per file, **in parallel** (a
single message, several tool calls). Give each agent the comment bodies for that
file, the checkout path, and this contract:

> Edit the file in place. Apply the **minimal change** that fully satisfies each
> request — never change behaviour beyond what the comment asks, preserve
> existing naming and formatting. When the intent is unclear, do not edit.
> Return only `{commentId, status: applied|skipped, files touched, one-line
> summary}` — no file contents, no diffs.

This keeps file contents out of the main context, which is where the cost is.
Only handle a file yourself when a comment needs judgement the agent lacks.

**Step 5 — Commit and push.** One call, one push, no diffs serialized — the
files are already edited:

```json
{ "kind": "apply_patch", "owner": "...", "repo": "...", "prNumber": N,
  "localRepoPath": "/abs/path/to/checkout",
  "commits": [ { "commitMessage": "fix: address review comment #<id> – <desc>",
                 "files": ["src/foo.py"] } ] }
```

`files` is **required** when there is no `patch`: only those paths are staged, so
unrelated uncommitted work in the user's checkout is never swept into the commit
— nor destroyed if the run fails. List exactly what the agents reported touching.

Group logically related comments into one commit (e.g. two nits in the same
function); keep unrelated changes in separate commits. Store each returned sha
against its `commentId`(s). On a sensitive PR, pass `"dryRun": true` first and
inspect `wouldPush`. On error: do **not** mark the comment resolved — report it
in the thread.

**Step 6 — Decide the resolution status.** `resolved = true` when the patch
fully addressed the request, or the comment needed no code change (praise,
obsolete — or skip it entirely). `resolved = false` when the fix is partial, the
request ambiguous, or the patch failed.

**Step 7 — Build the `updates` list.** One entry per root comment, always with
`threadId` (GitHub needs it to mark the thread resolved). Wording and language →
**`references/reply-templates.md`**.

**Step 8 — Update threads.** Call `{"kind":"update_threads", ...}` with **all**
updates in a single call. The script replies in each thread and resolves it via
GraphQL when `resolved = true`. Updates are independent — check `results` for
per-update failures (`step: reply | resolve`). `"dryRun": true` reports
`wouldPost`, no network call.

## Safety rules

- Never modify files outside the PR's existing diff scope unless a comment explicitly requests it.
- Never alter public API signatures without an explicit reviewer request.
- Never force-push or rebase — only `git push origin <branch>`.
- Prefer several small, focused commits over one large patch.
- If genuinely unsure: `resolved = false`, post a clarification request.
