# Gotchas

Pièges opérationnels en mode `live` et `rexec` — ce qui change ce qu'un agent doit
taper. Voir `SKILL.md` pour les règles impératives. Pour le détail archéologique et
le "pourquoi" des gardes (mesures tmux, régressions, historique) : `docs/internals.md`.

## Un nom de session est littéral, jamais un préfixe

Un nom de session doit être exact — `mux_has`/`mux_kill`/`mux_clients`
anchorent leur cible tmux (`-t "=$1"`), donc un préfixe qui matchait avant
par accident ne matche plus rien. Détail et mesures : `docs/internals.md` →
"Anchoring `=` et résolution par préfixe des noms de session".

## `stop`/`gc` refusent ta propre session

`stop <session>` sur ta propre session tape exit 8 (refus net, pas de
"continuer sur le reste") ; `gc` la saute pendant le sweep (comptée `kept`)
plutôt que de la détruire. Détail : `docs/internals.md` → "Garde own-session
sur `gc` et `stop` (implémentation)".

## Ne jamais lancer `selftest-guard` depuis une session qui compte

Il opère directement sur le serveur tmux par défaut (pas un socket isolé) et
groupe temporairement des sessions pendant certains cases — y compris
potentiellement la tienne. Détail : `docs/internals.md` → "`selftest-guard`
opère sur le serveur tmux par défaut".

## Une session laissée en plein ssh n'est pas réutilisable par un `spawn` ordinaire

Une fois hoppée, le foreground du pane n'est plus un shell nu, donc `spawn` ouvre une
nouvelle cockpit (nouvelle auth, second bloc Wave) sauf si la session est listée dans
`WSH_COCKPIT_ADOPT`. Workaround : réutiliser la session explicitement (`SESSION=…`).
Détail : `docs/internals.md`.

## `docker exec` est une couche de plus que les helpers poussés n'atteignent pas

