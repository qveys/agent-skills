---
name: git-worktree-workflow
description: "Use when changing a git repo: worktree, then review."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [Git, Worktree, Isolation, Review, Merge, Multi-Agent]
    related_skills: [agent-merge-conflict-arbiter, github]
---

# Git Worktree Workflow

Standing rule for this user: **any operation that can modify a git repository happens in a
dedicated worktree.** The canonical checkout is conceptually read-only, a reference point and
a sync target for the remote. Work reaches the canonical branch only after the user has
reviewed and validated it.

Load this skill for any task that edits tracked files, changes branch state, or touches git
history, including "just update this file in my repo".

## When to Use

- Toute tâche qui édite des fichiers suivis, change l'état d'une branche ou touche l'historique git (y compris « juste mettre à jour ce fichier »).
- Revue/merge d'un changement, purge de worktrees, push rejeté ou divergence, hooks pre-commit.

## Core rules (always on)

1. **Never edit, stage, or commit in the canonical checkout, whatever the size of the change.** A one-line status fix counts. The canonical stays clean because it is the only reference for the remote sync; a small direct commit there breaks that guarantee and cannot be reviewed as a branch. Create a worktree first.
2. **Put the worktree outside the repo**, or make sure the repo already ignores the worktree
   directory (`wt/`, `.worktrees/`). An untracked worktree directory permanently dirties the
   canonical status you rely on to prove the canonical is untouched.
