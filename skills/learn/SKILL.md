---
name: learn
description: >-
  Use when the user runs /learn, asks to learn from traces or past sessions,
  tune skills from how they actually work, or find unused skills, plugins, or
  MCP servers. Not for summarizing sessions into notes or memory.
user-invocable: true
argument-hint: "[--mode step|auto|report] [--days N | --since-last | --limit N] [--harness all|claude,grok,codex,cursor] [--per-trace] [--include-subagents] [--cwd PATH] [--focus TEXT] [--resume]"
---

# learn

Read the sessions this user sat at — Claude Code, Grok Build, Codex, Cursor, whichever are installed — find what they repeat, correct, and never use, and change the harness so the next session needs less typing.

State lives in `LEARN_HOME` (default `~/.learn`). Session stores are discovered next to each product (`~/.claude/projects`, `~/.grok/sessions`, `~/.codex/sessions`, `~/.cursor`). New skills are written to `user_skills_dir` from `surfaces.json` (prefers `~/.agents/skills`, the cross-runtime folder).

```
You (whatever coding agent is running this skill)
│
├── 0. state.py get → resume a pending run; collect_sessions.py --estimate → price per scope
├── 1. collect_sessions.py  → <run>/sessions/*.json, surfaces.json, usage.json, phrases.json
├── 2. Map-reduce (native `workflow` first, then subagents, then yourself)
│      Map     one note per batch of sessions → <run>/map/<range>.md   (signals.md)
│      Reduce  merge until one synthesis remains
│      Verify  three skeptics: phrases, stale lines, deletes — keep or drop, add nothing
│      Report  report.md + actions.json                                 (report-format.md)
├── 3. Short version in chat
└── 4. Curate with the user → apply → decisions.jsonl → state.py → done
```

Files next to this SKILL.md: `collect_sessions.py`, `state.py`, `learn-traces.rhai` (the map-reduce workflow), `signals.md`, `report-format.md`. Use `learn-traces` through the runtime's `workflow` tool whenever that tool exists; subagents are the fallback, not the default.

Host commands must work in bash **and** PowerShell: no `mkdir -p`, `mv`, `chmod`, `rm`, `date`, `echo >>`, no writing to `/tmp` by hand, and no hard-coded interpreter name; the two Python helpers do all filesystem work. Once per session, probe for an interpreter by running `state.py get` with `python`, then `py -3`, then `python3`; the first that prints JSON (exit code 0, or 3 when a run is pending) is the one to use. Its `python` field is the interpreter's absolute path and its `learn_home` field is the resolved home; use those two values as `<PYTHON>` and `<LEARN_HOME>` in every later command, always double-quoted. If none of the three runs, tell the user to install Python 3 and stop. Placeholders: `<skill dir>` is the directory holding this SKILL.md; `<user skills dir>` is `user_skills_dir` from `surfaces.json`; `<RUN>` is the run directory the collector prints; `<run name>` is its last path component.

If the user asked to summarize learnings into memory or notes rather than change skills, do not run this skill; use the memory tools and say why.

## 0. Resume or set up

The `state.py get` call above is also the resume check. Exit code 3 means a run is pending; `pending.run_dir` is its directory and `pending.status` says where it stopped:

- `report_ready` or `curating` — the report exists but was never curated. Tell the user the run date, the session count, and the action count from `<run_dir>/actions.json`, and offer to resume at step 3. `decisions.jsonl` lines already written for that run are respected.
- `running` with no `report.md` — the map-reduce was interrupted. Offer two choices: read the partial synthesis (newest file under `<run_dir>/reduce/` if any, else `map/*.md`) and stop, or start a fresh run.
- `collected` — sessions were collected but analysis never launched. Offer to launch it (skip to step 2 with that run dir) or start fresh.
- `--resume` takes the first offer in each case without asking.

For a new run, price it before deciding anything:

```bash
<PYTHON> <skill dir>/collect_sessions.py --estimate [--batch 1]
```

It scans every installed harness in about a second and writes `estimate.json` (its `out` field is the path): for each scope (`all`, `30d`, `14d`, `quick` = the 25 most recent sessions, `since_last` when a completed run exists) the kept session count, agent count, estimated tokens, and a wall-time range, plus a `recommended` scope. If every scope has 0 sessions, tell the user there is nothing to learn from yet and stop.

Then read what the user typed and pick one of three paths. Depth words and go words combine ("just run it, quick" = `auto` + `quick`); explicit flags win over wording. Two rules override both: a first-ever run (no `last_completed_at` in `estimate.json`) is always `step`, because `auto` removes zero-use skills and the user has never seen a report; and above 40M estimated tokens, ask before launching.

