---
name: github
description: "GitHub via gh CLI: PRs, issues, reviews, repos, auth."
version: 2.0.0
author: Ben Barclay (benbarclay), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [github, gh, git, pull-requests, issues, code-review, repos, auth, ci]
    category: software-development
    related_skills: [codebase-inspection, requesting-code-review]
---

# GitHub

Work GitHub end to end with the `gh` CLI (REST fallback where noted): auth,
issues, the PR lifecycle, issue-to-PR delivery, code review, and repo
management. This skill consolidates six former skills; each workflow lives
complete in its reference file — ALWAYS read the matching reference before
starting that workflow, the body below only routes.

## Routing

| Task | Read first |
|---|---|
| Auth broken / new machine / token or SSH setup / gh login / install gh without root / GitHub App credentials | `references/auth.md` |
| Create, triage, label, assign, close issues | `references/issues.md` |
| Branch, commit, open PR, watch CI, merge | `references/pr-workflow.md` |
| Carry an ISSUE to a verified PR (full delivery loop) | `references/issue-to-pr.md` |
| Review someone's PR: diffs, inline comments, verdict | `references/code-review.md` |
| Merge refused on a protected branch / merge-method policy / auto-merge | `references/merge-protected-branch.md` |
| Clone/create/fork repos, remotes, releases | `references/repo-management.md` |

Supporting assets: `scripts/gh-env.sh` + `scripts/git-credential-token.py`
(auth helpers), `templates/` (PR bodies, bug report, feature request),
`references/ci-troubleshooting.md`, `references/conventional-commits.md`,
`references/github-api-cheatsheet.md`, `references/review-output-template.md`.

## Core discipline (applies to every workflow)

- Preflight once per session: `gh auth status` — if it fails, go to
  `references/auth.md` before anything else.
- Prefer `gh` over raw REST; drop to `gh api` only for endpoints the
  porcelain lacks (the cheatsheet lists them).
- Never report CI green without checking `gh pr checks` yourself; never
  claim merged without verifying `state,mergedAt`.
- Read full context before writing: `gh issue view --comments` /
  `gh pr view --comments` — decisions live in threads, not titles.
- Sweep for duplicates before creating anything:
  `gh pr list --search` / `gh issue list --search`.
- A PR that stays `mergeStateStatus: BLOCKED` with green CI means the branch
  ruleset rejected the commits, not the code: check
  `gh api repos/O/R/branches/<base>/protection` (fields `required_signatures`,
  `enforce_admins`, `required_status_checks`). Do this check BEFORE opening the
  PR on a repo you have not pushed to before.
- Local `git commit` + `git push` on such a repo is guaranteed to fail the
  merge: a GitHub App / bot token can never register an SSH or GPG signing key
  (`403` on `POST user/ssh_signing_keys`), so its commits are always unsigned.
  Use the bundled harness `scripts/gh-sign-commit.sh` instead — it calls
  GraphQL `createCommitOnBranch`, which makes GitHub itself the committer, so
  the commit is `verified=true` and the branch advances with the mutation.
  Recipe: create the branch ref at the base sha first (`POST /git/refs`) —
  `createCommitOnBranch` refuses an unknown branch — then run
  `REF=refs/heads/<branch> PARENT=<base-sha> MESSAGE="..." scripts/gh-sign-commit.sh <paths...>`
  from a worktree holding the final content, and confirm the printed
  `verified:true`. Le fichier du dépôt est en mode `644` : lancer `bash <chemin>/gh-sign-commit.sh …` (sinon `Permission denied`), et passer `bash` aussi pour la copie locale si elle a perdu son bit exécutable. Fallback when the harness is unavailable: one
  `PUT /repos/O/R/contents/<path>` per file (committer `web-flow`). Either way
  this rewrites history — the old PR becomes obsolete, so open a fresh PR and
  close the blocked one with a pointer comment.
- Le garde-fou est installé : `core.hooksPath=/opt/data/git-hooks` (global, tous
  profils) ; son hook `pre-commit` interroge la protection du dépôt GitHub et
  refuse le commit local si `required_signatures` est actif, en renvoyant vers
  `gh-sign-commit` (symlink dans `/opt/data/bin/`). Politique mise en cache 12 h
  dans `$GIT_DIR/hermes-signature-policy`. Il bloque aussi les miroirs sans
  fusion : `HERMES_ALLOW_UNSIGNED=1 git commit ...` est le contournement
  explicite (aucun autre chemin légitime).
- Required check reported as `SKIPPED` (e.g. CodeRabbit refusing bot-authored
  PRs: "bot user not eligible for review") is treated as passing by GitHub —
  `mergeStateStatus` goes `CLEAN`. Don't hunt a phantom blocker: read the check
  run's `output.summary` first, then trust `mergeStateStatus`.
- Re-sending a revoked/limited `GH_TOKEN` to `rerun` or `workflow_dispatch`
  needs Actions **write**: without it the API answers
  `Resource not accessible by integration` (403).
- Credentials: never ask for, read, print or store a long-lived secret (PAT,
  GitHub App private key) in chat, context or files. Ask for the vault item
  NAME only. Prefer a GitHub App with short-lived installation tokens minted by
  a helper that reads the key inline (`op read` at signing time) and keeps only
  the token; a PAT in the vault is the fallback. Why: any secret that reaches
  the context is replayed in logs and is shared by every profile on the box.
- Scope before granting: install the App only on the chosen repos and grant the
  minimum permissions (Contents, Pull requests, Issues R/W; Metadata R).
- Shared install: when several profiles must use `gh`, install the binary in
  the shared HERMES_HOME (see `references/auth.md`, "User-space install"), not per profile.
- Prove access with a reversible write before reporting it as granted. The
  `permissions` field of a repo is not a reliable source for installation tokens.
- Grant-then-test: after the user changes an App's permissions, re-mint the token
  (drop the cache) before testing, because a token keeps the permissions it was minted with.
- Two forges, two accounts: GitHub and Gitea are different hosts with different
  credentials. Check the host of every remote before pushing or cloning.

## Verification

- The workflow's own reference file defines done for that task.
- Cross-cutting: every claim about remote state (CI, merge, release,
  issue state) is backed by a fresh `gh` read, never memory.
