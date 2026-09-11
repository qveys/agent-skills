# Cycle de vie d'une session cockpit

## Opening a cockpit — never hijack another agent's session

**Use `spawn` to open or continue a cockpit.** Never bare `start cockpit` — that
name is commonly reused by other agents (Claude, Grok…) and you will land in
their tmux pane.

**`spawn` reuses an alive cockpit by default** — no duplicate Wave block if your
previous session is still running. Without `--force` it walks four resolution
steps, each gated by an atomic claim (mechanics: `docs/internals.md`) :

1. **Registry** — among *my own* sessions (claimed under my
   `WSH_COCKPIT_AGENT`/`WSH_COCKPIT_PREFIX` key), filtered by prefix if one was
   passed → reuse. Several matches with no last-used → refuses (exit 2,
   ambiguous) rather than silently pick one.
2. **Adoption** (`WSH_COCKPIT_ADOPT` only) — claim each listed session in order,
   run the **mandatory** `hostname; pwd; whoami` probe, finalize only if the
   probe succeeds. A failed probe rolls the claim back.
3. **Legacy scan** — an unclaimed `cockpit-<prefix>-*` session found free is
   claimed on the spot (same probe gate) and reused.
4. **Nothing found** → create `cockpit-<prefix>-<HHMMSS>`, claim it, auto-open
   Wave. Auto-open is skipped when clients are already attached, whichever step
   produced the session.

`spawn` prints `SESSION=<name>` — use it (or rely on `send`/`read` defaults) for
the rest of the workflow. Flags:

- **`--force`** — only when you intentionally need a *second* cockpit window.
  Skips steps 1-3, never touches an existing claim of mine. Never call bare
  `spawn` again mid-workflow just to "reconnect".
- **`--situate`** — runs the hostname/pwd/whoami probe internally before
  returning, one call instead of four (see below).
- **`--pre <host>`** — pre-stages the helpers on `<host>` before the pane ever
  ssh-hops there.
- **`--tab <name>`** — relayed to `open`, anchors the Wave block on a named tab
  (`docs/advanced.md` → "Auto-open").

```bash
WSH_COCKPIT_PREFIX=grok scripts/wsh-live.sh spawn theo-plan
# → SESSION=cockpit-grok-theo-plan-224847
WSH_COCKPIT_PREFIX=grok scripts/wsh-live.sh spawn theo-plan
# → reusing existing tmux session 'cockpit-grok-theo-plan-224847' (pas de 225108)
```

Set `WSH_COCKPIT_PREFIX` or `WSH_COCKPIT_AGENT` so parallel agents keep separate
last-session state under `~/.cache/wsh-cockpit/`.

## Situer le shell juste après `spawn` — obligatoire

Un cockpit n'est pas toujours sur le Mac : une session vivante peut avoir été
laissée sur un serveur (ssh persistant, `su -`, `cd` projet), et un `spawn` qui
la réutilise atterrit dans ce contexte sans avertissement. Avant **toute** autre
commande, sache sur quelle machine, dans quel répertoire et sous quelle identité
tu parles — sinon tu pilotes à l'aveugle.

**Hôte déjà connu — pré-push avant le hop (voie recommandée).** `--pre <host>`
pousse les helpers sur `<host>` **avant** le `ssh` du pane, `$HOME` résolu hors
pane. Le premier `send`/`banner` après le hop est donc déjà en forme
courte (~100 caractères), jamais le blob inline :

```bash
COCKPIT=/Users/qveys/.claude/skills/wsh-cockpit/scripts/wsh-live.sh
$COCKPIT spawn theo-plan --pre macbook-openclaw
# → SESSION=cockpit-... puis "pre-push: helpers staged on '...' — remote mode ON"
$COCKPIT send 'tailscale ssh macbook-openclaw' "$SESS"   # le hop, sans footer/wait-done
$COCKPIT send 'hostname 2>&1' "$SESS"   # sonde avec footer : wait-done s'applique ici
$COCKPIT wait-done "$SESS" 60
$COCKPIT send 'docker ps 2>&1' "$SESS"  # déjà en forme courte
```

Sur une session déjà spawnée : `$COCKPIT remote-init --pre <host> "$SESS"`, puis
le `send` du hop.

**Hôte inconnu d'avance — `spawn --situate`.** La sonde tourne en interne ; si le
hostname diffère du Mac, `situate` appelle lui-même `remote-init` en best-effort
(push si joignable, sinon repli inline avec warning stderr — jamais de
hard-fail).

**Re-situer plus tard dans le workflow** (séquence manuelle équivalente) :

```bash
$COCKPIT send 'hostname; pwd; whoami 2>&1' "$SESS"; $COCKPIT wait-done "$SESS" 60
$COCKPIT read "$SESS" 20   # → srv1453980 / /docker/paperclip / root  (ou le Mac)
```

Adapte la suite : shell **local** → `tailscale ssh` pour atteindre le serveur ;
shell **déjà sur le serveur** → commandes en direct, sans re-ssh. Ne présume
jamais « je suis sur le Mac ». Si l'hôte diffère de l'attendu et que rien n'a
poussé les helpers, appelle `remote-init "$SESS" [host]` **avant tout autre**
`send`/`banner` — voir `docs/framing-and-transfer.md`.