- **They told you to go.** "just run it", "go ahead", "don't ask", "auto", "you decide" → mode `auto`, scope = the recommended one. Do not ask. State the choice and its price in one line before launching.
- **They told you the depth.** "quick" / "cheap" / "light" → `quick`; "everything" / "all of it" / "deep" → `all`; "per trace" → `--per-trace`; "since last time" → `since_last`. Mode stays `step` unless they also said to go.
- **Neutral** (bare `/learn`, "learn from my traces") → ask once, two questions, then do not ask again until curation:
  - **Mode** — `step` (recommended): present each group of actions and apply what the user picks. `auto`: apply every reversible action, then ask once about the rest. `report`: write the report, change nothing.
  - **Scope** — one option per scope in `estimate.json`, each labeled with its price. Mark the recommended one.

If a structured multiple-choice tool exists in this runtime, use it. If it errors or does not exist, ask the same two things in one plain-text line ("reply like `step, since-last`") and take exactly what they type.

`--per-trace` is one map note per session (about twice the tokens; default batches of 10). `--limit N` keeps the N most recent. `--focus TEXT` is a lens for mappers; it cannot remove a report section. `--cwd PATH` limits collection to one working directory. `--harness claude` (or `grok`, `codex`, `cursor`, or a comma list) limits which session stores are scanned; default is every store that exists.

## 1. Collect

```bash
<PYTHON> <skill dir>/collect_sessions.py [--days N | --since-last | --limit N] [--harness LIST] [--batch 1] [--include-subagents] [--cwd PATH] [--drop-pattern REGEX]
```

The collector picks the run directory (`<OS temp dir>/learn/<UTC timestamp>`) and prints it as `run_dir` in its last stdout line; use that value as `<RUN>` everywhere below.

A session is kept when a human sat at it: not a subagent/sidechain unless included, not a one-word smoke test with no tool use, and at least one real human prompt. CI security-review prompts and the `/feedback` template are dropped by default. Pasted credentials are redacted before anything is written.

Tell the user the coverage line (`seen`, `kept`, `dropped` by reason, `harnesses`) **before** launching analysis, and say plainly that the prompts from those N sessions will be sent to the model. If `kept` is 0, fix the scope before going on.

## 2. Map-reduce

Read `signals.md` and `report-format.md` now. Then produce `<RUN>/report.md` and `<RUN>/actions.json`.

The script cannot read the parent conversation, so every launch uses the same `args = {run_dir: <RUN>, count: manifest.sessions_kept, skill_dir: <skill dir>, grok_home: <LEARN_HOME>, python: <PYTHON>, batch: 10 (1 for --per-trace), fan: 10, today: "<YYYY-MM-DD>", user_label: "<name or 'the user'>", focus: "<text or omit>"}`. Per-trace runs over ~110 sessions need an `agent_budget` above the default 128.

How to run the analysis — **stop at the first match**; do not skip a native workflow in order to spawn subagents:

1. **This runtime has a `workflow` tool** — that is the proprietary engine. Use it.
   - If `learn-traces` is already in the available workflows list, launch with `source = {type: "name", name: "learn-traces"}`.
   - Else if a user or project copy exists (`~/.grok/workflows/learn-traces.rhai`, or `<git root>/.grok/workflows/learn-traces.rhai` from `manifest.json` → `project_roots`), launch that file with `source = {type: "script_path", script_path: "<that path>"}`. A user/project copy wins over the skill copy.
   - Else if `<skill dir>/learn-traces.rhai` exists, read it with the file tools, write it to the directory the `workflow` tool trusts (on Grok Build: `~/.grok/workflows/learn-traces.rhai`; never invent another folder), and launch with `source = {type: "script_path", script_path: "<that trusted path>"}`.
   - If the `workflow` tool exists but every one of those sources is missing, stop and say the skill install is incomplete (`learn-traces.rhai` should sit next to this SKILL.md). Do not reconstruct the workflow from memory, the web, or the binary.
   - The run notifies you when done; do not poll. Closing the TUI stops a Grok workflow; leaving the session idle is fine.
2. **No `workflow` tool, and this runtime can spawn parallel subagents** — one mapper per batch of session JSON files under `<RUN>/sessions/` (batch size 10, or 1 for `--per-trace`). Each mapper reads only its files plus `signals.md` and writes `<RUN>/map/<from>-<to>.md`. Then reduce those notes (groups of 10) until one synthesis remains. Then three verifiers (phrases, stale lines, deletes) that keep or drop, add nothing. Then one reporter that writes `report.md` and `actions.json` in the shape of `report-format.md`.
3. **Neither** — do the same map → reduce → verify → report loop yourself, still writing the files under `<RUN>/`. Do not skip the files; curation in step 4 reads them.

