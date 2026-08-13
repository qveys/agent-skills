---
name: conflict-resolve
description: >
  Use when Housekeeper or a user asks to resolve Git merge/rebase conflicts on a
  pull request via rebase + force-with-lease, after GitHub reports mergeable=false.
  Trigger on /conflict-resolve, "resolve PR conflicts", "rebase and fix conflicts",
  or similar. Requires an existing PR checkout and confirmed merge conflict.
---

# Conflict Resolve

Rebases a PR head branch onto the tip of its base, resolves conflict markers
agentically, commits with SSH signing, and pushes with **force-with-lease only**.

This is the **only** Housekeeper skill allowed to rewrite PR head history.
Never use plain `git push --force`.

---

## Prerequisites

| Requirement | Details |
|---|---|
| Working tree | PR checkout on `HEAD_REF` (runner provides `/work/...`) |
| `BASE_REF`, `HEAD_REF` | From Housekeeper env or JSON input |
| `CONFLICT_RESOLVE_MODE` | `write` (push allowed) or `dry-run` (local only) |
| Signing | `commit.gpgsign` enabled globally by runner entrypoint |
| Python 3.9+ | Stdlib only |

Optional env: `OWNER`, `REPO`, `PR_NUMBER`, `GITHUB_TOKEN`.

---

## Tool invocation

```bash
python3 ~/.claude/skills/conflict-resolve/scripts/conflict_tool.py '<json_input>'
```

Parse stdout as JSON. On error the tool prints `{"error":"..."}` and exits 1.
Some failures also set `"needs_human": true` (lease mismatch, branch protection).

Always pass `"localRepoPath"` when not cwd is not the PR checkout.

---

## Normative rules

1. **Always** call `prepare_rebase` before editing any conflicted file.
2. Resolve using full repo context. If two sides change the same business logic
   and you cannot pick one side with high confidence → **stop** (`needs_human`).
3. **Never** `git push --force`. Only `push_head` (force-with-lease).
4. **Never** push any ref other than `HEAD_REF`.
5. In **dry-run**: resolve locally if useful, post a plan comment; **never**
   call `push_head`.
6. Commits: Conventional Commits messages; Housekeeper bot author; always signed.
7. Do not amend/drop commits beyond what the rebase requires — **no** `rebase -i`.
8. If branch protection or lease mismatch blocks push → clear error, exit
   `needs_human`.

### Ambiguity → needs_human (stop, do not guess)

Stop and exit non-zero with a human-readable summary when:

- **(a)** Both sides change the same business logic without a clear local rule.
- **(b)** Lockfile / `package-lock` conflict without an obvious mechanical fix.
- **(c)** You are not **≥ confident** that exactly one side is correct.

**OK to resolve mechanically:** import ordering, whitespace, trivial delete+add,
clear ours/theirs when one side is pure formatting.

---

## Operations

### `prepare_rebase`

Fetch base and head, record remote tip SHA (for lease), rebase onto `origin/<base>`.

**Input:**
```json
{
  "kind": "prepare_rebase",
  "localRepoPath": "/work/owner-repo-pr42",
  "baseRef": "main",
  "headRef": "feature/foo"
}
```

**Output (clean):**
```json
{ "status": "clean", "remoteHeadSha": "abc123..." }
```

**Output (conflicts):**
```json
{
  "status": "conflicted",
  "remoteHeadSha": "abc123...",
  "files": ["src/a.ts", "package-lock.json"]
}
```

**Output (failed):**
```json
{ "status": "failed", "remoteHeadSha": "abc123...", "error": "..." }
```

Store `remoteHeadSha` — required for `push_head`.

---

### `list_conflicts`

**Input:**
```json
{ "kind": "list_conflicts", "localRepoPath": "/work/..." }
```

**Output:**
```json
{
  "count": 1,
  "conflicts": [
    {
      "path": "src/a.ts",
      "excerpt": "   12|<<<<<<< HEAD\n   13|ours\n..."
    }
  ]
}
```

---

### `commit_resolution`

Stage resolved paths and continue rebase. Repeats until rebase completes or new
conflicts appear. Unsigned commits are rejected.

**Input:**
```json
{
  "kind": "commit_resolution",
  "localRepoPath": "/work/...",
  "paths": ["src/a.ts"]
}
```

**Output (rebase done):**
```json
{ "status": "complete", "headSha": "def456..." }
```

**Output (more conflicts):**
```json
{ "status": "conflicted", "files": ["other.ts"], "error": "..." }
```

Call again after resolving the next batch of files.

---

### `push_head`

**Forbidden in dry-run.** Uses:

`git push --force-with-lease=refs/heads/<head>:<remoteHeadSha> origin <head>`

**Input:**
```json
{
  "kind": "push_head",
  "localRepoPath": "/work/...",
  "headRef": "feature/foo",
  "remoteHeadSha": "abc123..."
}
```

**Output:**
```json
{ "pushed": true, "headSha": "def456...", "headRef": "feature/foo" }
```

---

### `abort_rebase`

**Input:**
```json
{ "kind": "abort_rebase", "localRepoPath": "/work/..." }
```

**Output:**
```json
{ "aborted": true }
```

Use when giving up or before reporting `needs_human` after partial work.

---

## Workflow

### Step 1 — Prepare

```bash
python3 .../conflict_tool.py '{"kind":"prepare_rebase","localRepoPath":"...","baseRef":"main","headRef":"feature"}'
```

- `clean` → skip to push (write mode) or plan comment (dry-run).
- `conflicted` → continue to Step 2.
- `failed` → stop with error.

### Step 2 — List conflicts

```bash
python3 .../conflict_tool.py '{"kind":"list_conflicts","localRepoPath":"..."}'
```

### Step 3 — Resolve each file

Edit files to remove markers. Apply ambiguity rules above.

### Step 4 — Commit resolution

```bash
python3 .../conflict_tool.py '{"kind":"commit_resolution","localRepoPath":"...","paths":["file1","file2"]}'
```

Loop Steps 2–4 until `status: complete`.

### Step 5 — Push or plan

**Write mode:**
```bash
python3 .../conflict_tool.py '{"kind":"push_head","localRepoPath":"...","headRef":"...","remoteHeadSha":"<from prepare>"}'
```

**Dry-run:** summarize what would be pushed; **do not** call `push_head`.

---

## Smoke test (manual)

From any git repo with a conflicted rebase in progress:

```bash
export CONFLICT_RESOLVE_MODE=dry-run
python3 scripts/conflict_tool.py '{"kind":"list_conflicts"}'
python3 scripts/conflict_tool.py '{"kind":"push_head","headRef":"x","remoteHeadSha":"abc"}'
# → expect error: forbidden in dry-run
```

Unit tests (no git/network):

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

---

## Safety summary

| Allowed | Forbidden |
|---|---|
| `prepare_rebase`, `list_conflicts`, `commit_resolution` | `git push --force` |
| `push_head` in write mode only | Push base/default branch |
| `abort_rebase` on failure | `git rebase -i` |
| Mechanical conflict fixes | Guessing business logic |