3. **Resolve the default branch from the remote. Never assume `master`.**
4. **Merge gate = independent review OK + green CI, then `--ff-only` (or the repo's PR merge).**
   Standing rule from this user: a PR may be merged without asking again once (a) a neutral
   reviewer subagent that did not write the change returns OK, and (b) CI on the exact head SHA
   is green. Either missing, leave it unmerged and say so. Merging to a deploy-on-tag `main` is a
   production action: the gate replaces a per-PR approval, it does not remove the gate.
5. **Deliver working artifacts with evidence, not a summary of findings.** This user pushes
   back on knowledge-only outcomes: when they raise a problem they are asking you to resolve
   it. If a decision is genuinely theirs, state that clearly and still deliver the part you can.
6. **Push policy is set per repo by the user, not by this default.** When the user has stated a
   push rule (e.g. the brain vault: commit then push every time, without asking), follow it and
   do not wait for a go. Without such a rule, hand back the branch and the patch and do not push.
   A push is the only way the remote stays in sync: an unpushed canonical silently drifts from
   the other machines that sync the same repo.

## Procedure

### 0. Vérifier les worktrees existants avant d'en créer

Avant de créer un nouveau travail, lister les worktrees existants avec
`git worktree list`. Si un worktree dédié existe déjà pour la branche cible,
l'utiliser plutôt que d'en créer un nouveau. Nettoyer les inutilisés après usage
avec `git worktree prune`.

### 1. Read the repo's state before touching anything

- `git status --porcelain`, `git branch --show-current`, `git worktree list`, and the remote's
  default branch (`git symbolic-ref refs/remotes/origin/HEAD`, `git remote show origin`). If no
  remote/default ref exists, do not guess: record `git rev-parse HEAD` and use it only when it is
  the intended base; otherwise ask.
- **Check status after every edit batch and before handoff.** Another agent or the user may be
  writing the same repo concurrently. Files you did not touch showing as modified or staged are
  not yours: keep them, never clobber them, and report the collision rather than committing
  someone else's in-flight change. If a commit must sit next to foreign edits, name them in the
  commit message.
- If a requested target file is already modified in the canonical checkout, a clean worktree from
  `HEAD` omits that edit. Preserve it and keep your patch isolated; ask before incorporating it
  unless the user's request explicitly scopes a reconciliation. For that named scope, merge only
  those in-flight diffs in the worktree and compare the combined files against the canonical
  versions so neither side is lost. After importing a patch, verify the target before retrying it:
  replaying an already-applied Git delta fails or creates duplicate/conflicting state.
- If git refuses with `dubious ownership`, the checkout belongs to another uid:
  `git config --global --add safe.directory <path>`.
- If `git push`, `fetch`, or `pull` asks for an HTTPS username in a non-interactive session, inspect the credential
  helper and credential-file permissions before retrying. A helper path that exists but is not
  readable by the current uid makes Git behave as if no credentials exist — group membership
  alone does not bypass a `600` mode, the group read bit (`640`) must be set; otherwise retry
  from an environment that owns the credentials or fix ownership/permissions outside the agent
  session.

Done when: you know the canonical branch, its cleanliness, every existing worktree, the intended
base SHA, and the real default branch (or have recorded that no remote default exists).

### 2. Create the isolated worktree

- Session-level: `hermes -w` (or `--worktree`). In-session: `/worktree new <name>`. Manual:
  `git worktree add <path> -b <branch>`.
- Record the intended base SHA before creation; afterward confirm the worktree `HEAD` matches it
  and recheck canonical `HEAD` before final review. If canonical advanced, sync the agent branch
  to that tip in the worktree (`git merge --ff-only <canonical-branch>` when it is behind and the
  changes permit it; otherwise rebase or recreate), then rerun the affected tests. A stale base
  can hide same-file changes even when the original test suite passed.
- Prefer a path outside the repo unless the repo ignores the directory.
- `git worktree move <old> <new>` requires the destination's parent directory to exist first.

See `references/worktree-isolation-in-hermes.md` for the Hermes commands, the config keys that
govern them, and how to exercise worktree behaviour from a spawned session.

### 3. Work, then verify with proof

- Reproduce before fixing. State the exact line or mechanism where the behaviour originates.
- When the repo uses submodules, initialize them inside the worktree before running repo checks:
  `git submodule status` shows a leading `-` for uninitialized modules, and checks that read
  files inside the submodule will otherwise fail for the wrong reason.
- Repo-owned gates (`scripts/*check*`, `*verify*.mjs`, `--self-test`/`--check` pairs, content
  budgets, provenance markers) are the acceptance criteria for that repo. Read the checker's
  source before rewriting a file it measures, and add assertions to its self-test when you change
  it: `references/repo-owned-gates.md`.
- **Prove the test is RED without the fix and GREEN with it.** Stash only the source files and
  keep the tests, so the failing run proves the test binds to the change rather than to the
  environment. A test that has never failed proves nothing.
- For sibling suites, an unrelated failure is only "pre-existing" once you have reproduced it on
  the base with the change set aside. Run that comparison; do not assert it.
- **Say what you could not verify, and why.** Never present an unverified path as validated.

### 4. Commit on the agent branch

- Add files explicitly, one path at a time. Never `git add .` or `git add -A`.
- Follow the repo's own commit convention: read its `AGENTS.md` and, when it ships one, run its
  message validator before committing rather than after.
- Some validators also enforce variety across consecutive commits (emoji pools): read the last
  subject first (`git log --format=%s -n 1`) and draft a message that differs from it.
- When the user's git identity is unknown, commit with a neutral author and tell them to amend
  it before publishing.

### 5. Merge after review

- **Neutral review:** spawn a separate reviewer that gets the PR number, the repo rules and the
  acceptance criteria, but not the author's reasoning or advocacy, so it cannot inherit the
  author's blind spots. Prefer a model from another provider than the author (Kanban card with
  `model`/`provider`): subagents from `delegate_task` inherit the parent model, so a
  same-model reviewer shares its blind spots and burns the same quota.
- **CI check with the GitHub bot:** `gh run list --branch <branch> --json status,conclusion,headSha`
  and match `headSha` to `gh pr view <n> --json headRefOid`; the checks/status/branch-protection
  APIs may return 403 for the integration token while Actions reads work.
- **Order dependent PRs:** merge the root-cause fix before a threshold/noise PR that depends on
  it, so the alert keeps signalling until the cause is gone.
