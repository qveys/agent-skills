# Agent Skills Repository

This repository serves as the central, versioned source of all AI agent skills for Qveys. It allows centralized management of proprietary skills and synchronization of third-party vendor skills from upstream repositories.

## Why this repository exists

1. **Centralization**: Provide a single source of truth for agent skills that can be consumed by tools like Housekeeper, Hermes, Paperclip, Claude Code, and Codex.
2. **Provenance Tracking**: Track exact origins, versions, and updates of third-party skills.
3. **Immutability of Vendored Skills**: Keep vendored skills exactly as they are upstream to ensure clean updates without manual conflict resolution.

## `skills/` vs `vendor/`

- `skills/`: Contains proprietary or customized skills. You have full control over these.
- `vendor/`: Contains unmodified copies of third-party skills. **NEVER manually modify files in `vendor/`.** Any changes should be done by duplicating the skill into `skills/` or submitting a PR upstream.

## How to add an upstream skill

Add an entry to `sources.yaml`:

```yaml
  - id: my-awesome-skill
    repo: author/repo
    ref: main
    path: path/to/skill
    destination: vendor/author-repo/my-awesome-skill
```

Then run `npm run skills:sync -- --id my-awesome-skill` (or `npm run skills:sync -- --all` to sync all enabled sources).

## How to check for updates

```bash
npm run skills:check
```

This will compare the installed SHAs in `sources.lock.yaml` against the latest commits of the defined `ref` in the remote repositories.

## How to synchronize

```bash
npm run skills:sync -- --all          # all enabled sources
npm run skills:sync -- --id <id>      # a single source
```

This command will fetch any missing or updated skills and update `sources.lock.yaml`. It does not execute any code downloaded during the sync process.

The `--` is required: without it, npm consumes `--all`/`--id` as its own options and the CLI never receives them.

## `sources.yaml`

A declarative manifest defining what upstream skills you wish to track.

## `sources.lock.yaml`

A generated file acting as a lockfile (similar to `package-lock.json`). It records the precise commit SHA, timestamp, and source information of what is currently installed in `vendor/`.

## Automated Workflows

A GitHub Actions workflow (`.github/workflows/sync-upstreams.yml`) runs periodically to check for upstream updates. If updates exist, it creates or updates a Pull Request with the changes. **It never pushes directly to `main`.**

## Customizing an Upstream Skill

If you need to change a vendored skill:
1. Copy the folder from `vendor/...` to `skills/...`.
2. Customize your local copy in `skills/`.
3. (Optional) Remove the entry from `sources.yaml` if you no longer want to track the upstream version.

## Consuming this repository from Agents

- **Hermes**: Use the path to this repository as the external skills directory.
- **Housekeeper**: Mount this repository as a read-only Docker volume, or selectively copy specific skills.
- **Paperclip**: Import skills from this repository path rather than pointing directly to the numerous upstream repositories.
- **Claude Code**: Install skills as plugins from the `qveys-skills` marketplace, or symlink them into `~/.claude/skills/` (see below).
- **Codex / etc.**: Point the respective configuration or prompt injection to load skills from this unified repository.

### Installing into Claude Code via the marketplace

`.claude-plugin/marketplace.json` exposes each skill of `skills/` and `vendor/` as a plugin of the `qveys-skills` marketplace. Plugins are installed from GitHub, so changes must be pushed to `master` first:

```bash
claude plugin marketplace add qveys/agent-skills
claude plugin install wsh-cockpit@qveys-skills        # one skill
claude plugin marketplace update qveys-skills         # refresh the marketplace listing
claude plugin update wsh-cockpit@qveys-skills         # update the installed plugin
```

`marketplace update` only refreshes the listing; `plugin update` is what brings a changed skill into an already-installed plugin.

When adding a skill to `skills/` or a source to `sources.yaml`, add a matching entry to `marketplace.json`. Vendored duplicates of a `skills/` copy (`agent-governance`, `ai-ready`) and `security-review` (shadows the built-in command) are intentionally not listed.

### Installing into Claude Code via symlinks

Claude Code loads every directory in `~/.claude/skills/` that contains a `SKILL.md`. Symlinking to this checkout means edits and `skills:sync` updates are picked up without reinstalling:

```bash
mkdir -p ~/.claude/skills

# Proprietary skills (skips _template)
for d in ~/Git/agent-skills/skills/*/; do n=$(basename "$d"); [[ $n == _* || -e ~/.claude/skills/$n ]] || ln -s "${d%/}" ~/.claude/skills/$n; done

# Vendored skills (skips security-review, which would shadow the built-in /security-review)
for f in ~/Git/agent-skills/vendor/*/*/SKILL.md; do d=$(dirname "$f"); n=$(basename "$d"); [[ $n == security-review || -e ~/.claude/skills/$n ]] || ln -s "$d" ~/.claude/skills/$n; done
```

Both loops are idempotent: rerun them after adding a skill or syncing a new source. Existing entries are never overwritten, so on a name collision the `skills/` copy wins (e.g. `agent-governance`, `ai-ready`).

- `security-review` is skipped on purpose: same-named user skills take precedence over bundled Claude Code skills, so the symlink would shadow the built-in `/security-review` command. Remove an existing link with `rm ~/.claude/skills/security-review` to get the built-in back.
- Don't also install the same skill as a plugin from the `qveys-skills` marketplace (`.claude-plugin/marketplace.json`), or it will show up twice.
