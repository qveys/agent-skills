# Audit trail, backend Zellij, diagnostic et vue navigateur

## Audit trail

**`live` mode only.** Every tmux session auto-logs everything displayed in the pane
to `~/Library/Logs/wsh-cockpit/<session-slug>.log` (sanitized slug of session name).
Logs are **retained for 30 days** then auto-purged. Disable logging with
`WSH_LIVE_LOG=0`; customize directory with `WSH_LIVE_LOG_DIR=/path`. **⚠️ Audit
logs contain everything displayed — treat them as sensitive** (directory `chmod 700`,
files `chmod 600`). Delete manually with
`rm ~/Library/Logs/wsh-cockpit/<session-slug>.log`.

## Backend Zellij (expérimental)

`WSH_MUX=zellij scripts/wsh-live.sh …` : `spawn/start/send/read/wait-done/stop/status/open`, Wave → `zellij attach`.
Commandes également disponibles : `banner`, `step-run`, `output`, `push`, `pull`, `remote-init`, `local-init`, `doctor`.

- `remote-init` / `local-init` : ne persistent pas le mode distant sticky (Zellij n'a pas de store d'options par session ; passer par `WSH_LIVE_SEP_REINIT=1` / `WSH_STEP_INLINE=1`).
- `gc` : exécute l'hygiène des marqueurs, saute le balayage des sessions idle (spécifique tmux) et retourne 0.
- Refusé (code 13) : `keys` (touches tmux), `web` (ttyd = lecture seule ; Zellij a `zellij web`).
- Audit tmux-only : non journalisé, `UNLOGGED` sur stderr.
- Ne pas réduire wait-done (rendu headless paresseux).
- Détails : `docs/internals.md`.

## Auto-open (`live open`)

`open` gère les cas particuliers de Wave (stale `WAVETERM_TABID`, lecture WAL `?mode=ro`
de l'onglet actif, chemin absolu `tmux`, vérification d'attache avec repli manuel).
Appeler simplement `scripts/wsh-live.sh open <session>`.

**Le bloc s'ouvre sur l'onglet du shell INITIATEUR** (où tourne le Claude Code
émetteur), pas sur l'onglet « actif » DB : signaux vivants privilégiés — nom tmux
`wave-<tab8>`, puis onglet contenant `WAVETERM_BLOCKID`.

Si `open` signale l'onglet (ex. «T4», quand >1 onglet existe), **communique ce nom
à l'utilisateur** — ne pas se contenter d'un « c'est ouvert ».

## `doctor` — diagnostiquer le cockpit

`scripts/wsh-live.sh doctor` déroule une série de checks read-only (tmux, serveur, sessions
`cockpit-*` vivantes, `wsh`/`sqlite3`, DB Wave/tab actif, state dir, helpers,
logs d'audit, extras `ttyd`/`zellij`) et n'écrit jamais rien — sûr à lancer
n'importe quand, même sans session. Utilise-le quand `open` échoue, qu'une
session semble invisible côté utilisateur, ou que l'état parait périmé. Sortie
une ligne par check (`ok|warn|fail — libellé — détail`), rc 0 si tout est `ok`/
`warn`, rc 1 si au moins un `fail`.

## Cockpit dans le navigateur (`web`)

`scripts/wsh-live.sh web {start|stop|status} [session]` expose le pane d'une
session cockpit dans un navigateur via [`ttyd`](https://github.com/tsl0922/ttyd)
(`brew install ttyd`), pour un utilisateur qui préfère un onglet web à un
`tmux attach`.

```bash
scripts/wsh-live.sh web start cockpit-theo-plan-225108
# web view started: http://127.0.0.1:7681 (pid 84403, session '...')
# mode: read-only (default) — set WSH_WEB_WRITE=1 for a writable view
# loopback only ; from the tailnet: tailscale serve --bg 7681 (never 'funnel' — see below)

scripts/wsh-live.sh web status cockpit-theo-plan-225108   # running/stopped + URL
scripts/wsh-live.sh web stop   cockpit-theo-plan-225108   # kill + supprime le pidfile
```

- **Lecture seule par défaut.** `ttyd` tourne sans `-W` et tmux en `attach -r`
  (lecture seule). `WSH_WEB_WRITE=1 scripts/wsh-live.sh web start <session>`
  active l'écriture (`-W` et sans `-r`) pour piloter depuis le web.
- **Port** : `WSH_WEB_PORT` (défaut `7681`).
- **Sécurité — bind loopback strict.** `ttyd` écoute sur `127.0.0.1` (traiter comme
  sensible). Accès distant via **uniquement** `tailscale serve --bg <port>` (arrêt :
  `tailscale serve reset`) — **jamais `tailscale funnel`** (internet public).
- `web start` est idempotent (message + rc 0 si déjà lancé) et vérifie la réponse
  (`curl` sur le port → `200`, jusqu'à 3s ; sinon rc 1 et nettoyage du pidfile).
- `doctor` signale la présence/absence de `ttyd` (extra optionnel, requis
  uniquement par `web`).