- From the canonical checkout: `git merge --ff-only <branch>`, only once the gate above is met.
- A `--ff-only` merge needs the canonical branch to still be an ancestor of the agent branch.
  If the remote default moved, **rebase the agent branch onto `origin/<default>` in the clean worktree first**, then ff-merge into a canonical that is an ancestor of that rebased tip.
- If the canonical working tree has **unrelated uncommitted work**, do not `reset --hard` it. Push the rebased tip from the clean worktree (`git push origin HEAD:<default>` when HEAD descends from `origin/<default>`), or update only the ref after a successful remote ff.

### 6. Clean up

- `hermes worktree list|audit|prune` reclaims accumulated trees; worktrees are pruned on exit
  unless they hold unpushed commits.
- Remove throwaway sandboxes and scratch repos you created, and verify the canonical is clean.
- **Purge accumulated agent worktrees without losing uncommitted work.** `git worktree remove`
  keeps branch commits but destroys uncommitted tracked edits and untracked files. Before
  purging a tree, compare each tracked-modified file against the canonical branch
  (`git -C <wt> diff <canonical> -- <file> | wc -l`): a non-zero delta is unmerged work, zero
  means the canonical already has it. Preserve non-zero trees as a WIP commit on their branch
  first (`--no-verify` when a repo hook blocks the transient mid-task state; the WIP is local
  and reversible), then `git worktree remove --force <path>`. Untracked artifacts regenerable
  from sources are expendable; keep all branches afterwards — dropping them is a separate,
  reviewed decision. Verify with `git worktree list` and the branch list.

## Pitfalls

- **Worktree setup writes into the canonical checkout.** Creating a tree appends `.worktrees/`
  to the canonical repo's `.gitignore`, which contradicts a read-only-reference workflow.
  Refuse the write via `worktree_gitignore: false`, or commit the ignore entry yourself so the
  membership check becomes a no-op.
- **`worktree: true` hard-fails outside a repository.** Config-driven isolation must degrade to
  running in place when there is no repo, otherwise a plain session becomes unusable in any
  non-repo directory. An explicit `-w` should still fail loudly, because the user asked for
  isolation there.
- **Only the chat path creates the worktree.** The global one-shot form (`hermes -z`) skips
  worktree setup entirely, so a config-driven worktree silently does not happen and looks like
  a broken feature. Use `hermes chat -q` when the worktree is what you are testing.
- **A script that hardcodes `master` breaks on a `main` repo** with
  `fatal: couldn't find remote ref master`. Grep the repo for `master` before touching branch
  logic, and resolve the default branch from the remote rather than from habit.
- **Fix a script's test scaffold in the same change.** Scaffolds usually recreate the branch
  name the script assumed, so leaving them behind means the suite tests a repo that no longer
  resembles the real one and stays green over the bug.
- **Never delete the shell's own working directory.** Removing the directory you are standing in
  breaks later relative-path commands; `cd` somewhere valid first.
- **Ephemeral checkouts eat deliverables.** When the workspace or install tree can be rebuilt,
  keep the patch/branch somewhere persistent and tell the user its exact path; a patch left in a
  scratch workspace is gone at the next rebuild.
- **Protected instruction files need the platform approval path.** If editing `AGENTS.md` or a
  similar protected prompt file is blocked by an approval timeout, stop and ask the user to
  approve the UI prompt; do not retry through shell or another write path, because the guard has
  explicitly withheld consent. A refusal that instead names a path restriction
  (`outside HERMES_WRITE_SAFE_ROOT`) is not a withheld consent: the repo simply lives outside the
  write-safe root, and the sanctioned path is staging the edit as a script plus `terminal`. Recipe:
  `references/repo-owned-gates.md`.
- **Do not reuse a sibling worktree whose tree already has unrelated edits.** Copying this task's files onto it overwrites another agent's in-flight work. Create a fresh worktree from the intended base instead.
- **Never `git reset --hard` a dirty checkout to unblock ff-only.** Uncommitted inbox drains, notes, or sibling edits are destroyed. If a destructive update is refused or would be needed only to simplify the path, switch to a fresh/clean worktree, rebase the agent branch, and push or ff-merge from there; do not ask again for the destructive shortcut.
- **Genuine collisions between two agents' branches** are not this skill's job: hand them to
  `agent-merge-conflict-arbiter` so neither side self-adjudicates.
