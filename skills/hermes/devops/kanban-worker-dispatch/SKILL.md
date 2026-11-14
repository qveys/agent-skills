---
name: kanban-worker-dispatch
description: "Use when a Kanban worker fails silently or blocks."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [kanban, dispatch, worker, headless, troubleshooting]
    related_skills: [kanban-orchestration, kanban-batch-recovery]
---

# Kanban worker dispatch

## When to Use

- Une carte reste `ready` sans jamais passer `running`, ou s'auto-bloque après 2 essais (`protocol violation`, `spawn_failed`, `crashed`).
- Avant de créer des cartes pour un profil worker (pré-vol) ; avant de relancer un lot bloqué.
- Un worker a écrit son livrable mais la carte reste `blocked`/`running` (récupération de complétion obsolète).

Diagnose why a dispatched worker never ran, died instantly, or blocked — before concluding the task is wrong.

Most "the card is stuck" reports are dispatch-configuration faults, not task faults. The symptoms are silent: the card sits in `ready`, or it auto-blocks after two attempts with an error that names a violation the task never caused.

## Pre-flight rules (apply BEFORE creating a card)

1. **The assignee must be an existing profile.** The dispatcher calls `profile_exists(assignee)`; a card whose assignee does not resolve is never spawned and never errors — it waits in `ready` forever. Verify the profile directory exists before assigning.
2. **Forced skills must exist inside the assignee profile.** Profiles are isolated: a skill present in the default root (`/opt/data/skills`) is not inherited by `/opt/data/profiles/<profile>/skills`. Exception: skills of the shared directories declared in `skills.external_dirs` (e.g. a cloned `agent-skills` checkout) are visible to every profile that declares them — check the worker profile's `config.yaml` first. A card with `skills='["foo"]'` crashes immediately with `Error: Unknown skill(s): foo` until the skill directory is copied into that profile. Before batch relaunch, run a smoke test with the exact forced skills, e.g. `hermes -p <profile> --skills foo --skills bar chat -q 'Réponds exactement: OK' -Q`.
3. **The assignee profile must have `worktree: false`.** With `worktree: true` (present in some default configs), the spawned CLI tries to create a git worktree, fails outside a Git repository, prints `--worktree requires being inside a git repository` and exits **rc=0** — with no terminal kanban call, which the dispatcher counts as a protocol violation.
4. **The task workspace must resolve inside the container that runs the dispatcher**, not inside your own. A path only valid in another container yields `spawn_failed` with `workspace: [Errno 13] Permission denied`. Prefer `workspace_kind: scratch` unless you are certain of the target namespace.
5. **Paths in the card body must exist in the worker's container.** Workers run elsewhere; a card citing a path from your own container sends the worker hunting for files it cannot see. State paths in the worker's namespace and expose reference material on a volume both containers mount.
6. **Name the container for every component that must RUN, not just exist.** A worker cannot start a process in another container, and it cannot see the boundary from inside its own. If the deliverable includes a service the *other* container must reach, its placement is part of the spec: state which container it runs in, and scope the worker's deliverable to the mechanism plus the exact procedure — never to "start it yourself". A loopback service started on the wrong side of the boundary is unreachable by design and looks like a working deliverable until someone tries to use it.

## Headless execution constraints

- **Single-query (`-q`) workers cannot answer approval prompts.** Flagged-dangerous commands come back as `BLOCKED: Command flagged as dangerous (...) but single-query mode (-q) runs without a user present to approve it`. This covers `python3 -c`, heredocs and other inline-interpreter shapes — i.e. the natural ways to write a file from a shell. Either set `approvals.single_query_mode: approve` on the worker profile, or instruct the worker to create files with the `write_file` tool (one file per call), reserving the shell for plain commands (`mkdir`, `ls`, `chmod`, `curl`).
- **Write scope is a separate gate from approval.** `write_file` and `patch` refuse any path outside `HERMES_WRITE_SAFE_ROOT`, and the agent image ships `ENV HERMES_WRITE_SAFE_ROOT=/opt/data`. A worker then cannot write its own home or workspace, and every write fails with `Write denied: ... is outside HERMES_WRITE_SAFE_ROOT`. Fix the container-level value (a compose `environment:` entry overrides an image `ENV`) rather than patching profiles one at a time; the variable accepts an `os.pathsep`-separated list.
- **Every run must end with `kanban_complete` or `kanban_block`.** A worker that exits cleanly without one is recorded as `crashed` with `protocol violation`, regardless of the work it did. Treat "worker finished but the card says crashed" as a protocol fault to fix, not a false alarm.

## Auto-block and retry

Two consecutive spawn failures auto-block the card. Neither `worktree: true` nor a wrong workspace path is a task defect — fix the configuration, then `kanban_unblock` to requeue. Unblocking is the supported retry; do not recreate the card and do not assign it to yourself.

## Diagnostic order

