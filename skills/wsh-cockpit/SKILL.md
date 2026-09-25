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

Run commands **in the open**, in a Wave Terminal block the user can read and
control. Relevant docs:

- `docs/session-lifecycle.md` — spawn/start/open/stop/release, situating, adoption, `gc`.
- `docs/banners.md` — banner rendering rules, palette, `step-run`.
- `docs/framing-and-transfer.md` — `send` framing, reading a result, transfers, `remote-init`.
- `docs/advanced.md` — audit trail, `open` internals, `doctor`, browser view.
- `docs/gotchas.md` — the pitfalls list, one `##` section each.

## Two modes

- **`rexec`** — one-shot: stdout/stderr + exit code; the block lingers ~60s for
  the user, detached. → `scripts/wsh-rexec.sh`
- **`live`** — persistent tmux session **on the Mac** you drive, the user attaches;
  best for co-driving. Needs `brew install tmux`. → `scripts/wsh-live.sh`

Default: `rexec`; interactive: `live`.

## Mode 1 — rexec

```bash
scripts/wsh-rexec.sh <local|connection> <command...>
scripts/wsh-rexec.sh local 'sw_vers; ls ~/Git'
```

Output: stdout/stderr, then `---- exit code: N ----`. Connection strings via
`wsh conn status`. Quote the command as ONE argument — it runs under the target
shell, so `;`, `&&`, pipes, `$(...)` work. Slow? `WSH_REXEC_TIMEOUT=180`.

## Mode 2 — live

```bash
L=scripts/wsh-live.sh  # all subcommands below
$L spawn [prefix] [--force] [--situate] [--pre <host>] [--tab <name>]  # reuses an alive session, not one left in ssh
$L start [session] [--reuse]      # create (auto-unique if unnamed)
$L open [session] [--tab <name>]  # attach a Wave block
$L send '<command>' [session]     # type + Enter (framed)
$L keys '<tmux-keys>' [session]   # raw keys: C-c, Up, q, Enter
$L read [session] [lines]         # pane snapshot (unframed)
$L output [session] [seq] [--full]  # send #seq's framed segment
$L wait-done [session] [timeout_sec] [--print]  # wait for the exit footer
$L step-run <id> '<label>' '<command>' [session] [timeout_sec]  # banner + send + wait
$L banner {header|phase|step|done} ... [session]  # airy step banners
$L stop [session]                 # kill, or release with a keep marker
$L release <session>              # hand a session back (arg mandatory)
$L status [prefix] | current | doctor | gc [--dry-run] [--idle=SECONDS] [--only-session=NAME]
$L web {start|stop|status} [session]  # browser view via ttyd (read-only)
$L push <session> <local> <remote> | pull <session> <remote> <local>  # host deduced from remote-init
$L remote-init [session] [host]   # after an ssh hop (sticky inline-only without host)
$L remote-init --pre <host> [session]  # RECOMMENDED when host is known: before the hop
$L remote-init --container <container> [session]  # after `docker exec`: same path, one layer down
$L local-init [session]           # revert remote-init
scripts/wsh-step.sh {header|phase|step|done|cmd|defs}  # renderer / one-liner / pane fn defs
```

## Règles impératives

- **`spawn`, jamais `start cockpit`** (nom réutilisé par d'autres agents) ; `--force` seulement pour une 2e fenêtre délibérée.
- **Cockpit nommé par l'utilisateur** (`WSH_COCKPIT_ADOPT` inclus) : adopte-le, n'en crée pas une seconde.
- **`--situate` obligatoire juste après `spawn`** ; `--pre <host>` est un plus (pré-push des helpers avant le hop), pas un substitut — une session réutilisée peut être restée en ssh.
- **Bannières obligatoires** pour tout plan multi-étapes, jamais `echo` ni markdown nu.
- **Une seule session SSH persistante** par hôte, pas une rafale de one-shots.
- **Toujours terminer les commandes par `2>&1`** — non négociable.
- **Helper absent : réinstaller immédiatement ; inline en dernier recours.** Voir `docs/framing-and-transfer.md`.
- **Jamais de `send` avant le footer `exit` du précédent** : `wait-done`, jamais un `sleep` ni du grep sur la sortie.
- **Jamais de base64, `cat` ou heredoc dans `send`** pour transférer un fichier — `push`/`pull`.
- **Lire un résultat avec `output`** (ou `wait-done --print`), pas `read N` ; `read` sert au scrollback libre (TUI, REPL, pane non framé).
- **`release` obligatoire pour une session `--keep`** (marqueur sticky) ; sinon `stop` normal, y compris adoptée sans `--keep`.
- **Chaque sous-agent exporte son propre `WSH_COCKPIT_AGENT`** (jamais `user-preopen-*`/`released`) ; idem `WSH_COCKPIT_PREFIX` entre agents parallèles.
- **Un nom de session est littéral**, jamais un préfixe abrégé.

## Bannières

```bash
COCKPIT="<base directory of this skill>/scripts/wsh-live.sh"
$COCKPIT banner header "Théo Marceau — OpenClaw" "cockpit-theo-plan-225108"
$COCKPIT banner phase 1 6 "Fondations & isolation"
$COCKPIT step-run 1.1 "openclaw doctor" 'openclaw doctor'
$COCKPIT banner done "Phase 1 terminée"
```

## Hôte distant — une session, pas une rafale

Une seule session ssh interactive (auth FIDO2 une fois), tout le travail dedans,
puis `exit`. Pour un hop OpenSSH, active `ControlMaster` — le pane devient la
connexion maîtresse que `push`/`pull` réutilisent sans ré-auth. Un one-shot
`ssh <host> '<cmd> 2>&1'` reste légitime pour un diagnostic ponctuel (1-2
commandes), jamais comme mode de travail : `send` avertit dès le 2e.

Commandes, variante `tailscale ssh`, et recette `ControlMaster` complète :
`docs/framing-and-transfer.md`.

### Transférer des fichiers — **jamais base64/cat dans `send`**

Séparer transfert et exécution. **Pane en session SSH** : la voie officielle est
`push`/`pull`, l'hôte étant déduit de `remote-init`/`--pre` — jamais à redonner :

```bash
$COCKPIT push "$SESS" ./local-file.md /remote/absolute/path.md   # local -> remote
$COCKPIT pull "$SESS" /remote/absolute/path.log ./local-copy.log # remote -> local
```

Hors session SSH, `scripts/wsh-push.sh` (ou `wsh file cp`) reste utilisable
directement. Ordre de transport, repli et rationale : `docs/framing-and-transfer.md`.

### Descendre d'une couche — conteneur

Un `docker exec <c> bash` dans une session déjà hoppée est une couche de plus : le
helper poussé au-dessus n'atteint pas le conteneur (`No such file or directory`,
footer perdu). `remote-init --container <container>` juste après le hop — **pas de
repli inline** :

```bash
$COCKPIT send 'docker compose exec paperclip bash' "$SESS"
$COCKPIT remote-init --container paperclip "$SESS"
```

`paperclip` est le **nom du conteneur**. Si le service Compose porte un autre nom,
résous-le **par le service** et exige **un seul** conteneur — jamais
`docker ps --filter name=` (filtre sous-chaîne). Recette et transport :
`docs/framing-and-transfer.md`.

## Nettoyage

**Attends au moins 60s** avant de traiter une session idle comme orpheline — elle
peut être en plein run. `stop` et `gc` ferment le bloc Wave avec la session tmux.
