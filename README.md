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

Then run `npm run skills:sync -- --id my-awesome-skill` (or `npm run skills:sync` to sync all).

## How to check for updates

```bash
npm run skills:check
```

This will compare the installed SHAs in `sources.lock.yaml` against the latest commits of the defined `ref` in the remote repositories.

## How to synchronize

```bash
npm run skills:sync
```

This command will fetch any missing or updated skills and update `sources.lock.yaml`. It does not execute any code downloaded during the sync process.

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
- **Claude Code / Codex / etc.**: Point the respective configuration or prompt injection to load skills from this unified repository.