Work outward from the worker's own stdout; each step answers a different question.

| Step | Where | Answers |
|---|---|---|
| 1 | `<KANBAN_ROOT>/kanban/logs/<task_id>.log` (board `default`) ou `<KANBAN_ROOT>/kanban/boards/<slug>/logs/<task_id>.log` (autre board) | Did the CLI even start? A startup flag error appears here as plain stdout. |
| 2 | `<profile>/logs/errors.log` and `agent.log` | Full tool errors, un-truncated: blocked commands, denied writes, import failures. |
| 3 | `task_runs` in the board DB | `outcome`, `error`, `metadata` per attempt — separates `spawn_failed` from `crashed`. **Read `ended_at - started_at` per attempt**: <5s deltas point to worktree/CLI startup failures; 60-180s deltas point to timeout. |
| 4 | gateway profile `logs/agent.log` | The dispatcher's own counters: `spawned=`, `crashed=`, `auto_blocked=`, reaped PIDs. |

`KANBAN_ROOT` = `$HERMES_KANBAN_HOME` s'il est défini, sinon la racine Hermes partagée (`/opt/data` ici) — **pas** le `HERMES_HOME` d'un profil : le board est partagé entre profils par conception (vérifié dans `/opt/hermes/hermes_cli/kanban_db.py::kanban_home`). Une requête sur la mauvaise base renvoie 0 ligne sans erreur.

Run `scripts/kanban_diagnose.py <task_id> [--board <slug>]` to print steps 1–3 in one shot (il résout la racine et le board comme le fait Hermes).

## Pitfalls

- A worker's `os.environ` is fixed at spawn: a config or `.env` fix does not reach a run already in flight. Confirm the fix landed only on a fresh run.
- Reading a directory with the file-read tool returns "not a regular file (directory)" — that is a card-wording problem, not a broken worker.
- `git` inside a shared home can fail with `dubious ownership` when the writer's uid differs from the reader's. `git config --global --add safe.directory <repo>` is read-only and sufficient; `chown` needs root and can break the other container's writes.
- Do not conclude "permissions" from a `Permission denied` on a path that is simply absent in that container — the `ENOENT` from `mkdir`ing a missing parent surfaces the same way.
- **Repeated `crashed/crashed` runs at ~60-120s intervals are not always `worktree: true`.** If `task_runs` shows several attempts with `started_at → ended_at` deltas of 60-180s and each crashes with `protocol violation`, the worker is being killed by `terminal.timeout` (default 180s) or `runtime.lifetime_seconds` (default 300s) before it can call `kanban_complete`. The fix is in the worker profile: raise `terminal.timeout` and `runtime.lifetime_seconds` to 600s minimum when the worker handles long-running tasks (large PDF reads, full-corpus scans). Confirm with the user before editing a shared profile.
- **Distinguishing the two `rc=0 protocol violation` causes from `task_runs` alone is unreliable** — both produce identical `crashed/crashed` + `protocol_violation` events. The differentiator is the run duration pattern: worktree failures crash in <5s (CLI fails before worker body runs), timeout failures survive 60-180s (worker body runs and is killed mid-task). Always read `ended_at - started_at` per run before assuming the cause.

## Stale completion recovery (fiche/synthesis written, card blocked)

When a worker writes the artifact to disk but exits without calling `kanban_complete`, the card accumulates `consecutive_failures` until it auto-blocks. The fix is a single Python probe that cross-checks the board against the filesystem:

```
python3 scripts/kanban_fix_stale_completion.py <assignee> --fiche-dir <dossier> [--syn-dir <dossier>] [--board <slug>]   # dry-run
python3 scripts/kanban_fix_stale_completion.py <assignee> ... --apply   # actually fix
```

The script handles two cases:
- **fiche/synthesis exists on disk** → marks the card `done`, resets `consecutive_failures`
- **artifact missing + card blocked** → resets to `ready` for a fresh retry

Always run the dry-run first. On a board with dozens of blocked cards, run it once per assignee (par ex. un profil lecteur et un profil stratège) before manually unblocking anything.

**Typical symptom**: a burst of `✖ gave up after repeated spawn failures / protocol violation` notifications in quick succession, all for the same assignee, most of which have `consecutive_failures` ≥ 2 and `worker_pid = None`. The board shows `running` or `blocked` but the artifact is already on disk.

**This pattern is expected** when `lifetime_seconds` in the worker profile is too short for the task (e.g. a 500-page PDF takes 8 minutes to read but `lifetime_seconds: 300` kills the worker at 5 min). Raise `lifetime_seconds: 900` and `terminal.timeout: 300` in the profile before retrying. The profile change only affects fresh runs, not the current blocked ones — fix those with the script above, then re-dispatch.

**Routine**: when the session starts seeing `✖ protocol violation` notifications in volume, run the fix script proactively rather than waiting for each notification to arrive one-by-one.
