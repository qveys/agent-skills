---
name: wsh-cockpit
description: >-
  Run commands for the user in a VISIBLE Wave Terminal block — local or on a
  Wave-connected host — so they can watch and take the keyboard. Triggers:
  "show me how you'd run this", "do it but let me watch", "open a terminal and
  walk me through it". Also when plain `ssh` to `user@ip`/srvXXXX fails with
  "Permission denied (publickey,password)" — the credentials live in Wave /
  1Password. Announce steps with `banner`/`step-run`, never `echo`; move files
  with `push`/`pull`, never base64 through `send`.
---

# wsh-cockpit

Do terminal work on the user's behalf **in the open**, in a Wave Terminal block
they can see, read, and step into. Read the relevant doc first:

- `docs/session-lifecycle.md` — `spawn`/`start`/`open`/`stop`/`release`, situating
  the shell, adoption and `--keep`, reuse, cleanup timing, `gc` sweep.
- `docs/banners.md` — banner rendering rules, palette, `step-run`.
- `docs/framing-and-transfer.md` — `send` framing, reading a result, file
  transfer, `remote-init`/`local-init`.
- `docs/advanced.md` — audit trail, `open` internals, `doctor`, browser view.
- `docs/gotchas.md` — the pitfalls list, one `##` section each.

## Two modes

- **`rexec`** — one-shot: capture stdout/stderr + exit code. The block lingers
  ~60s for the user to read, but detached — the script returns as soon as the
  command finishes. → `scripts/wsh-rexec.sh`
- **`live`** — a persistent tmux session **on the Mac** you drive and the user
  attaches to; best for interactive co-driving. Needs `brew install tmux`.
  → `scripts/wsh-live.sh`

Default to `rexec`; `live` when the work is interactive.

## Mode 1 — rexec

```bash
scripts/wsh-rexec.sh <local|connection> <command...>
scripts/wsh-rexec.sh local 'sw_vers; ls ~/Git'
scripts/wsh-rexec.sh qveys@187.77.175.117 'docker ps; uname -a'
```

Output: stdout/stderr, then `---- exit code: N ----`. Connection strings via
`wsh conn status`. Quote the command as ONE argument — it runs under the target
shell, so `;`, `&&`, pipes, `$(...)` work. Slow? `WSH_REXEC_TIMEOUT=180`.

## Mode 2 — live

```bash
scripts/wsh-live.sh spawn [prefix] [--force] [--situate] [--pre <host>] [--tab <name>]  # open/continue a cockpit: reuses an alive session by default
scripts/wsh-live.sh start [session] [--reuse]  # create a session (auto-unique if unnamed)
scripts/wsh-live.sh open  [session] [--tab <name>]  # attach a Wave block, optionally on a named tab
scripts/wsh-live.sh send  '<command>' [session]  # type a command + Enter (framed by default)
scripts/wsh-live.sh keys  '<tmux-keys>' [session]  # raw keys: C-c, Up, q, Enter — never framed
scripts/wsh-live.sh read  [session] [lines]  # free-form pane snapshot (default 30) — unframed panes only
scripts/wsh-live.sh output [session] [seq] [--full]  # print send #seq's framed segment exactly — no lines to guess
scripts/wsh-live.sh wait-done [session] [timeout_sec] [--print]  # wait for the exit footer; --print adds bounded output
scripts/wsh-live.sh step-run <id> '<label>' '<command>' [session] [timeout_sec]  # banner + send + wait in ONE call
scripts/wsh-live.sh banner {header|phase|step|done} ... [session]  # airy step banners (required)
scripts/wsh-live.sh stop  [session]  # kill the session (or release it, if it carries a keep marker)
scripts/wsh-live.sh release <session>  # hand a session back; argument mandatory, no default
scripts/wsh-live.sh status [prefix]  # is the last session alive? matching sessions?
scripts/wsh-live.sh current  # print last spawned session for this agent
scripts/wsh-live.sh doctor  # read-only diagnostic of the whole chain, rc 0/1
scripts/wsh-live.sh gc [--dry-run] [--idle=SECONDS] [--only-session=NAME]  # sweep orphaned idle sessions
scripts/wsh-live.sh web {start|stop|status} [session] # browser view via ttyd, read-only by default
scripts/wsh-live.sh push <session> <local> <remote>  # file transfer out; host deduced from remote-init
scripts/wsh-live.sh pull <session> <remote> <local>  # file transfer in
scripts/wsh-live.sh remote-init [session] [host]  # after an ssh hop: push helpers to [host] (sticky inline-only without it)
scripts/wsh-live.sh remote-init --pre <host> [session]  # RECOMMENDED when <host> is known: push helpers BEFORE the hop
scripts/wsh-live.sh remote-init --container <container> [session]  # after `docker exec`: copy helpers into the container, same path
scripts/wsh-live.sh local-init  [session]  # revert remote-init
scripts/wsh-step.sh {header|phase|step|done|cmd|defs} # renderer / one-liner / pane-side fn defs
```

## Règles impératives