Symptôme : `No such file or directory` sur le fichier helper juste après le hop
conteneur, footer `exit` disparu. Fix : `remote-init --container <container>
[session]` — copie les mêmes fichiers au même chemin absolu, la forme courte de
`send`/`banner` repart sans changement. **Pas de repli inline** (workflow réel,
rejeté explicite — voir `docs/framing-and-transfer.md` → "Descendre d'une couche
de plus"). Best-effort : conteneur injoignable → warning stderr, retour non nul,
jamais de hard fail. Couvert par `selftest-live` cases 14a-14c. Mécanisme et
mesures : `docs/internals.md`.

## `remote-init "$sess"` sans hôte purge maintenant les chemins helpers périmés

La branche sans hôte appelle le même `remote_helper_paths_clear` que `local-init`
avant de poser le flag sticky — plus de chemin helper remote périmé qui traîne.
Couvert par `selftest-live` case 13. Historique du bug : `docs/internals.md`.

## Never start cockpit blindly

Another agent may already own that tmux session. Use `spawn` to open/continue your
cockpit; it reuses an alive session automatically. Only `spawn --force` creates a
duplicate window.

## Never call spawn again mid-workflow to reconnect

If the cockpit tab is still open, run `send`/`read` (or `current` / `status`)
against the existing `SESSION=`. `spawn` without `--force` reuses an alive session,
but a prefix matching nothing in the registry, `WSH_COCKPIT_ADOPT` or the legacy
scan **creates a fresh cockpit** — a second tab, exactly like `--force`. Pourquoi :
`docs/internals.md`.

## Never skip airy step banners on multi-step cockpit work

More than ~2 related commands → `banner` before each logical step and `banner done`
at each phase end. Plain `echo`, markdown headings or chat narration do not replace
in-pane banners — the user is watching the terminal.

## The linger does NOT block the call

`rexec` returns as soon as the command finishes; the visible-then-delete window runs
in a detached background job, so the block can still linger in the user's Wave tab
after your call returned. `WSH_REXEC_LINGER=0` only to have it gone instantly.

## First statement mangled (remote)

Wave types the command into the remote shell and the first statement loses its
argument in that handoff. The `true __warmup__;` prefix + `START` marker absorb it —
leave them in; don't make the first real statement depend on its argument.

## Don't forget cmd:runonce=true on remote

Driving the steps by hand without it runs the command twice (the connection switch
re-runs the controller).

## Exit code unreliable via Wave's own footer

Wave's per-block "exit code" is unreliable (`-1` is normal). Trust the
`---- exit code ----` line (`echo END$?` on target).

## No input injection into an arbitrary block

wsh has no `sendinput`/`type`. `live` works *because* tmux (on the Mac) gives you
`send-keys`; `rexec` bakes the command in up front, so prompting for input won't
work — make it non-interactive (`-y`, here-strings) or use `live`.

## Remote needs an existing Wave connection

Check `wsh conn status`; if the host isn't listed, the user opens it once with
`wsh ssh -n <host>`.

## Never push files via base64 in cockpit send

Use `scripts/wsh-push.sh` (tailscale ssh pipe / `wsh file cp`) from the agent shell,
then verify with a short `send`. Base64 in tmux breaks quotes and length limits.
Reading the other way is `wsh file cat "wsh://<conn>/path"` — this skill is for
*running* something visibly.

## Wait for the gateway before the next command after a restart

A bare restart returns while LaunchAgent is still starting — immediate `infer`,
`agent` or `channels status` calls race a dead socket and fail. **Do not** fire the
next `send` until the restart's footer shows exit 0 *and* the probe is ok. Prefer
**one chained cockpit command** (wait loop inside the pane) over an agent-side
`sleep`:

```bash
$COCKPIT send 'bash ~/wsh-gw-restart.sh 60 2>&1' "$SESS"
```

`openclaw gateway restart --wait 45s` couvre le même cas. Boucle inline complète :
`docs/internals.md`.

## `sudo` ne reçoit pas le TTY à travers le framing de `send`

Symptôme (mesuré 2026-09-16 sur vps-openclaw, via le hop distant) : `send 'sudo
<cmd> 2>&1'` affiche `[sudo] password for <user>:` puis échoue **immédiatement**
(`sudo: a password is required`, footer `exit 1`) — le process a lu EOF et le `keys`
d'appoint arrive après sa mort. `docs/framing-and-transfer.md` décrit l'inverse (un
`sudo` interactif alimentable par `keys`) : les deux ne peuvent pas être vrais
partout, donc traite le cas mesuré comme le tien dès que le pane n'est pas le TTY
qui exécute.

Deux voies propres, jamais de saisie du mot de passe par l'agent :

```bash
# sans framing : tapée brute au prompt, hérite du TTY (pas de footer exit —
# vérifier ensuite par un send cadré)
WSH_LIVE_SEP=0 scripts/wsh-live.sh send 'sudo <cmd>' "$SESS"
# ou la faire taper par l'utilisateur dans le pane
```

Corollaire, **dans ce cas mesuré seulement** : ne pas `wait-done` sur un `sudo` cadré
en croyant qu'il attend une saisie — il a déjà rendu la main ; vérifier avec `read`.
Sous le contrat de framing (un `sudo` interactif alimenté par `keys`), `wait-done`
reste au contraire la bonne attente, puisqu'il ne rend pas la main avant la fin. Pane
dans un shell root (`su`) : **deux** `exit`, un pour root, un pour ssh.

## Toujours terminer la commande `send`/`rexec` par `2>&1`

Non négociable. L'utilisateur **EXIGE de voir le footer `└─[#N] exit <code>`** :
sans `2>&1`, la sortie stderr peut arriver **après** le footer et donner
l'impression qu'il manque. `2>&1` fusionne les deux flux **avant** l'impression du
footer, qui reste donc la dernière ligne. Pourquoi, en détail : `docs/internals.md`.
```bash
$COCKPIT send 'openclaw doctor 2>&1' "$SESS"   # BIEN
$COCKPIT send 'openclaw doctor' "$SESS"        # MAL
```
- **Commande chaînée :** `2>&1` sur l'**ensemble** (`'{ cmd1; cmd2; } 2>&1'`), jamais
  sur la seule dernière sous-commande.
- **Jamais de commande interactive sans footer** : `tailscale ssh host` sans commande
  ouvre un shell interactif. Pour un diagnostic, le one-shot
  `tailscale ssh host '<cmd> 2>&1'`.
- **Ce one-shot sert au diagnostic, pas au travail** : pour du travail réel, une seule
  session SSH persistante (SKILL.md "Hôte distant").

## Never send the next command until the previous one shows exit in the pane

Each framed `send` ends with `└─[#N] exit <code>`. Use `wait-done` before the
next `send` — never an agent-side `sleep`, never a grep on arbitrary output:
```bash
$COCKPIT send 'bash ~/wsh-gw-restart.sh 60 2>&1' cockpit-theo-plan-225108
$COCKPIT wait-done cockpit-theo-plan-225108 120    # blocks until #[N] exit seen
# only if exit 0:
$COCKPIT send 'openclaw infer model run ... 2>&1' cockpit-theo-plan-225108
$COCKPIT wait-done cockpit-theo-plan-225108 180
```
Timeout par défaut 300 s (`WSH_WAIT_TIMEOUT`). `--print` émet le résultat dans le
même appel (borné par les marqueurs `┌─[#N]`/`└─[#N]`) au lieu d'un `read`/
`output` séparé — voir `docs/framing-and-transfer.md` → "Lire un résultat sans
deviner". Mécanique (`@[wsh_seq]`, polling du pane) : `docs/internals.md`.
