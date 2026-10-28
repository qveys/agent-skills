---
name: obsidian-vault-health
description: Use when fixing Obsidian vault health reports.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [obsidian, vault, health, wikilinks, markdown]
    related_skills: [obsidian]
---

# Obsidian Vault Health

Use this skill when the user asks to fix an Obsidian vault-health, vault-lint, broken-wikilink, inbox-drain, duplicate-note, or note-naming report.

## Procedure

1. **Load the general Obsidian workflow first.** Use the `obsidian` skill for vault path resolution and file-tool conventions, then resolve the concrete vault path before reading or editing files.
2. **Reproduce the report.** Inspect the vault's own conventions (`AGENTS.md`, vault map files, and health-script comments), then run the same health command/script that produced the report so the baseline counts are grounded.
3. **Classify issues by source.** Separate living notes, templates, archives/imports, inbox captures, and generated/raw source notes. Respect exclusions encoded by the vault's health script; do not repair files the script intentionally ignores.
4. **Repair wikilinks against canonical targets.** Search filenames and content before creating any note. Prefer retargeting to existing canonical notes with short wikilinks; use `[[target|alias]]` when the visible label matters. Create small entity anchor notes only for durable recurring concepts that genuinely have no existing note.
5. **Drain inbox without deleting.** For inbox files that are non-conforming, duplicated elsewhere, or raw captures, preserve originals by moving them into a descriptive archive/import batch under the vault's archive area when one exists. Do not normalize filenames inside the archive unless the vault explicitly requires it.
6. **Patch narrowly.** Patch only living notes that the health script analyzes. Avoid broad replacements across archives/templates because they can alter provenance and are often excluded by design.
7. **Verify with the health command.** Re-run the health script after edits. Keep working until the target report is clean or explicitly label any remaining issue that needs user judgment.
8. **Report Git shape.** If the vault is a Git repository, check status/diff summary after verification. Explain moves as `deleted from source + untracked/added archive batch` when not staged, so the user does not confuse preservation with deletion.

## Pitfalls

- Do not claim a vault is fixed from manual inspection alone; the health command's final output is the proof.
- Do not create duplicate concept notes before searching for canonical names; Obsidian health failures often come from naming drift, not missing knowledge.
- Do not rewrite archived/imported material just to satisfy live-note conventions; archives preserve provenance and many vault health scripts exempt them.
- Do not turn an inbox drain into data loss; move raw notes to an archive batch unless the user explicitly approves deletion.
- Exclude keepers such as `.gitkeep` from inbox occupancy counts; a keeper is not content, and counting it makes an empty inbox look occupied forever.
- When a check script enforces a size cap on a living control file, shrink that file to the cap rather than raising the cap, unless the user owns the checker and asks to change it.
