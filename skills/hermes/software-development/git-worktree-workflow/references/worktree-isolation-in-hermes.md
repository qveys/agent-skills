# Worktree isolation in Hermes

Depth for `git-worktree-workflow`: the Hermes commands, the config keys behind them, the write
that lands in the canonical checkout, and how to exercise worktree behaviour from a session
that spawns children.

## Creating a tree

- `hermes -w` / `--worktree`: disposable tree for the session, pruned on exit unless it holds
  unpushed commits. Multiple terminals running `hermes -w` each get their own tree and branch.
- `/worktree new <name>`: in-session. Creates `.worktrees/<name>` on branch `hermes/<name>`,
  based on the freshly-fetched remote tip, and retargets the session's terminal and file tools
  into it without a restart. `/worktree` shows the active tree, `/worktree list` lists them.
- `git worktree add <path> -b <branch>`: manual, and the only form that lets you choose a
  location outside the repo.
- `git worktree move <old> <new>` requires the destination's parent directory to exist.

## Auditing and reclaiming

- `hermes worktree list` (aliases `ls`, `audit`) classifies every tree: age, size, verdict,
  reason.
- `hermes worktree prune` removes provably-safe trees and deletes fully-merged local branches.
  It never deletes uncommitted tracked changes, unique unpushed commits, or in-use trees;
  untracked-only scratch is archived before removal.
- **`hermes worktree` is the cleanup command, not a creation one.** Reading its name as "make me
  a worktree" leads to the wrong tool; creation is `-w`, `/worktree new`, or `git worktree add`.

## Config keys

| key | default | read by | meaning |
|---|---|---|---|
| `worktree` | `false` | session setup in `cli.py` | create a worktree for every CLI session inside a repo, not only with `-w` |
| `worktree_sync` | `true` | `hermes_cli/worktree_ops.py` | branch the new tree from the freshly-fetched remote tip instead of local HEAD |
| `worktree_gitignore` | `true` | `hermes_cli/worktree_ops.py` | allow setup to append `.worktrees/` to the canonical repo's `.gitignore` |

- A top-level key that code reads but the config defaults do not register makes
  `hermes config set` answer "not a recognized config key" for a documented option. Register the
  key in the config defaults, which is also what makes it show up in `hermes config get` and
  eligible for migration.
- `hermes config get <key>` reads whatever is in the file even when the code no longer knows the
  key, so a green `get` is not evidence that the setting is in force. Check the code, not just
  the value, before trusting a gate to have an effect.

## The write that lands in the canonical checkout

Creating a worktree appends `.worktrees/` to the canonical repo's `.gitignore`, so every run
mutates the checkout a read-only-reference workflow wants byte-identical. Two ways out:

- `worktree_gitignore: false`: skip the write entirely. The new tree then shows up as an
  untracked `.worktrees/` until the repo ignores it on its own terms.
- Commit `.worktrees/` (or `wt/`) in the repo's own ignore file: the membership check becomes a
  no-op and the canonical genuinely stays clean.

## Exercising it from a spawned session

A child CLI spawned from a gateway or WebUI session inherits surface state that pins its
working directory away from the launch directory:

- `_HERMES_GATEWAY=1` inherited in the environment makes `cli.py` skip its force-export of
  `TERMINAL_CWD`, so a stale value from the parent surface survives.
- `terminal.home_mode` overrides `HOME` to `$HERMES_HOME/home`, and a relative
  `terminal.cwd: "."` is what anchors on `HOME`, not on the process cwd.

The observable symptom is a session whose `pwd` is the inherited workspace or the profile home
instead of the directory you launched from, so no repo is found and no worktree is created,
which looks exactly like a broken feature.

To exercise launch-directory or repo-dependent behaviour:

```bash
cd <repo>
env -u TERMINAL_CWD -u _HERMES_GATEWAY HOME=<repo> hermes chat -q "<probe>" -Q --max-turns 1
```

- `HOME=<repo>` is what re-anchors the session when `terminal.cwd` is `.`.
- `hermes chat -q` is required: the global one-shot form bypasses worktree setup entirely.
- Ask the session to report `pwd`, then check `git worktree list` and the repo's `.gitignore`
  before and after, so creation and the canonical write are both observed rather than assumed.
- A tree with no unpushed commits is cleaned up on exit, so an empty `git worktree list`
  afterwards is the documented outcome, not proof that creation failed. Observe during the run
  or have the session create a commit if you need the tree to persist.
