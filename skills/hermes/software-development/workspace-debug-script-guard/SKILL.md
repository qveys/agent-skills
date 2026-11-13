---
name: workspace-debug-script-guard
description: "Use when writing a throwaway script under /workspace."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [workspace, scripts, scratch, hygiene, git-hooks]
---

# Workspace debug script guard

## When to Use

- Avant d'écrire un script jetable (probe, check, extract, expérience) ou un fichier généré sous `/workspace/`.
- Avant de livrer un fichier à l'utilisateur via `MEDIA:` (où le placer).
- Les projets `trading` et `brain` ci-dessous sont des exemples présents sur cette instance ; pour un autre projet, lire son `AGENTS.md` et appliquer le même principe (dossier scratch du projet, jamais la racine).

## The rule

All work output lives under `/workspace/` — at minimum. Never write deliverables, assets, or generated files to `/opt/data/cache/` or other scratch paths, because the gateway that delivers `MEDIA:` files cannot fetch them from there (observed: a valid PNG in `/opt/data/cache/scratch` was rejected, and it displayed only after being copied under `/workspace`). (Distinction : un script/sonde **jetable** qui ne livre rien peut vivre dans le scratch du runtime, `$TMPDIR` — ici `/opt/data/cache/scratch`, purgé après 24 h — mais jamais à la racine de `/workspace` ni d'un projet ; seul ce qui doit être **livré** doit être sous `/workspace`.) Deliverables go in a named subfolder of `/workspace/` (e.g. `/workspace/assets/<topic>/`), and the `MEDIA:` path must point there.

When working under `/workspace/`, any throwaway script written to probe, extract, check, or experiment MUST live under the project's sanctioned scratch directory — NEVER at `/workspace/` itself, and NEVER at any project root (`/workspace/trading/`, `/workspace/brain/`).

The reason is operational, not aesthetic:

- Project roots are reserved for stable tooling and curated structure. Root-level `.py` files violate the explicit "aucun fichier à la racine" rule in `trading/AGENTS.md` and the equivalent organization in `brain/AGENTS.md`.
- Files dropped directly in `/workspace/` are invisible to any project's gitignore and risk being committed from a worktree branch by accident.
- 28 such files accumulated on 2026-09-24 between 12:24 and 14:11 before being cleaned up. The user flagged this as a reproducible defect.

## Where to put scripts per project

### Trading project — `/workspace/trading/`

- **Probe / check / discover** (`check_*.py`, `find_*.py`, `quick_*.py`): `/workspace/trading/out/_stray/<YYYYMMDD-HHMMSS>/check_*.py`
- **Extract** (`extract_*.py`, `read_*.py`): `/workspace/trading/out/_stray/<YYYYMMDD-HHMMSS>/extract_*.py`
- **Outputs** (`.json`, `.txt` produced by the above): same directory as the script that produced them. NEVER at `/workspace/`.
- **Scripts that graduate into real tools**: promote them to `/workspace/trading/tools/<name>.py` after the user approves — do not leave them as `out/_stray/`.

The timestamp format is `YYYYMMDD-HHMMSS` in Europe/Brussels timezone (matches the existing `out/_stray/` layout). If multiple scripts are written within the same minute, append a short suffix (`-a`, `-b`) — never skip the timestamp.

### Brain project — `/workspace/brain/`

- The vault is git-managed via `scripts/brain-agent-sync.sh`. Each agent works only in its worktree branch (`agent/<nom>`), and the sync script refuses changes outside `Second-Cerveau/`.
- Debug scripts specific to brain operations go under `/workspace/brain/scripts/` (existing convention; see `.agents/scripts/` examples) — never at `/workspace/brain/` root, never under `/workspace/`.
- For one-off vault probes, prefer using existing `.agents/scripts/` or create a new dated script there; do not pollute the project root.

### Non-project assets and deliverables — `/workspace/assets/<topic>/`

- Images, logos, exports and their generator script go in `/workspace/assets/<topic>/` (create it with `mkdir -p`). The generator script is re-runnable and sits next to its outputs.
- Do not leave the previous version's files in a state that makes the new one ambiguous: name versions explicitly (`-v2`) and say which one is current.

### Workspace root — `/workspace/`

There is no sanctioned location here. If you need to write a script that genuinely does not belong to either project (very rare), escalate to the user first — do not silently create one at `/workspace/`.

## How to create the directory

```bash
TS=$(date -u +%Y%m%d-%H%M%S)  # or Europe/Brussels if TZ is set
mkdir -p /workspace/trading/out/_stray/$TS
```

If `out/` does not exist yet, create it — that is the project's sanctioned output location per `trading/AGENTS.md`.

## What the guard refuses

- `write_file(path="/workspace/check_*.py", ...)` — refused; redirect to the project's scratch dir or escalate.
- `write_file(path="/workspace/trading/foo.py", ...)` for any non-stable script — refused; either graduate to `tools/` or move to `out/_stray/<ts>/`.
- `write_file(path="/workspace/brain/foo.py", ...)` for any non-stable script — refused; either graduate to `scripts/` or `.agents/scripts/` or escalate.
- `terminal("python /workspace/check_pdf.py ...")` for a script that does not exist in the canonical location — refuse, recreate under the project's scratch dir first.

Stable, project-level scripts (`tools/pdf/extractor.py`, `scripts/read_personal_finance.py`, `tools/inventory.py`, `.agents/scripts/*`) are NOT in scope — those have a real home.

## Git safety nets already deployed

- `/workspace/trading/.git/hooks/pre-commit` — refuses any `.py` at the trading project root, plus large `.json` (>100 KB) at the same root.
- `/workspace/brain/.husky/pre-commit` — prévu pour refuser tout `.py` à la racine de brain, mais **absent** au 2026-10-24 (`ls` négatif) : à installer (voir `git-worktree-workflow` : un hook `.husky/` n'est actif qu'après `husky install`, sinon copier dans `.git/hooks/`). Brain a déjà un hook `commit-msg` pour valider les messages.

These hooks are the last line of defense. The skill is the first.

## Self-check before each write

Ask yourself three questions before writing any `.py` or large `.json`:

1. Is this a one-shot probe/check/extract, or a stable tool? If one-shot → project's scratch dir.
2. Will the file be referenced again after this turn? If no → project's scratch dir.
3. Does the path start with `/workspace/` or any project root and end with a single descriptive filename? If yes → almost certainly wrong; move under the project's scratch dir or `tools/`/`scripts/`.

If all three say "stable, reusable, properly named, in `tools/`/`scripts/`", proceed. Otherwise redirect.

## Cleanup cadence

`out/_stray/<ts>/` directories in trading are scratch by design. The trading project already has a `hermes worktree audit|prune` workflow for `.worktrees/`; a similar `tools/stray_clean.py --older-than 7d` could exist if cleanup becomes painful. Until then, leave them — they are out of the way and self-documenting by timestamp.
