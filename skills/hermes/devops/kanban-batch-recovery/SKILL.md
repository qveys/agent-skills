---
name: kanban-batch-recovery
description: "Use when recovering batches of blocked Kanban cards."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [kanban, dispatch, recovery, batch, profiles]
    related_skills: [kanban-orchestration, kanban-worker-dispatch]
---

# Kanban batch recovery

## When to Use

- Plusieurs cartes d'un board sont `blocked` par une même panne fournisseur/profil/dispatch et l'utilisateur demande une reprise ciblée.
- À ne pas utiliser pour une seule carte (voir `kanban-worker-dispatch`).

Use this when many cards on one board are blocked by a shared provider/profile/dispatch fault and the user asks for a targeted batch recovery. The goal is to restore only recoverable work while preserving real `needs_input` blocks.

## Procedure

### 1. Snapshot and classify before writing

Read the board database in read-only mode and classify every `blocked` task by `assignee`, `block_kind`, `last_failure_error`, latest `task_events.payload`, and, for crash cases, the per-task run log.

```python
import sqlite3
from pathlib import Path
DB = Path('<KANBAN_ROOT>/kanban/boards/<board>/kanban.db')  # KANBAN_ROOT=/opt/data ou $HERMES_KANBAN_HOME ; board default : <KANBAN_ROOT>/kanban.db
conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
```

Use categories that drive different actions:

| Category | Signal | Action |
|---|---|---|
| transient provider | `Model is unavailable`, `BadRequestError`, HTTP 400 and no `needs_input` | candidate for requeue after profile smoke test |
| missing forced skill | run log contains `Unknown skill(s): ...` | install/copy skill into assignee profile, then smoke test |
| missing venv in worktree | run log contains `ModuleNotFoundError` inside `.worktrees/*` | fix tool backend discovery to traverse parent directories up to repo root |
| true human/rework block | `block_kind='needs_input'` or review rejection | fix substantive document defect, commit, then unblock |
| timeout | `elapsed ... > limit ...` / `timed_out` | do not mix with provider recovery; inspect runtime profiling & loops first |

### 2. Preserve `needs_input` as work, not noise

Never requeue `block_kind='needs_input'` in a transient-error batch. For review cards, generate a durable list for the producing profile instead: `review_task_id`, parent task IDs, review title, and concise reason. This gives the user the true reprise list without erasing the reviewer’s verdict.

### 3. Fix profiles before any unblock

For each affected assignee profile, correct the shared cause before touching task status:

- set the intended `model.provider` and `model.default`;
- keep `worktree: false` for scratch/non-git worker workspaces;
- ensure every forced skill exists under `/opt/data/profiles/<profile>/skills/<skill>/SKILL.md` (or in a dir the profile lists in `skills.external_dirs`, e.g. a cloned `agent-skills` checkout), not only in the default root;
- for a zero-cost chain, set `auxiliary.free_only: true` so title/judge/auxiliary calls cannot take a paid fallback lane.

### 4. Smoke-test the exact worker path as a hard gate

Run the same profile and forced skills the dispatcher will use:

```bash
timeout --signal=TERM --kill-after=10s 90s \
  /opt/hermes/.venv/bin/hermes -p <profile> --cli --accept-hooks \
  --skills <skill-a> --skills <skill-b> \
  chat -q 'Réponds exactement OK, sans outil ni modification.' -Q
```

If the smoke test returns HTTP 429/free quota exhausted, or any non-OK provider failure, **STOP before requeue**. Save the selected task IDs and the quota reset signal, then wait or schedule a retry after reset. Requeueing while the exact smoke path fails just consumes retries and recreates the same blocked batch.

### 5. Requeue only the selected transient cards

For each selected card, re-read its current state, ensure no original worker still owns a live run, and add a short comment explaining the resolved cause and the successful smoke test. Then call the supported `kanban_unblock(board=<explicit-board>, task_id=<id>)` tool. It respects parent gating and resets consecutive dispatch failures while preserving the block-loop counter.

Do not write task statuses directly in SQL, erase errors, or reset `block_recurrences`: bypassing the kernel loses dependency and loop-breaker protection. Keep read-only SQLite for bulk audits only. Do not mark a card done merely because its artifact exists; validate every acceptance criterion and the artifact version first.

Do not delete events, comments, runs, or attachments; they are the audit trail.

### 6. Verify the recovery

After the write, read back counts by `status` and `assignee`, then wait at least one dispatcher tick and verify real pickup via `running` tasks plus logs/PIDs. A SQL update to `ready` is not proof that workers ran.

## Pitfalls

- **Do not batch-unblock everything named `blocked`.** `needs_input` is a substantive verdict and must remain visible; mixing it with provider failures erases the work queue the user actually needs.
- **Do not requeue on a failing smoke test.** The dispatcher is deterministic enough to fail the same way at scale; a single exact smoke failure is cheaper than dozens of auto-blocks.
- **Do not let zero-cost work use paid auxiliaries.** A free main model can still trigger paid auxiliary/fallback calls unless `auxiliary.free_only: true` is set in each affected profile.
- **Do not classify timeouts without logs.** They may come from artifact/completion failures, undersized runtime limits, or repeated provider 429 sleeps. Inspect both provider logs and artifact state; raising runtime limits cannot repair an exhausted quota.
- **Bound smoke tests and inspect their session-specific errors.** A timeout with only `session_id` on stdout can conceal a 429 followed by a long retry sleep. Inspect the emitted session in profile logs before retrying; distinguish the primary provider from every configured fallback. Record only sanitized provider/model/error/limit/reset evidence, not raw account identifiers or credential payloads.
- **Treat the reset header as an earliest retry signal, not proof of recovery.** Convert epoch milliseconds into an explicitly named timezone. Require a new exact-profile smoke test after the reset; never bulk requeue merely because that time passed.
- **Tools executed in git worktrees cannot assume `.venv` at `parents[2]`.** Git worktrees isolate checkouts into `.worktrees/<id>/`; untracked virtual environments stay in the primary repository root. Tool scripts must traverse parent directories recursively to locate `.venv` and `.pdfvenv`.
- **Avoid nested/quadratic parser invocations in document refinement.** Calling a full document extractor inside a per-page refinement loop causes catastrophic timeouts on large files (>500 pages). Open document handles once and query specific pages directly.
- **Keep main and auxiliary availability separate.** Some Hermes versions reject `openrouter/free` under `auxiliary.free_only` because the guard recognizes only `:free` SKUs. Confirm the local warning/source before proposing a verified free auxiliary SKU; do not disable the free-only guard or change a shared profile without authorization.
