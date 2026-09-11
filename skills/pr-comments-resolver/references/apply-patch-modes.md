# `apply_patch` — modes, signing, failure handling

Read this when a plain `apply_patch` call is not enough: batching, reusing a
local checkout, previewing with `dryRun`, or diagnosing a signing/push failure.

## Commit payload

**Batch (preferred):** one clone (or one local checkout), N signed commits
applied in order, **one push** at the end — so N fixes cost one clone + one push
instead of N.

```json
{
  "kind": "apply_patch", "owner": "qveys", "repo": "my-supervision", "prNumber": 4,
  "localRepoPath": "/abs/path/to/checkout",
  "commits": [
    { "commitMessage": "fix: address review comment #1", "files": ["src/foo.py"] },
    { "commitMessage": "fix: address review comment #2", "files": ["src/bar.py"] }
  ]
}
```
**Output:** `{ "commitShas": ["abc123...", "def456..."] }`

**Legacy single-patch** (still supported): `{"patch": "...", "commitMessage": "..."}`
at the top level → **Output:** `{ "commitSha": "abc123..." }`.

`authorName` / `authorEmail` are optional, top-level, and apply to every commit
in the batch. When omitted the commit inherits the ambient git identity (global
`~/.gitconfig`). They exist so the SSH signature is attributed to the right author.

## Commit entries without `patch` (default path)

A commit entry with **no `patch` key** means *"commit the edits already sitting
in the working tree"*. Edit the files directly with `Edit` / `Write`, then let
the script stage, sign, commit and push them.

Prefer this over emitting a unified diff: the diff never has to be serialized
into the call, and it cannot fail on stale context. `git apply` is skipped
entirely.

Three preconditions, each with its own explicit error:

- **`localRepoPath` is required** — a fresh clone has no local edits to commit.
- **`files` is required on every patchless entry** (non-empty list of paths).
  They must be exact repo-relative file paths — directories, globs and `.` are
  recursive pathspecs and are rejected. Only those paths are staged
  (`git add -- <files>`, never `git add -A`), and the index is re-checked after
  staging: anything outside the list (including something the caller had staged
  before the run) aborts the commit. Granularity is the file, not the hunk — an
  unrelated edit *inside* a declared file does get committed.
- **No mixing** patch and patchless entries in one call: the patch entries stage
  everything and would sweep up the other commits' working-tree edits. Send two
  separate calls.

The clean-working-tree precondition does **not** apply here — a patchless run
needs the tree dirty, that dirt is the payload. Correspondingly, a failed
patchless run rewinds with `git reset --mixed` (HEAD back, files kept on disk),
never `--hard`: the script must not delete edits it did not produce.

## `localRepoPath` (reuse an existing checkout)

```json
{ "localRepoPath": "/abs/path/to/existing/checkout" }
```

Preconditions are checked up front, each with its own clear error: the path must
be a git repo and its **current branch must equal the PR's head branch**. For
patch entries the **working tree must also be clean**; patchless entries need it
dirty (that dirt is the payload) and are guarded by the `files` allowlist
instead.

The user's git config is never touched — an `authorName`/`authorEmail` override,
if given, is passed per commit via `git -c user.name=... -c user.email=...
commit ...` instead of `git config`. Pushes go through the existing `origin`
remote (no token URL).

On any failure (apply, signing, push, unexpected exception) the branch is
rewound to its pre-run HEAD, so the checkout never ends up carrying unpushed
commits — `--hard` in patch mode (restoring the clean pre-run tree), `--mixed`
in patchless mode (keeping the caller's edits on disk).

Without `localRepoPath` the script shallow-clones the PR head branch into a temp
dir using a token URL, and pushes back through it.

## `dryRun`

```json
{ "dryRun": true }
```

Runs the full flow (clone or local checks, patch application, signed commits)
but **never pushes**.

**Output:** `{ "dryRun": true, "wouldPush": [ { "commitMessage": "...",
"diffStat": "...", "signed": <bool> }, ... ] }`

In local-repo mode the branch is reset back to its pre-dry-run HEAD before
returning — `--hard` for patch entries, `--mixed` for patchless ones so the
caller's edits stay on disk. In a dry run a signing failure does not abort the operation — it
retries the commit unsigned and reports `signed: false`, since the point of a
dry run is to diagnose before the real pass.

Worth a pass when the PR is sensitive (production branch, many reviewers) or the
patch set is large.

## Signing (enforced on real runs)

Commits are **always signed** (`git commit -S`). The signing key, format, and
signer program are inherited from the ambient git config — nothing is hardcoded.

If signing fails, the operation **aborts and never pushes an unsigned commit**;
it returns an `error` asking you to unlock the key and retry. A push is also
refused if `HEAD` ends up without a signature.

Two common causes, both reported verbatim in the error:
1. the signing key is locked (e.g. 1Password) — unlock it and retry;
2. the shell is sandboxed and blocks the signer (`op-ssh-sign`) — rerun outside
   the sandbox (Claude Code Bash with `dangerouslyDisableSandbox`).

## Failures

**Output:** `{ "error": "git apply failed: ..." }`, or a signing error as above.
`git apply` output is truncated to its first lines per stream — the diagnosis is
at the top, the rest is padding.

In batch mode a failure on commit *k* names the offending commit
(`commit 2/3 ("fix: ...") failed: ...`) and **nothing is pushed**.

If the PR head lives on a fork, a push failure is annotated with the fork's name
— the token most likely lacks push rights there.
