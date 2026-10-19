---
name: vps-dokploy
description: >-
  Operate the vps-dokploy production server — Dokploy itself (compose apps, file
  mounts, deploy webhooks, its Postgres state) and the Housekeeper stack it
  hosts (webhooks, model router, runner, review pipeline). Use whenever the user
  mentions vps-dokploy, Dokploy, a `myhousekeeper-compose-*` / production
  container, "en production" on that host, or asks to deploy, trigger, inspect
  or reproduce anything running there. Paperclip lives on vps-openclaw
  (`paperclip-vps`); OmniRoute specifics are in `omniroute-ops`.
user-invocable: true
---

# vps-dokploy — direct routes (validated 2026-10-02)

## Access
- Connect with `tailscale ssh qveys@vps-dokploy` — works non-interactively.
- Host: `srv766743`, Ubuntu 26.04, tailnet `100.100.10.50`. Docker is usable by
  `qveys` (`docker ps/logs/exec` need no sudo).
- Plain `ssh dokploy` / `ssh vps-dokploy` uses the SSH config `Host vps-dokploy`
  (port 234, key `~/.ssh/id_ed25519_sk_mac`), a **security key**: from an
  agent/non-interactive shell it fails `Permission denied (publickey)`. Use
  `tailscale ssh`.
- `/etc/dokploy/...` is root-owned. To write there, go through a root container
  (`docker run --rm -v <dir>:/cfg alpine sh -c '…'`) rather than sudo.
- `git` in `/etc/dokploy/...` reports *dubious ownership* and
  `/etc/gitconfig: Permission denied` for `qveys`: prefix with
  `GIT_CONFIG_NOSYSTEM=1 git -C <dir> -c safe.directory=<dir> …`.

## What runs here
Dokploy (`dokploy/dokploy:v0.30.8`, UI/API on `0.0.0.0:3000`, plus
`dokploy-postgres` and `dokploy-redis`) manages most stacks:
`myhousekeeper-compose-*` (Housekeeper), `myhermesagent-*`, `omniroute-*`,
`myopencode-server-*`, `hermes-webui`, `hermes-agent`, `hermes-voice-bridge`,
`imap-bridge`, `blinko-*`, `rustdesk-*`, `gitea-runner-vps-dokploy`,
`docker-events-log`. **Do not assume a container name** — resolve it once and
reuse the variable (`docker ps --format '{{.Names}}' | grep -E '<appName>.*-<svc>-1'`).

## Dokploy internals (Postgres)
```
PG=$(docker ps --format '{{.Names}}' | grep dokploy-postgres)
docker exec "$PG" psql -U dokploy -d dokploy -c "select …"
```
- Columns are **camelCase, quoted**: `"composeId"`, `"appName"`, `"branch"`,
  `"autoDeploy"`, `"refreshToken"`, `"filePath"`. Unquoted → *column does not
  exist*.
- `compose` = deployed compose apps (`appName`, `repository`, `owner`, `branch`,
  `composePath`, `refreshToken`, `env`, `autoDeploy`); `application` =
  single-container apps; `deployment` = deploy history (title = pushed commit
  subject, `status`, `createdAt`); `mount` = **file mounts** (below).
- Per app: `/etc/dokploy/compose/<appName>/code` (git clone of
  `repository`@`branch`) and `.../files/` (materialized mounts; the compose's
  relative paths resolve against it). Compose project name = `appName`.

### ⚠️ File mounts (the #1 trap)
A mount is `type='file'`, `filePath='./housekeeper/model-router.yaml'`,
`content` = the whole file. Dokploy **writes `content` into
`<composeDir>/files/<filePath>` on every deploy**.
- **The UI shows `mount.content`**, not the disk file.
- **Editing the disk file is ephemeral** (overwritten at the next deploy) and
  invisible in the UI — it only "works" for the running container because the
  app bind-mounts it and read hot-reloads (the router reloads on `mtime`). It
  silently regresses at the next deploy.
- Durable change: edit the mount in the Dokploy UI, or
  ```
  docker exec "$PG" psql -U dokploy -d dokploy -c \
   "update mount set content = replace(content,'OLD','NEW')
     where \"composeId\"='<id>' and \"filePath\"='./housekeeper/model-router.yaml';"
  ```
  then refresh the UI, and align the disk copy
  (`docker run --rm -v <files/dir>:/cfg alpine sh -c '… > /cfg/<file>'`) so disk
  and base agree before the next deploy.

### Deploy webhook (when autoDeploy doesn't fire)
```
T=$(docker exec "$PG" psql -U dokploy -d dokploy -At -c \
    "select \"refreshToken\" from compose where \"appName\"='myhousekeeper-compose-s2q5xe';")
curl -s -X POST "http://127.0.0.1:3000/api/deploy/compose/$T" \
  -H 'content-type: application/json' -H 'x-github-event: push' \
  -d '{"ref":"refs/heads/main","after":"<sha>"}'
```
- The `x-github-event: push` header is **required**: without it →
  `301 {"message":"Branch Not Match"}`; with it → `200 {"message":"Compose
  deployed successfully"}`.
- `autoDeploy=true` normally fires this on a push to `branch`; observed not
  firing for a bot squash-merge (2026-10-02) — call it yourself then.