- **`spawn`, jamais `start cockpit`** (nom réutilisé par d'autres agents) ; `--force` seulement pour une 2e fenêtre délibérée.
- **Cockpit nommé par l'utilisateur** (ou listé dans `WSH_COCKPIT_ADOPT`) : adopte-le, n'en crée pas une seconde.
- **`--situate` obligatoire juste après `spawn`** ; `--pre <host>` est un plus (pré-push des helpers avant le hop), pas un substitut — une session réutilisée peut être restée en ssh.
- **Bannières obligatoires** pour tout plan multi-étapes, jamais `echo` ni markdown nu.
- **Une seule session SSH persistante** par hôte, pas une rafale de one-shots.
- **Toujours terminer les commandes par `2>&1`** — non négociable.
- **Jamais de `send` avant le footer `exit` du précédent** : `wait-done`, jamais un `sleep` ni du grep sur la sortie.
- **Jamais de base64, `cat` ou heredoc dans `send`** pour transférer un fichier — `push`/`pull`.
- **Lire un résultat avec `output`** (ou `wait-done --print`), pas `read N` ; `read` sert au scrollback libre (TUI, REPL, pane non framé).
- **`release` obligatoire pour une session `--keep`** (marqueur sticky) ; sinon `stop` normal, y compris adoptée sans `--keep`.
- **Chaque sous-agent exporte son propre `WSH_COCKPIT_AGENT`** (jamais `user-preopen-*`/`released`) ; idem `WSH_COCKPIT_PREFIX` entre agents parallèles.
- **Un nom de session est littéral**, jamais un préfixe abrégé.

## Bannières

```bash
COCKPIT=/Users/qveys/.claude/skills/wsh-cockpit/scripts/wsh-live.sh
$COCKPIT banner header "Théo Marceau — OpenClaw" "cockpit-theo-plan-225108"
$COCKPIT banner phase  1 6 "Fondations & isolation"
$COCKPIT banner step   1.1 "openclaw doctor"
$COCKPIT send 'openclaw doctor 2>&1'
$COCKPIT banner done   "Phase 1 terminée"
```

## Hôte distant — une session, pas une rafale

Une seule session ssh interactive (auth FIDO2 une fois), tout le travail dedans,
puis `exit`. Pour un hop OpenSSH, active `ControlMaster` : le pane devient la
connexion maîtresse que `push`/`pull` réutilisent sans ré-auth.

```bash
$COCKPIT send "ssh -o ControlMaster=auto -o ControlPath=~/.cache/wsh-cockpit/cm-$SESS -o ControlPersist=10m <host>" "$SESS"
# hôte joignable seulement en tailscale ssh (pas d'OpenSSH ControlMaster) :
$COCKPIT send 'tailscale ssh <host>' "$SESS"
$COCKPIT push "$SESS" ./local.md /remote/absolute/path.md
$COCKPIT send 'exit' "$SESS"              # retour au Mac en fin de travail
```

Un one-shot `ssh <host> '<cmd> 2>&1'` reste légitime pour un diagnostic ponctuel
(1-2 commandes), jamais comme mode de travail : `send` avertit dès le 2e.

### Transférer des fichiers — **jamais base64/cat dans `send`**

Séparer transfert et exécution. **Quand le pane est en session SSH**, la voie
officielle est `push`/`pull` (l'hôte est déduit de `remote-init`/`--pre` —
jamais à redonner à la main) :

```bash
$COCKPIT push "$SESS" ./local-file.md /remote/absolute/path.md   # local -> remote
$COCKPIT pull "$SESS" /remote/absolute/path.log ./local-copy.log # remote -> local
```

Ordre de transport (choisi automatiquement, annoncé sur stderr) : `wsh file
cp` → le socket `ControlMaster` de la session (zéro ré-auth — voir ci-dessus)
→ `tailscale ssh` → `scp` nu en dernier recours. Ces transports tournent hors
pane depuis le shell agent : ils ne comptent **jamais** pour l'avertissement
one-shot SSH (qui ne surveille que `send`).

Hors session SSH (local → local, ou hôte connu sans passer par une session
cockpit), `scripts/wsh-push.sh` (ou `wsh file cp`) reste utilisable
directement. Détails : `docs/framing-and-transfer.md`.

### Descendre d'une couche — conteneur

Une fois DANS la session SSH, un `docker exec <c> bash`/`docker compose exec
<c> bash` descend encore d'une couche : les helpers de la couche du dessus
(hôte distant, ou ce Mac) ne sont plus atteignables depuis le conteneur — le
`send` suivant continue d'émettre la forme courte `. '<chemin>' && ...` mais
`<chemin>` n'existe pas dans le conteneur (`No such file or directory`,
footer `exit` perdu). Appelle `remote-init --container <container>` juste
après le `docker exec` — **pas de repli inline** ici :

```bash
$COCKPIT send 'docker compose exec paperclip bash' "$SESS"
$COCKPIT remote-init --container paperclip "$SESS"
# ... la forme courte de send/banner marche à nouveau, chemin inchangé ...
```

Copie les mêmes fichiers helper au même chemin absolu déjà enregistré pour la
session — `send`/`banner` n'ont rien à changer. Détail (transport, cas
local/distant) : voir `docs/framing-and-transfer.md`.

## Nettoyage

**Attends au moins 60s** avant de traiter une session idle comme orpheline — elle
peut être en plein run. `stop` et `gc` ferment le bloc Wave avec la session tmux.