## Cockpit pré-ouvert par l'utilisateur — adoption, `--keep`

Le wrapper `claude-cockpit` (`scripts/claude-cockpit.sh`, symlinké sur le
`$PATH`) permet à l'utilisateur de pré-ouvrir des cockpits avant de lancer
l'agent : `claude-cockpit theo-plan --keep --and deploy -- <args claude>` crée un
cockpit par groupe `--and`, pose `WSH_COCKPIT_ADOPT=<sessions>` (liste ordonnée)
et `WSH_COCKPIT_AGENT=claude-<epoch>-<pid>` dans l'environnement de l'agent.

- **Sonde obligatoire.** Aucune adoption n'est finalisée sans `hostname; pwd;
  whoami` réussi ; son résultat s'affiche. Échec de sonde → claim restauré.
- **Adoption ciblée.** Un préfixe explicite qui ne correspond à **aucune**
  session adoptable **crée un cockpit neuf** — jamais d'adoption forcée. Seul un
  `spawn` **sans préfixe** adopte en nominal (première session de la liste).
- **`--keep` est une propriété de la SESSION, pas du claim.** Le marqueur survit
  à toute adoption/relâche ultérieure. Conséquence : **`release`, jamais `stop`**
  sur une session `keep` — `stop` se rabat d'ailleurs automatiquement sur
  `release` quand le marqueur est là. Une session adoptée **sans** `keep` suit le
  chemin normal et peut être `stop`ée.
- **Balayage de sortie du wrapper.** Au retour de `claude`, toute session encore
  vivante de ce run est relâchée si elle porte `keep`, détruite sinon. C'est le
  filet, pas le chemin nominal : `release`/`stop` proprement en fin de tâche.
- **Sous-agents.** Chacun exporte son propre `WSH_COCKPIT_AGENT` — jamais
  l'espace réservé `user-preopen-*`/`released`, que `spawn` refuse.
- **Hygiène `gc`.** Plancher d'idle 24 h pour une `keep` abandonnée : voir la
  section `gc` ci-dessous. `gc` nettoie aussi les familles de marqueurs
  orphelins (`keep-`, `prefix-`, `adopt-claim-`, `.won-<pid>`…) dont la session
  est morte — jamais une session vivante.

## Reusing a named session

```bash
scripts/wsh-live.sh start cockpit --reuse   # only when continuing YOUR session
```

- `spawn` is the default entry point — first call creates + opens, later calls
  reuse.
- `start` without a name auto-generates a unique session. With an explicit name
  it **refuses to reuse** unless you pass `--reuse`.
- `open` attaches a Wave block to an existing session; it self-heals a stale Wave
  env and falls back to printing the manual `tmux attach` line
  (`docs/advanced.md` → "Auto-open").
- `send` / `keys` / reading a result : voir `docs/framing-and-transfer.md`.
- Pour co-piloter un **hôte distant**, ouvre-le *dans* la session
  (`send 'ssh host'`) — tmux reste sur le Mac, le shell distant vit dedans.

La session survit aux appels et au détachement (Ctrl-b d) — c'est ce qui en fait
un espace partagé. **`stop` (et `gc`) ferment le bloc Wave automatiquement** :
l'id est mémorisé sous `~/.cache/wsh-cockpit/block-<session>` et `teardown_session`
le supprime en best-effort. Rien à faire à la main.

## Cleaning up — but not too fast

**Attends au moins 60s avant de balayer un bloc que tu crois orphelin.** Un bloc
qui semble abandonné peut être un `rexec` en plein run ou en plein linger — le
supprimer tôt ferme un terminal en cours d'usage.

```bash
wsh blocks list                 # find strays (note which look idle ≥60s)
wsh deleteblock -b <block-id>   # remove each confirmed orphan
```

Ne supprime que les blocs/sessions **que tu as créés ou adoptés sans `--keep`**.
Laisse les panes de l'utilisateur tranquilles ; dans le doute, laisse. Cette
section de balayage heuristique ne concerne que les traînards `rexec`, qui n'ont
pas de fichier d'état : en mode `live`, `stop`/`gc` suffisent.

## `gc` — sweep automatique des sessions orphelines

Une session `live` n'est normalement supprimée que par un `stop` explicite — si
cet appel n'a jamais lieu (crash, cockpit oublié), la session fuit. `gc` détruit
toute session `cockpit-*` restée **idle** au-delà du seuil **et** sans client
attaché, via le même `teardown_session()` que `stop`.

```bash
scripts/wsh-live.sh gc                          # sweep réel, seuil par défaut 24h
scripts/wsh-live.sh gc --dry-run                # liste ce qui SERAIT tué
scripts/wsh-live.sh gc --idle=3600              # seuil personnalisé (secondes)
scripts/wsh-live.sh gc --only-session=cockpit-x  # restreint à une session
```

- `--idle=SECONDS` surcharge `WSH_LIVE_GC_IDLE` (défaut `86400` = 24 h).
- Une session **attachée** n'est jamais tuée, même au-delà du seuil.
- Une session **`keep`** a un plancher d'idle de 24 h (`GC_KEEP_FLOOR_IDLE`)
  même avec un `--idle` plus court — passé ce plancher elle retombe dans le
  balayage normal : une `keep` détachée et oubliée finit par disparaître.
