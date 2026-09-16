# Internals

> **Pour le mainteneur, pas pour l'agent.** Ce fichier documente le pourquoi
> des gardes présentes dans les scripts — mesures tmux, régressions,
> historique des fixes. Il n'est volontairement référencé depuis AUCUN
> `SKILL.md`, pour ne pas entrer dans le contexte d'un agent. Les pièges
> réellement opérationnels (ce qu'un agent doit taper différemment) sont dans
> `docs/gotchas.md`.

## Garde own-session sur la réutilisation et les chemins d'écriture

**A reused session can turn out to be your OWN Claude Code terminal —
`spawn` guards automatically, but know the failure mode.**
`find_reusable_session` looks up the last-remembered session **for the
agent/prefix key**, not for the exact positional name you passed — if that
key was ever recorded against a tmux session that got repurposed later
(e.g. a human attached it and started an interactive program, including
another `claude` CLI), a bare `spawn` would hand it back with zero content
check. `send`ing into that pane doesn't run a command — it types text into
whatever's running there; against a live Claude Code REPL, your "situate"
probe (`hostname; pwd; whoami`) gets submitted as a **new chat message**
instead of executing, and you only notice from the confused reply.
`session_safe_to_reuse()` (`lib/session.sh`) guards on two checks before
any reuse: (1) an unconditional block on any tmux session that resolves to,
or shares a pane with, the one the caller is itself running inside — exact
name, prefix, fnmatch, anchored `=name`, or a grouped session under another
name are all caught primarily via `$TMUX_PANE` membership in
`mux_session_panes` (`tmux list-panes -s`); when `$TMUX_PANE` is unset, the
guard can no longer establish identity at all and refuses outright
(`own_tmux_session` returns rc=2, Task 8) instead of falling back to a name
comparison — this catches the incident above, since
`pane_current_command` alone would report "bash" from inside the check
itself; (2) a `pane_current_command` heuristic that rejects any OTHER
session whose foreground isn't a bare shell. `start <name> --reuse` refuses
the caller's own session with exit 8 but deliberately applies only check 1:
`--reuse` is an explicit "continue THIS session", so a non-shell foreground
is presumed known to the caller — only `spawn`'s silent reuse runs the
bare-shell heuristic too. History: guard introduced by
`a920197` (#7), silently lost in the `9863c07` regression, reintroduced
with `selftest-guard`. Since Task 2 (lot 2), the same own-session check
guards the WRITE paths too: `send`/`keys`/`step-run`/`banner` all refuse
outright (exit 8, `deny_own_session`, `lib/session.sh`) when the resolved
session is the caller's own — against a bare shell this used to TYPE the
command into the caller's own pane, queued silently behind the still-
running caller until it eventually finished (measured: `step-run` timing
out at rc=124 rather than ever seeing the real result, since `wait-done`
gave up long before the queued text got a chance to run). `read`/`output`/
`wait-done` stay unguarded — read-only, no self-interference hazard (plan
§3).

## Anchoring `=` et résolution par préfixe des noms de session

**A session name is now taken literally — abbreviations by prefix are no
longer accepted.** `mux_has`/`mux_kill`/`mux_clients` (`lib/mux.sh`) anchor
their tmux target with `=` (`-t "=$1"`), forcing an exact match. Before
this, an unanchored `-t "$1"` let tmux fall back from exact match to
session-name prefix, then to fnmatch — so `mux_has "cockpit-foo"` could
silently resolve to `cockpit-foo-bar-123456` and a remembered dead session
could "come back to life" via a same-prefixed homonym. This was never a
designed shortcut: `resolve_session` (`lib/session.sh`) is a pure
passthrough with no resolution logic of its own, so the old fallback was
tmux's default behavior leaking through, not a feature. The one place this
changes visible behavior is argument disambiguation in `wsh-live.sh`
(`output`/`step-run` parsing "is this token a session name or something
else?"): a prefix typed by a caller now falls through to the other
category instead of matching. Covered by `selftest-guard` cases 13-17 (18
adds a positive control — see `lib/selftests.sh`).
Whether a tmux command honors `=` is **not** predictable from "target-session
vs target-pane" alone — measure per command:

- Honor `=` (target-session): `has-session`, `kill-session`, and
  `list-clients` (measured: `list-clients -t "=beta"` → rc=0, `-t "=bet"` →
  `can't find session: bet`, rc=1). `mux_clients` is anchored the same way
  as `mux_has`/`mux_kill` — free to add, since its 4 callers
  (`wsh-live.sh:441,477,727,730`) only ever receive names already
  validated by `need_session`/`last_session`.
- Reject `=` outright and resolve by PREFIX instead (measured, tmux 3.7b):
  `set-option`/`show-option`, along with `send-keys`, `capture-pane`,
  `split-window`, `pipe-pane`. Previously misclassified in this file as
  honoring `=` — measured wrong, by deduction, not by running it (see the
  I2 gotcha below for what that cost). Measured on an isolated server with
  only a session named `soptlong`: `set-option -t "=sopt" @m 1` → rc=1
  `no such session: =sopt` (the anchor is rejected), but `set-option -t
  "sopt" @m 7` → rc=0, and `show-option -v -t soptlong @m` → `7` — the
  unanchored write landed on `soptlong` via prefix resolution, the exact
  opposite of what an anchored command would do. Piège associé :
  `show-option -qv -t "=X" @opt` still returns rc=0 with an EMPTY value
  when `X` doesn't exactly exist (`-q` swallows the "no such session"
  error) — a quiet empty result is not proof the target was rejected, nor
  that it doesn't exist. Fixing prefix ambiguity for these commands means
  canonicalizing the name once via `mux_session_name` and propagating
  only that — a separate piece of work (`send-keys`/`capture-pane`/
  `split-window`/`pipe-pane` still need it; `set-option`/`show-option` in
  `teardown_session` got a narrower fix — see the next gotcha).

Fixed for the discrimination itself (not the canonicalization above) by the
`2026-08-02-desambiguisation-argument-session.md` lot: a token still gets
dropped from ITS category when it doesn't look like a session at all, but a
token whose FORM matches (`cockpit-*`, the bare `cockpit` default, or an
anchored `=…`) no longer falls through silently just because it happens not
to exist right now — `looks_like_session` (`lib/session.sh`) makes that
call by shape, before `mux_has` ever asks about existence, and a token that
passes it but is dead reaches `need_session` and fails loud (`no tmux
session 'X'`, exit 4) at `banner`/`wait-done`/`output`/`step-run`, the same
four sites this gotcha names. `--session NAME` / `-s NAME`
(`parse_session_flag`) sidesteps the whole discrimination for a caller that
already knows the name it wants — including one that doesn't match
`cockpit-*` at all (`start` accepts free-form names) — short-circuiting
straight to `resolve_session`/`need_session`; a flag with no value (end of
arguments, or a value starting with `-`) is a usage error, exit 2, not a
silent no-op. Covered by `selftest-guard` cases 30-36.

## `stop <prefix>` a pu corrompre silencieusement une session voisine

**`stop <prefix>` used to silently corrupt a LIVE neighbour session
instead of doing nothing.** `stop` (`wsh-live.sh`) passes its raw argument
straight to `teardown_session` (`lib/session.sh`) with no `mux_has` check
of its own. `teardown_session`'s six `tmux set-option -u -t "$sess"` calls
are unanchored, and `set-option` resolves by PREFIX (see the gotcha
above) — so `stop cockpit-nb`, with no session exactly named
`cockpit-nb` but a live `cockpit-nb-222222` next to it, used to wipe that
neighbour's `@wsh_remote_mode`/`@wsh_remote_host`/helper-path options
while the anchored `mux_kill` right after correctly (and silently)
refused to kill anything — measured end to end: `stop cockpit-nb` prints
`no session 'cockpit-nb' to kill` (rc=1) and the neighbour's three
options come back empty immediately after, with the neighbour itself
still alive and never mentioned. Concretely dangerous for a neighbour
mid-SSH-hop with `remote-init` done: its next `send` loses remote mode
and tries to source a helper path local to the Mac on the remote host;
`push`/`pull` lose the recorded host. Not a new hole — before the "="
anchoring (Task 6), the same call used to actually KILL the neighbour
(loud, at least visible); anchoring `mux_kill` alone turned that into a
silent partial corruption instead. Fixed by gating the six set-option
calls on an anchored `mux_has "$sess"` check at the top of
`teardown_session` (`lib/session.sh`): only once that confirms an
EXACT session exists does the function resolve its canonical name
(`mux_session_name`) and touch its options; a bare prefix with no exact
match now leaves the block untouched entirely. Closing `stop`/`gc`
themselves against acting on a prefix at all (rather than just this one
function's internal consistency) is deferred to
`docs/plans/2026-08-02-desambiguisation-argument-session.md`.

## Garde own-session sur `gc` et `stop` (implémentation)

**`gc` now refuses to destroy its own session; `stop` refuses outright
(exit 8).** (Task 1, lot 2.) `gc_should_kill` (`lib/gc.sh`) itself stays
a pure idle/attached check — the own-session guard lives in `cmd_gc`
instead: a probe before the loop (`session_is_own` on a name that can
never exist) refuses the WHOLE sweep, printing a note and destroying
nothing, when identity is indeterminable (`$TMUX` set, `$TMUX_PANE`
unset); inside the loop, any candidate that IS the caller's own session
is skipped — counted `kept`, the sweep continues on the others (unlike
`stop`, this is a skip, not an error). `--dry-run` still lists normally
regardless (it never destroys anything, so the indeterminate-identity
probe is skipped for it). Measured before this guard existed: running
`gc --idle=0` from inside a detached `cockpit-*` session killed that
session out from under itself — conditions to self-kill were the calling
session named `cockpit-*`, detached (no attached tmux client), and idle
for at least the threshold (default 86400s, override with `--idle=`);
`gc` runs automatically, best-effort, in the background on every `spawn`
and every `start`, so this could fire without the caller ever running
`gc` by hand. `stop <session>` (`wsh-live.sh`) got its own, stricter
guard on the same `session_is_own`/`session_own_refusal`/
`session_indeterminate_refusal` helpers (`lib/session.sh`) already used
by `start --reuse`: unlike `gc`'s skip-and-continue, a `stop` on the
caller's own session refuses outright (exit 8, same family as `start
--reuse`'s own-session refusal) — there is no "continue on the rest",
`stop` only ever targets the one session it was given. The remaining
ergonomic gap (how a caller should DISAMBIGUATE which session they meant
in the first place, rather than just being refused) is tracked in
`docs/plans/2026-08-02-desambiguisation-argument-session.md` §3 bis.

## `selftest-guard` opère sur le serveur tmux par défaut

**`selftest-guard` creates sessions on the DEFAULT tmux server, some of
them GROUPED onto the caller's own live session.** Case 10 (grouped
session sharing the caller's pane) runs `tmux new-session -t "=$own"`
against whatever real tmux session is currently running the selftest
itself — not an isolated `-L` socket. It cleans up after itself
(`tmux kill-session` on its own throwaway names, plus the EXIT trap), but
it is operating directly on the tmux server that also holds the user's
real Wave-wrapped sessions for the duration of the run. Never invoke it
from inside a session you cannot afford to see momentarily grouped, and
never edit it without re-reading the cleanup trap.
A session literally named `=foo` is not addressable through this code: the
`${1#=}` strip in `mux_has`/`mux_kill`/`mux_clients` treats a leading `=`
as the anchor marker, not as part of the name. Unreachable via generated
names (`cockpit-<prefix>-<ts>`, `[a-z0-9-]`), but reachable via a
free-form name passed to `start`.

## L'anchoring ferme la cible implicite "session courante"

**Anchoring turned an implicit "current session" target into a safe
no-op.** Measured: `tmux has-session -t ""` → rc=0, resolving to whatever
session is CURRENT on the server; `tmux has-session -t "="` → rc=1 ("no
mouse target" — sic). So before this lot's `=` anchoring, `mux_has ""` was
true and `mux_kill ""` targeted a real, implicit session — the server's
current one. After anchoring, the same empty argument is a safe no-op.
Unreachable today (`teardown_session` only ever receives canonical names,
`resolve_session` falls back to `SESS_DEFAULT` rather than passing an
empty string through) — but it is exactly the failure mode this lot exists
to close.

## Adoption d'une session laissée mid-ssh (`WSH_COCKPIT_ADOPT`)

**A cockpit left mid-`ssh`/`tailscale ssh` still doesn't look reusable to
ORDINARY `spawn`.** Once hopped, the pane's foreground isn't a bare shell
anymore, so `session_safe_to_reuse` refuses it (registry step 1 and the
legacy scan step 3 both rely on it) and `spawn` opens a fresh session — new
FIDO2 auth and a second Wave block. Still not a bug: `pane_current_command`
says nothing about what's running at the far end of the tunnel (a remote
shell is reusable, a remote `claude` isn't), and that information isn't
available locally without a probe. The wrapper/adoption lot (fiches 1.2-1.9)
DID add a relaxed check — `adopt_state_allowed` accepts a bare shell OR an
`ssh`/`tailscale`/`mosh` foreground, gated by the mandatory situate probe
(`adopt_run_probe`) — but **only** for step 2 of `spawn`'s resolution, i.e.
a session explicitly listed in `WSH_COCKPIT_ADOPT` (see
`docs/session-lifecycle.md` → "Opening a cockpit"). It is deliberately NOT
applied to my own last-remembered session or to the legacy scan — silently
reusing a session *I myself* left mid-hop carries the same "your probe
becomes a chat message" risk as the incident described above, and the
explicit `WSH_COCKPIT_ADOPT` list is the only place that risk is judged
worth taking (the sessions there were pre-opened *for* this purpose).
Workaround unchanged for anything outside `WSH_COCKPIT_ADOPT`: reuse the
existing session explicitly (`SESSION=…`) instead of calling `spawn` again.

## La probe d'adoption ne fait jamais confiance à l'état remote-mode mémorisé

**The adoption probe never trusts a session's remembered remote-mode
state — it re-frames itself inline every time.** A `keep` session can be
released, picked up by a completely different agent, ssh-hopped again to a
different host, released again… any number of times before the next
adoption — its sticky `@wsh_remote_mode`/helper-path tmux options reflect
whatever the PREVIOUS occupant last set, not necessarily reality for the
agent adopting it now. `adopt_run_probe` (`lib/session.sh`) forces
`WSH_LIVE_SEP_REINIT=1` on its own `send`/`wait-done`/`read` calls
regardless of what the session's options claim — self-contained inline
framing, never the pushed-helper form — so the probe itself can never be
the thing that silently breaks because a stale remote-mode flag pointed it
at a helper file that no longer exists on that host. This is deliberately
probe-only: once the probe succeeds and you know where you actually are,
a normal `remote-init "$SESS" <host>` (or `local-init`) still applies if
you want the short-form framing for the rest of the workflow.

## Détection d'une commande tapée mais pas soumise (RPROMPT powerlevel10k)

**A command typed but not yet submitted is invisible to the adoption
guard's process check — the last captured pane line is the only signal
that catches it, and it only recognizes the machine's actual prompt
shapes.** `mux_pane_command` (`lib/mux.sh`) reports the pane's FOREGROUND
process; while a human or a prior agent is mid-keystroke on a command
(no Enter pressed yet), that process is still the bare shell, so
`adopt_state_allowed` alone would call the pane adoptable and the
probe's own `send` would land its text on top of the unsubmitted
input, merging into a garbled command. Measured on this machine's real
prompt (disposable tmux session, zsh + powerlevel10k-style theme with a
right-side RPROMPT segment): the rendered last line pads out to the pane
width and appends `─`+a corner glyph (`╮`/`╯`) flush right REGARDLESS of
whether text was typed — a naive "anything after the prompt glyph"
check would refuse every adoption. `adopt_last_line_busy`
(`lib/session.sh`) strips that decoration if present, then recognizes
exactly two shapes: bare `❯` (idle, adoptable) vs `❯ <text>` (busy,
refused). Anything else — a different prompt theme (classic `$`/`%`/`#`,
non-p10k themes), an empty capture, unrelated scrollback — is
UNCLASSIFIED and is treated as adoptable: a false positive here would
make a healthy cockpit unadoptable, which is worse than the accepted
best-effort gap. `mux_pane_last_line` captures with `-J` (joins
tmux-wrapped physical rows back into one logical line) specifically
because the padded RPROMPT row can exceed `#{pane_width}` without tmux
ever setting the wrap flag — `-J` re-joins it either way, so the
predicate always sees the true tail of the logical line. Net effect:
this mitigation only protects sessions using a prompt shape it
recognizes; a custom or unrecognized prompt with text typed but not
submitted can still slip through unrefused.

## Wave state DB vs fallback disque : désynchronisation de 9 jours

**The live Wave state DB and its on-disk fallback path can disagree by
days.** Two different resolvers exist in `lib/wave.sh`: `wave_db_ro()`
(used by tab-cache resolution, `open`'s auto-open path) falls back to the
hardcoded `~/Library/Application Support/waveterm` when `wsh wavepath data`
fails or is empty; `wave_db_ro_strict()` (used only by `open --tab`'s
`resolve_tab_by_name`) refuses outright (rc=1) instead of ever touching
that hardcoded path. This isn't cosmetic: measured in step-1.1, the
hardcoded fallback pointed at a DB snapshot **9 days stale** relative to
the live one `wsh wavepath data` resolves dynamically — a `--tab` lookup
silently falling back to it could match (or miss) a tab that was
renamed/closed/created days ago. If you're adding a NEW caller that needs
the live DB and correctness matters more than best-effort availability,
reach for `wave_db_ro_strict()`, not `wave_db_ro()`.

## Machine d'états du claim (`lib/claim.sh`)

Chaque étape de la résolution `spawn` (registre → adoption → scan legacy) passe
par la machine d'états de `lib/claim.sh` : **ABSENT → PRÉ-CLAIM → EN-COURS →
POSSÉDÉ**. Invariant I3 : toute session réclamée par quiconque, dans n'importe
quel état au-delà d'ABSENT, est ignorée par les étapes situées en dessous —
jamais de double claim silencieux. Deux agents ne peuvent donc pas finaliser la
même session, et une adoption qui échoue (sonde en échec, pane occupé) restaure
le claim précédent au lieu de le perdre.

`release_session` sur une session **sans** marqueur `keep` supprime le fichier de
claim entièrement (retour ABSENT, re-scannable à l'étape 3). Sur une session
**avec** `keep`, le claim est rétrogradé en pré-claim `released`, ré-adoptable via
l'étape 2 et jamais redétruit au passage.

## Wrapper `claude-cockpit` — détails d'environnement

Le wrapper crée chaque cockpit en `spawn --force --preopen` (jamais une
réutilisation silencieuse) et pose `WSH_COCKPIT_AGENT=claude-<epoch>-<pid>`.
Il retire explicitement `WSH_COCKPIT_PREFIX` de l'environnement de l'agent, même
si elle était héritée : elle prendrait sinon le pas sur `WSH_COCKPIT_AGENT` dans
`normalize_prefix`.

Le balayage de sortie ne saute que si le wrapper lui-même crashe. Les sessions
jamais adoptées restent sous la clé `user-preopen-<n>`, les adoptées passent sous
`claude-<runid>`.

## Fermeture du bloc Wave (`teardown_session`)

`open`/`spawn` impriment `opened Wave block <block-id> ...` et mémorisent cet id
sous `~/.cache/wsh-cockpit/block-<session>`. `teardown_session` — partagé par
`stop` et `gc` — le relit et lance `wsh deleteblock -b <block-id>` en
best-effort : le bloc se referme parfois tout seul quand le process du pane
sort, auquel cas `deleteblock` retourne simplement `not found` ; l'absence de
`wsh` sur le `PATH` est également tolérée. Le repli manuel (`tmux attach`
imprimé) ne sert que si le fichier d'état manque — bloc ouvert à la main, ou
état effacé sous ses pieds.

## Couverture selftest de `gc`

`selftest-gc` teste la décision pure, sans tmux réel — à lancer après toute
retouche de `lib/gc.sh`.

## Framing `send` — helper versionné, compteur, couleurs

Le framing stocke de petites fonctions dans un helper à chemin court versionné
(`~/.cache/wsh-cockpit/helpers/wsh-live-sep-vN.sh`). Le premier `send` framé d'une
session tmux le source ; les suivants n'émettent qu'un appel compact
`__wsh <seq> <cmd>`. Le helper affiche la commande, la lance avec le shell du
pane, capture `$?`, puis imprime le footer.

Largeur des règles : celle de `COLUMNS`, plafonnée à 100. Sur un pane TTY :
séparateurs **bleu ciel**, `[#N]` **cyan électrique**, horodatage bleu, `$`
**jaune vif**, commande **blanc intense**, footer **vert néon** (exit 0) /
**rouge vif** (échec) — 256 couleurs saturées, dégradées en texte plain hors TTY.

Un compteur par session vit dans un fichier d'état sous `~/.cache/wsh-cockpit/`,
si bien que la séquence `#N` persiste d'un `send` à l'autre sans fichier
temporaire ; `stop` le remet à zéro.

Les bannières n'utilisent jamais les tokens `START`/`END` : pas de collision avec
les marqueurs de `rexec`, et `read` reste un `capture-pane` lisible par un humain.

En mode remote, le helper est re-sourcé **à chaque appel** (pas de suivi « chargé
une fois » pour ce cas) : aucun risque d'état périmé si le pane se reconnecte.

## Bannières — palette et rendu attendu

```
┌────────────────────────────────────────────────────────────────────────┐   ← cyan dim
│                         PHASE 1 / 6                                    │   ← cyan bold
│                      Fondations & isolation                            │   ← blanc
└────────────────────────────────────────────────────────────────────────┘



────────────────────────────────────────────────────────────────────────   ← jaune dim
  ▸  [1.1]  openclaw doctor                                               ← jaune / blanc
────────────────────────────────────────────────────────────────────────
```

Palette par type (256 couleurs saturées) :
- **`header`** — bordures **turquoise**, titre **magenta hot**, session bleu ciel.
- **`phase`** — bordures **turquoise**, `PHASE N / T` **cyan électrique**, sous-titre blanc intense.
- **`step`** — bordures **jaune vif**, `▸ [id]` **orange**, libellé blanc intense.
- **`done`** — bordures **vert néon**, `✓ message` **vert lime**.

Le rendu a une seule source de layout (`__wsh_banner` dans `wsh-step.sh defs`) ;
le live `banner` et le preview direct l'utilisent, seul le fallback
`WSH_STEP_INLINE=1` répète la mise en page en `printf` plat.

## Backend Zellij (expérimental)

`WSH_MUX=zellij scripts/wsh-live.sh …` pilote une session **Zellij** au lieu de
tmux, avec le même cœur de boucle : `spawn`/`start`/`send`/`read`/`wait-done`/
`stop`/`status`/`open` (le bloc Wave exécute alors `zellij attach`).

- Une session Zellij background n'a **pas de pane** tant qu'un `run` n'en crée
  pas un ; le script le fait et mémorise le pane-id (`~/.cache/wsh-cockpit/pane-*`),
  car les actions Zellij headless doivent cibler le pane explicitement.
- Restent **tmux-only** avec refus explicite : `keys` (noms de touches tmux) et
  `web` (ttyd a besoin de l'attach lecture seule ; Zellij a son propre
  `zellij web`). Le journal d'audit (`pipe-pane`) est aussi tmux-only, mais ne
  bloque pas la session : elle démarre quand même, non journalisée, avec un
  avertissement explicite sur stderr (`UNLOGGED`) plutôt qu'un refus silencieux.
- Le framing `send` re-source le helper à chaque appel (pas de store d'options
  par session côté Zellij) : ligne visible un peu plus longue, comportement sûr.
- Gate de non-régression : `WSH_MUX=zellij scripts/wsh-live.sh selftest-live`
  doit passer, comme la version tmux, après toute retouche du cœur live.
- Le rendu headless Zellij peut être paresseux au premier write : `wait-done`
  (polling adaptatif) l'absorbe ; ne pas réduire ses timeouts sous zellij.

## Selftests à lancer selon la zone retouchée

- **Framing / quoting** → `scripts/wsh-live.sh selftest-sep` (helper wrapper sous
  bash et zsh, sans tmux).
- **Cœur live** (framing, `wait-done`, `banner`, `stop`, fichiers d'état) →
  `selftest-sep` **et** `selftest-live`, ce dernier exerçant la vraie boucle tmux
  bout-en-bout sur une session `cockpit-selftest-$$` jetable, sans jamais ouvrir
  de bloc Wave. `remote-init` avec un `<host>` (le chemin qui pousse les helpers
  via `wsh-push.sh`) n'est **pas** couvert — il dépend d'un hôte distant réel — et
  a été vérifié manuellement à la place (voir la PR).
- **`send`** (framing, garde one-shot SSH) → aussi `selftest-oneshot-ssh`, pur,
  sans tmux.
- **`wsh-push.sh`, `push`/`pull`, socket `ControlMaster` de session**
  (`control_path_for_session`, `remote_host_*` dans `lib/session.sh`) → aussi
  `selftest-transfer`. Les cas d'erreur (fichier local absent, hôte injoignable)
  sont couverts sans hôte distant réel ; le round-trip checksum et le cas
  fichier-distant-absent tournent en plus si ce Mac accepte le ssh loopback vers
  lui-même (sinon `skip` explicite), et le transport `ControlMaster` a été vérifié
  manuellement contre un hôte réel du tailnet (voir la PR).
- **Rendu des bannières** → `scripts/wsh-step.sh selftest-step` (garde
  `direct ≡ cmd ≡ defs`, bash+zsh, couleurs forcées).
- **Documentation du skill** → `scripts/wsh-live.sh selftest-docs` (budget de
  tokens, couverture des sous-commandes, liens, règles impératives).

## Rationale déplacée depuis `docs/gotchas.md`

Ces passages expliquent *pourquoi* les pièges de `gotchas.md` existent. Ils ne sont
pas nécessaires pour agir : l'opérationnel reste dans `gotchas.md`, qui pointe ici.

**`docker exec` — une couche de plus.** `remote-init <host>`/`--pre` poussent les
helpers sur l'HÔTE ; une fois le pane dans `docker exec <c> bash` (ou
`docker compose exec`), ce chemin n'existe pas dans le conteneur, donc le sourcing
échoue. C'est pourquoi `remote-init --container` copie les mêmes fichiers au même
chemin absolu dans le conteneur, sans changement de forme côté `send`/`banner`.
Best-effort assumé : `docker`/`tailscale` manquant ou conteneur injoignable →
warning stderr, retour non nul, jamais de hard fail. Couvert par `selftest-live`
cases 14a-14c. Détail transport : `docs/framing-and-transfer.md`.

**`remote-init "$sess"` sans hôte — historique.** Avant, la forme sans hôte
basculait juste le flag sticky sans vider un éventuel chemin helper remote
enregistré par un `remote-init <host>` antérieur sur la même session : le mode
« inline-only » n'était pas réellement inline, `send` continuait de sourcer
l'ancien chemin, possiblement injoignable. Corrigé : la branche sans hôte appelle
le même `remote_helper_paths_clear` que `local-init` avant de poser le flag.
Couvert par `selftest-live` case 13.

**Réutilisation par `spawn` — pourquoi elle n'est plus inconditionnelle.** Le lot
registre/adoption (fiches 1.2-1.9, voir `docs/session-lifecycle.md` → « Opening a
cockpit », étapes 1-4) a retiré la garantie « `spawn` sans `--force` réutilise
toujours » : un `spawn` avec un préfixe explicite qui ne correspond à rien dans le
registre, `WSH_COCKPIT_ADOPT` ou le scan legacy **crée une cockpit neuve** — un
second onglet non demandé, exactement comme `--force`.

**Attente du gateway — boucle inline complète.** L'option scriptée
(`bash ~/wsh-gw-restart.sh 60`, déployée par `wsh-push.sh`) est préférée. Variante
« une seule commande `send` », utile quand aucun helper ne peut être déployé :

```bash
$COCKPIT send '{ R=1; openclaw gateway restart && { EL=0; while [ $EL -lt 60 ]; do sleep 3; EL=$((EL+3)); if openclaw gateway status 2>&1 | grep -q "Connectivity probe: ok"; then echo READY:$EL; R=0; break; fi; echo waiting:$EL; done; }; openclaw gateway status 2>&1 | head -12; [ "$R" -eq 0 ]; } 2>&1'
```

`openclaw gateway restart --wait 45s` couvre le même cas en une commande. Ne pas
enchaîner (`infer`, `agent`) avant `Connectivity probe: ok`.

**Pourquoi `2>&1` est non négociable.** Si une commande écrit sur **stderr** et que
stderr n'est pas redirigé, cette sortie peut arriver **après** le footer
`└─[#N] exit <code>` du pane (ou hors de la fenêtre de `read`) : l'utilisateur croit
alors que « les commentaires de fin d'exécution » manquent. `2>&1` fait fusionner
stdout et stderr dans le pane **avant** l'impression du footer, qui reste donc
fidèle et complet.

**Mécanique de `wait-done`.** `wait-done` lit le compteur `@[wsh_seq]` posé par le
dernier `send` et *poll* le pane tmux jusqu'au footer correspondant. Timeout par
défaut 300 s (`WSH_WAIT_TIMEOUT`).
