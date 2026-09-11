# Gotchas

Pièges opérationnels en mode `live` et `rexec` — ce qui change ce qu'un
agent doit taper. Voir `SKILL.md` pour les règles impératives (celles-là ne
se discutent pas). Pour le détail archéologique et le "pourquoi" des gardes
(mesures tmux, régressions, historique), voir `docs/internals.md`.

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

Une fois hoppée, le foreground du pane n'est plus un shell nu, donc `spawn`
ouvre une nouvelle cockpit (nouvelle auth, second bloc Wave) sauf si la
session est explicitement listée dans `WSH_COCKPIT_ADOPT`. Workaround :
réutiliser la session explicitement (`SESSION=…`). Détail :
`docs/internals.md` → "Adoption d'une session laissée mid-ssh
(`WSH_COCKPIT_ADOPT`)".

## Never start cockpit blindly

Another agent may already own that tmux session. Use `spawn` to open/continue
your cockpit; it reuses an alive session automatically. Only `spawn --force`
creates a duplicate window.

## Never call spawn again mid-workflow to reconnect

If the cockpit tab is still open, run `send`/`read` (or `current` / `status`)
against the existing `SESSION=`. Calling `spawn` without `--force` **usually**
reuses it — but this is no longer an unconditional guarantee since the
registry/adoption lot (fiches 1.2-1.9, `docs/session-lifecycle.md` → "Opening
a cockpit", steps 1-4): a `spawn` with an explicit **prefix that doesn't
match** anything in my registry, `WSH_COCKPIT_ADOPT`, or the legacy scan
**creates a fresh cockpit instead** — a mismatched prefix mid-workflow is a
second tab the user did not ask for, exactly like `--force`, just spelled
differently. Calling it with `--force` always opens a second tab regardless
of prefix.

## Never skip airy step banners on multi-step cockpit work

If you're running more than ~2 related commands, use `banner` before each
logical step and `banner done` at each phase end. Plain `echo`, markdown
headings, or chat-only narration do not replace in-pane banners — the user
is watching the terminal.

## The linger does NOT block the call

`rexec` returns as soon as the command finishes; the visible-then-delete
window runs in a detached background job, so the block can still be
lingering in the user's Wave tab after your call has returned. Set
`WSH_REXEC_LINGER=0` only when you want the block gone instantly.

## First statement mangled (remote)

Wave types the command into the remote shell, and the first statement loses
its argument in that handoff. The `true __warmup__;` prefix + `START` marker
absorb it — don't remove them, and don't make the first real statement
something that errors without its argument.

## Don't forget cmd:runonce=true on remote

If you ever drive the steps by hand — without it the command runs twice (the
connection switch restarts the controller, which re-runs).

## Exit code unreliable via Wave's own footer

Wave's own per-block "exit code" is unreliable (`-1` is normal). Trust the
`---- exit code ----` line, which comes from `echo END$?` on target.

## No input injection into an arbitrary block

wsh has no `sendinput`/`type`. `live` mode works precisely *because* tmux (on
the Mac) gives you `send-keys`; `rexec` bakes the whole command in up front. A
`rexec` command that prompts for input won't work — make it non-interactive
(`-y`, here-strings) or use `live`.

## Remote needs an existing Wave connection

Check `wsh conn status`; if the host isn't listed, the user opens it once
with `wsh ssh -n <host>`.

## Reading a remote file

Better done directly: `wsh file cat "wsh://<conn>/path"`. Use this skill when
you need to *run* something visibly.

## Never push files via base64 in cockpit send

Use `scripts/wsh-push.sh` (tailscale ssh pipe / `wsh file cp`) from the agent
shell, then verify with a short `send` in the cockpit. Base64 in tmux breaks
quotes and length limits.

## Wait for the gateway before the next command after a restart

A bare restart returns while LaunchAgent is still
starting — immediate `infer`, `agent`, or `channels status` calls race a dead
socket and fail. **Do not** fire the next `send` until the restart command's
footer shows exit 0 *and* probe is ok. Prefer **one chained cockpit command**
(wait loop inside the pane) instead of relying on agent-side `sleep`:
```bash
# Option A — helper on remote (deploy via wsh-push.sh):
$COCKPIT send 'bash ~/wsh-gw-restart.sh 60 2>&1' cockpit-theo-plan-225108
# Option B — inline wait loop in a single send:
$COCKPIT send 'openclaw gateway restart; EL=0; while [ $EL -lt 60 ]; do sleep 3; EL=$((EL+3)); openclaw gateway status 2>&1 | grep -q "Connectivity probe: ok" && echo READY:$EL && break; echo waiting:$EL; done; openclaw gateway status 2>&1 | head -12'
```
Only after `Connectivity probe: ok` → send the next step (`infer`, `agent`,
etc.). OpenClaw also supports `openclaw gateway restart --wait 45s` when run
as one command.

## Toujours terminer la commande `send`/`rexec` par `2>&1`

Non négociable. L'utilisateur **EXIGE de voir le footer `└─[#N] exit <code>`
de chaque process**. Si une commande écrit sur **stderr** (erreur, warning,
log de progression) et que tu n'as pas redirigé stderr, cette sortie peut
arriver **après** le footer (ou hors de la fenêtre de `read`), ce qui donne
l'impression que « les commentaires de fin d'exécution » manquent. En
collant `2>&1` à la fin de la commande, stdout et stderr fusionnent dans le
pane **avant** que le footer ne s'imprime — le footer reste donc bien la
**dernière ligne**, fidèle et complète.
```bash
# BIEN — stderr fusionné, footer fiable :
$COCKPIT send 'openclaw doctor 2>&1' "$SESS"
$COCKPIT send 'tailscale ssh macbook-openclaw "ls -l ~/.openclaw 2>&1"' "$SESS"

# MAL — stderr s'échappe, footer paraît manquant / incohérent :
$COCKPIT send 'openclaw doctor' "$SESS"
```
- **Commande chaînée :** mettre `2>&1` sur l'**ensemble** : `'{ cmd1; cmd2; } 2>&1'`
  ou regrouper en sous-shell `'( cmd1 && cmd2 ) 2>&1'`. Ne pas se contenter d'un
  `2>&1` sur la dernière sous-commande.
- **Jamais de commande interactive sans footer.** `tailscale ssh host` (sans
  commande) ouvre un **shell interactif** : il ne rend jamais la main, donc le
  footer `exit` n'apparaît qu'à la déconnexion. Pour un diagnostic, préférer un
  **one-shot** `tailscale ssh host '<cmd> 2>&1'` qui retourne et imprime le footer.
- **Ce one-shot est pour un diagnostic ponctuel, pas pour travailler.** Pour du
  travail réel sur un hôte, ouvre une session SSH persistante (une seule fois)
  au lieu d'enchaîner des one-shots — voir SKILL.md "Hôte distant — une
  session, pas une rafale". `send` avertit sur stderr (jamais bloquant) à
  partir du 2e one-shot SSH consécutif.

## Never send the next command until the previous one shows exit in the pane

Each framed `send` ends with `└─[#N] exit <code>`. Use `wait-done` before the
next `send` — do not guess with agent-side `sleep` or grep arbitrary output
text:
```bash
$COCKPIT send 'bash ~/wsh-gw-restart.sh 60 2>&1' cockpit-theo-plan-225108
$COCKPIT wait-done cockpit-theo-plan-225108 120    # blocks until #[N] exit seen
# only if exit 0:
$COCKPIT send 'openclaw infer model run ... 2>&1' cockpit-theo-plan-225108
$COCKPIT wait-done cockpit-theo-plan-225108 180
```
`wait-done` reads the `@[wsh_seq]` counter set by the last `send` and polls
the tmux pane for the matching footer. Timeout defaults to 300s
(`WSH_WAIT_TIMEOUT`). Add `--print` to also emit the result — bounded by the
`┌─[#N]`/`└─[#N]` markers, no line count to guess — in that same call instead
of a separate `read`/`output`; see `docs/framing-and-transfer.md` → "Lire un
résultat sans deviner".
