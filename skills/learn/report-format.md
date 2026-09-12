# /learn output format

Two files in the run directory. `report.md` is for the user. `actions.json` is for the apply step. Every action in `actions.json` must appear in `report.md`, and every claim in sections 1–3 of `report.md` must be backed by a verifier's Kept list.

## report.md

Write short sentences with one meaning each. No hedged summaries: a count is a number, a path is a path.

```markdown
# /learn report — <today>

## Overview
Problem: <2–4 sentences: what the traces show the user repeating, correcting, or never using>
Proposed change: <2–4 sentences: the smallest set of harness edits that removes that repetition>
Actions: <N> total — <a> new skills, <b> skill updates, <c> enables, <d> deletes/disables, <e> need a decision

## 1. Repeated phrases -> skills
| # | Phrase (quoted) | Sessions | Owner | Action |
Owner is an existing skill (name, path) or NEW <name>. Action is the action id from actions.json.

## 2. Skills to update
| # | Skill (path) | Stale line (quoted) | Evidence (session ids) | Replacement | Action |

## 3. Unused -> delete or disable
| # | Name | Kind | Count | Last used | Why safe | Action |
Kind is skill, plugin, mcp, workflow, or hook. "Why safe" names what still does the job, or says `only copy — ask`, or `referenced by <names> — ask`.

## 4. Gaps
Recurring needs with no owner. No action ids; these are for the user to decide.

## Unverified claims
Only present when a verifier section failed: the claims from that section, listed but not acted on unless the user asks; any action emitted for them carries `requires_confirmation: true`.

## Dropped claims
Bullet list: claim, reason it was dropped (which verifier, what failed). Include "previously rejected by the user" items here.

## Coverage
- sessions seen / kept / dropped by reason (from manifest.json)
- human turns read; sessions read by mappers vs total
- map or reduce slots lost; verifier sections that failed
- window and filters used (params from manifest.json)
- what this run could not see: subagent/sidechain sessions unless included, hook use, managed MCP servers, anything outside the scanned harness homes
```

## actions.json

```json
{
  "run_dir": "<run_dir>",
  "generated_at": "<today>",
  "actions": [
    {
      "id": "A1",
      "kind": "skill | plugin | mcp | workflow | hook | config",
      "action": "create | edit | enable | disable | delete | propose | ask",
      "target": "<name>",
      "path": "<absolute path of the file or directory the action touches>",
      "protected": "plugin | bundled | git-tracked | null",
      "referenced_by": ["<loaded skill names that mention this skill>"],
      "reversible": true,
      "requires_confirmation": false,
      "evidence": {
        "sessions": ["<session id>", "..."],
        "count": 0,
        "quote": "<exact phrase or stale line, at most 300 chars>"
      },
      "reason": "<one sentence>",
      "edit": {
        "anchor": "<exact substring of the current file, or \"\" for create>",
        "replacement": "<full replacement text, or full file content for create>",
        "mode": "replace | insert_after | append"
      }
    }
  ]
}
```

Rules for the fields:

- `id` is `A1`, `A2`, … in report order.
- `path` is exact. For `plugin` and `mcp` actions it is the config file named in `surfaces.json` (for example `~/.grok/config.toml`, `~/.claude/settings.json`, `~/.claude.json`), and `edit.anchor` is the exact list or table header line to change. Never include config values other than names.
- `reversible` is `true` for edits with an anchor, enables/disables, and deletes (the apply step moves deleted files to `<LEARN_HOME>/trash/<run name>/`). It is `false` only when the apply step cannot undo the change from the trash directory or the anchor.
- `protected` and `referenced_by` are copied from `surfaces.json`. A protected skill is never edited or deleted in place: the action is `propose`, with `requires_confirmation: true` and a `reason` that says where the fix belongs — a user-skill override with the same name for `plugin` and `bundled`, a pull request for `git-tracked`. `propose` carries an `edit` block so the apply step can write the override or the patch.
- A `delete` whose `referenced_by` is non-empty is emitted as `ask`, and `reason` names the referrers.
- `requires_confirmation` is `true` for `ask`, `propose`, any `delete` of the only copy of a job, and any unverified claim.
- `edit` is required for `create`, `edit`, and `propose`; omit it for enable, disable, delete, ask.
- `create` writes `<user skills dir>/<name>/SKILL.md` (`user_skills_dir` from `surfaces.json`). The `replacement` is the whole file: `---` frontmatter with `name`, `description` (what it does plus the trigger phrases), then a body of imperative steps. Use the quoted phrases as the trigger list and the body.