- A deploy = git pull + `docker compose build` + `up -d`; follow
  `deployment.status` and `/healthz`. `refreshToken` is a deploy capability —
  treat it as a secret.

## Housekeeper production stack
- `appName` `myhousekeeper-compose-s2q5xe`. Resolve containers live:
  `APP=$(docker ps --format '{{.Names}}' | grep -E 'myhousekeeper-compose.*-housekeeper-1' | head -1)`;
  peers `…-postgres-1` (user/db `housekeeper`/`housekeeper`), `…-redis-1`,
  `…-docker-socket-proxy-1`, plus ephemeral `hk-*` runners from
  `housekeeper-runner:latest`.
- Health: `docker exec "$APP" node -e 'fetch("http://127.0.0.1:3000/healthz").then(r=>r.text()).then(console.log)'`
  → `{"ok":true,"checks":{…}}`; public `https://housekeeper.quentinveys.be/healthz`.
- Logs: `docker logs "$APP"` — one line per cycle step (`job start`,
  `pr-review context collected`, `model_router_decided`, `runner checkout`,
  `docker run start/stop`, `runner verdict`, `job complete`). Grep by
  `handlerId=`, `repo=`, `pr=`, `deliveryId=`.
- **Ground truth for "did a review publish"** is Postgres, not the logs — a
  `review_runs` row exists only on a real persistence:
  ```
  docker exec <pg> psql -U housekeeper -d housekeeper -c \
   "select r.name,pr.number,left(rr.head_sha,7),rr.created_at
      from review_runs rr
      join pull_requests pr on pr.id=rr.pull_request_id
      join repositories r on r.id=pr.repository_id
     order by rr.created_at desc limit 10;"
  ```
- Baked images: `housekeeper:latest` (app) and `housekeeper-runner:latest`
  (agentic runner). The runner image is what carries `docker/opencode.json`; a
  change to it needs a Dokploy rebuild that includes `runner-image`.

### Model router (why `/pr-review` picks a model)
- `model-router.yaml.models.allow` is a **strict whitelist** (`catalog_mode=allow`):
  an id absent from it can never be selected, even if priced.
- The runner serves a provider only if it is declared in `docker/opencode.json`
  **and** keyed in `auth.json` (`files/opencode-data/auth.json`, 0600) **and**
  carries an explicit `options.baseURL` (else `docker/hk-provider-proxy.mjs`
  skips the key). A router pick from an unserved provider fails (MYH-500) or
  falls back to `OPENCODE_FALLBACK_MODEL`.
- `OPENROUTER_API_KEY` (the Jev key, in the compose `.env`) is now injected into
  the runner's provider auth by the app — do not duplicate it in `auth.json`.

### Manual webhook trigger (reproduce a delivery without GitHub)
Sign a payload with the repo's `GITHUB_WEBHOOK_SECRET` (compose `.env`) and POST
to the app's loopback port:
```
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"
curl -s -X POST http://127.0.0.1:3003/webhooks/github \
  -H 'content-type: application/json' -H "x-hub-signature-256: $SIG" \
  -H 'x-github-event: pull_request' -H "x-github-delivery: <uuid>" --data "$BODY"
```
Minimal `pull_request` body: `{"action":"synchronize","installation":{"id":…},
"repository":{"name":…,"owner":{"login":…}},"pull_request":{"number":…,
"draft":false,"head":{"sha":…},"base":{"ref":"main"}}}`. `pr-review` debounces
60 s then runs. A synthetic event exercises ingress → queue → runner, but it is
not a GitHub delivery (no redelivery/monitor, no retargeting guarantees).

### Inspecting a live runner
Runner containers are ephemeral. While one is up (`docker ps | grep hk-`),
`docker exec` into it; the OpenCode server listens on `127.0.0.1:4096` and its
password is `HK_OPENCODE_PASSWORD` in the driver process env
(`/proc/$(pgrep -f hk-opencode-driver)/environ`). `/session/<id>/message` shows
whether the model is actually answering (parts, tool calls) or stuck.

## Gotchas (all hit 2026-10-02)
- **Never print secrets.** A broad `grep`/`sed` over `.env` leaked
  `OPENROUTER_API_KEY` into the transcript; extract names, or use values
  in-place without echoing.
- `ALLOWED_REPOS` is a quoted multi-line value — a single grep line is partial.
- A Dokploy file-mount edit on disk is invisible in the UI and non-durable;
  always fix `mount.content` and align the disk copy.
- Don't prune images around a compose whose tag you cannot rebuild.
- For a visible walkthrough, run host commands through `wsh-cockpit`.

## Keeping this skill current
This file is the memory of that host: after a `/learn` run (or any session) that
discovers or invalidates an operational route here, land the change as a PR to
`skills/vps-dokploy/SKILL.md` — validated commands, and the gotcha that cost the
time.

## Validated
2026-10-02: repaired `/pr-review` end to end — wired the OpenRouter provider
from `.env` (`my-housekeeper` PR #510, merged `82e7dd34`), Dokploy rebuilt app +
runner, and a real review completed: webhook → allowlist → debounce → queue →
context → router → runner → OpenCode → OpenRouter → parse/filter → inline
comment + master section + GitHub review → `review_runs` persistence. The
router allow-list fix had to be applied to the Dokploy `mount.content`, not the
disk file.