- **Hook files in `.husky/<name>` are not active by default.** `.husky/` ships template scripts
  with a repo, but they only fire after `husky install` sets `core.hooksPath`. Before that, the
  hook files are inert decoration. When deploying a Git safety net (pre-commit guard,
  message-validator wrapper, etc.) and you cannot guarantee `core.hooksPath` is configured,
  install the executable into `.git/hooks/` directly and `chmod +x` it. Verify by running a
  known-bad input through `git commit` — a script that does not fire is worse than no script.
- A pre-commit checker that reads working-tree files can validate different bytes from the commit
  when staged and unstaged content diverge. Validate sources, manifests and the checker itself
  from an index snapshot; reject symlink/non-regular modes on every checked path. Match accepted
  source types and nesting to scanner coverage (a non-recursive scanner requires flat sources).
  Include rename/type-change statuses (`R`/`T`) and test staged deletion, rename, worktree
  divergence and a permissive unstaged checker; see `references/repo-owned-gates.md`.
- Before refreshing an installed `.git/hooks/*` copy, compare it with the tracked source and
  preserve its existing rules; installed hooks are separate files and may be shared across
  worktrees. If a hook invokes repository tooling, ensure that implementation is present in the
  target checkout too: Git runs the hook against that checkout, not a sibling worktree. Never
  install an older worktree copy over a newer active hook: reconcile first, test a known-bad staged
  change through a real `git commit` in an isolated repo, then verify installed bytes and mode.
- **A repo-owned sync helper is scoped to one repo and to one subtree.** Before running one (a
  script that fetches/merges the default branch and then commits only a named subdirectory), read
  its guard clauses: it may refuse unless the current branch matches a pattern (e.g. `agent/*`),
  and its `save` step adds only that subtree. If that subtree is git-ignored in the repo you run
  it from — the common shape when a sibling vault is checked out separately — `sync` still works
  but `save` is a permanent no-op that only prints `rien à commiter`. Confirm with
  `git check-ignore -v <subtree>` and run the script from the repo it was written for.
- **Credential helpers that fail silently block pushes with `could not read Username`.** Inspect
  `git config --show-origin --get-all credential.helper` first. To use a specific helper for one
  push without editing config, reset the list then set the sanctioned one:
  `GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c credential.helper=<helper-path> push origin <branch>`.
  Keep `GIT_TERMINAL_PROMPT=0` so a missing credential fails fast instead of hanging. Never print
  or copy the returned secret; check only that the helper returns a `username=` line.
- **A push rejected as non-fast-forward when the remote has commits from another machine:** fetch,
  `git merge --no-edit origin/<branch>` (or rebase if the user prefers linear history), verify the
  merge touches only expected paths, then push normally. Never force-push to resolve it.
- **A `--ff-only` pull that fails on a diverged branch is signalled, never forced.** When the
  local branch has its own commits AND the remote has moved (both `ahead` and `behind` non-zero),
  `git pull --ff-only` cannot fast-forward: report the divergence instead of forcing it. The
  sanctioned recovery is `git pull --rebase` then `git push`, never `--force`; on a rebase
  conflict, abort and surface it. **Re-fetch immediately before deciding:** a background or
  multi-host sync can advance the remote, and even absorb your local commits onto `origin`,
  between your first fetch and your decision, so a stale `ahead N / behind M` reading misleads.
  A `504`/RPC failure from the remote is transient: retry the push rather than reworking history.

## Verification

- `git worktree list` shows the agent tree on its own branch; the canonical still sits on its
  own branch and `git status --porcelain` shows no unexpected entry.
- The change's tests are red on base and green with it, demonstrated, not asserted.
- The canonical branch received the work only through the reviewed `--ff-only` merge.
- The hand-back names: branch, commit(s), where the patch lives, what was verified, what was not.