Before starting, tell the user the coverage line and the price from `manifest.json` → `estimate`. Then:

```bash
<PYTHON> <skill dir>/state.py set --run-dir <RUN> --status running --mode <mode> --scope <scope>
```

If the user asks how it is going, list `<RUN>/map`, `reduce`, `verify` and say which phase is writing.

## 3. Present

Read `report.md`. Give the user the Overview, the three tables trimmed to their top rows, the Coverage line, and the path to the full report. Keep it under a screen; do not paste `actions.json`. If the report's headline names a skill as missing, check `slash_commands_with_no_loaded_skill` in `usage.json` first: the skill may exist in a root the collector did not scan.

## 4. Curate and apply

`actions.json` is the work list (fields in `report-format.md`). Consent rules, identical in every mode:

- An action is applied only when the user picked its id, or in `auto` mode when it is reversible and not `requires_confirmation`.
- A free-text answer is not consent. Re-ask with the literal reading as options before writing anything.
- Options the user left unpicked are `deferred`, not `rejected`. Only an explicit refusal is `rejected`. Deferred items return next run; rejected ones do not.
- One group's answer never authorizes another group.
- Before recording rejections, re-read the answer once: a single-item pick on a multi-select that offered many is the shape of an accidental Enter. Apply the pick, defer the rest, and say so.

Apply mechanics:

- `create` — write `edit.replacement` to `path` (`<user skills dir>/<name>/SKILL.md`), creating the directory.
- `edit` — before the first edit to any file in a run, read it and write an untouched copy to `<LEARN_HOME>/trash/<run name>/originals/<name>.md`. Then replace using `edit.anchor` / `edit.mode` (`replace`, `insert_after`, `append`). If the anchor is missing, re-read the file and fix the anchor; never overwrite the whole file.
- `propose` — the target is protected. For `plugin` or `bundled`: read the protected SKILL.md in full, apply the edit to that text, and write the **complete** result to `<user skills dir>/<name>/SKILL.md`. For `git-tracked`: write the patch to `<RUN>/patches/<name>.diff` and tell the user it needs a pull request. Never edit a plugin, bundled, or git-tracked file in place.
- `enable` / `disable` — edit only the plugin enabled/disabled lists in the config file named by `path`. Read only that block.
- `delete` — if `referenced_by` is non-empty, stop and ask, naming the referrers. Otherwise `<PYTHON> <skill dir>/state.py trash --run-name <run name> <path>` moves the skill directory, workflow file, or hook file into `<LEARN_HOME>/trash/<run name>/`. For an MCP server, cut its table/object out of the config named by `path`, write it to `<LEARN_HOME>/trash/<run name>/mcp-<name>.toml` (or `.json`), then `state.py restrict` that file **before** removing the key. Do not copy whole config files.
- After each apply, re-read the changed file or config block and confirm the change is present.

By mode:

- **step** — one question per group: 1 (phrases → create/edit), 2 (updates), 3 (deletes/disables), then 4 (gaps, discussion only). At most eight options per question. Apply the picked ones before the next group, and write `deferred` for the unpicked ones the moment the group closes.
- **auto** — apply every action with `requires_confirmation: false`, then one question for the rest, then apply the picked ones.
- **report** — stop after step 3, then set the state to `done`.

Record every decision with `<PYTHON> <skill dir>/state.py decide --run-dir <RUN> --id A3 --kind skill --action delete --target <name> --path <path> --decision applied|rejected|deferred [--undo <trash path>]`.

Set `state.py set --run-dir <RUN> --status curating` when group 1 opens and `--status done` when the last group closes or the user stops. After a completed run, the estimate's `since_last` scope is the recommended one.

Finish with what changed (paths), what was rejected or deferred, how to undo, and the full report path.

## Rules

- Zero hits is evidence, not proof. The only copy of a job is an `ask`, not a delete. A skill other loaded skills reference is not a free delete.
- Unused **plugin** and **bundled** skills are not delete candidates; `usage.json` → `unused_loaded` is user and project skills only.
- One repeated phrase is one action; it joins the skill that already owns the job when one exists.
- Never print secrets: tokens, headers, env values, API keys, auth files. Inventory is names and paths only.
- If the user disputes a count, re-run the collector; do not guess.
- Skill edits follow the usual skill-design principles of this runtime.
