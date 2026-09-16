# Framing des `send` et transfert de fichiers

## Pousser des fichiers vers un remote — jamais base64 dans `send`

Le cockpit est fait pour des **commandes courtes** visibles dans Wave. Y coller du
base64, des `printf '%s' '…'` géants ou des heredocs casse le shell
(`cursh quote>`), dépasse la limite tmux et pollue l'écran que l'utilisateur
regarde. **Séparer transfert et exécution :**

```bash
# NON — base64 dans send
send 'python3 -c "import base64; ... decode('\''GIANT...'\'')..."'
# NON — printf base64 en morceaux
send "printf '%s' 'IyBUT09M...' > /tmp/x.b64"
# NON — cat/heredoc du contenu d'un fichier à travers le pane, même "juste pour lire"
send "cat /remote/path/big-file.log"
```

### Voie officielle quand le pane est en SSH — `push`/`pull`

Une fois que le pane a fait son hop (`remote-init`/`--pre <host>` a enregistré
l'hôte pour la session), l'hôte est déduit de l'état de session — pas besoin de le
redonner, impossible de se tromper entre deux appels :

```bash
scripts/wsh-live.sh push "$SESS" ./local-file.md /remote/absolute/path.md
scripts/wsh-live.sh pull "$SESS" /remote/absolute/path.log ./local-copy.log
```

Ordre de fallback, identique dans les deux sens, choisi automatiquement et
**annoncé sur stderr** :

1. **`wsh file cp`** — si Wave a déjà une route pour la connexion.
2. **Socket `ControlMaster` de la session** — réutilise la connexion OpenSSH déjà
   authentifiée du hop du pane, zéro nouvelle auth FIDO2. Skip silencieux si le
   hop était un `tailscale ssh` (pas de ControlMaster) ou si le pane n'a pas hopé.
3. **`tailscale ssh`** — pipe stdin (push) / `cat` (pull), auth tailnet
   transparente, pas de multiplexage.
4. **`scp` nu** — dernier recours, avertissement sur stderr, ré-auth probable.

`push`/`pull` tournent depuis le shell agent (jamais via `send`) : ils ne comptent
**jamais** pour l'avertissement one-shot SSH, qui ne surveille que `send`. Sans
hôte enregistré, ils échouent avec un message clair plutôt que de deviner.

### Hors session SSH — `wsh-push.sh` ou `wsh file` directement

```bash
PUSH=/Users/qveys/.claude/skills/wsh-cockpit/scripts/wsh-push.sh
$PUSH /tmp/theo-tools.md /Users/qveys/agents/theo-marceau/TOOLS.md
$PUSH ./patch.json5 /Users/qveys/theo-patch.json5 qveys@macbook-openclaw

wsh file cp -f ~/Git/mon-fichier.md wsh://qveys@macbook-openclaw/Users/qveys/cible.md
cat contenu.md | wsh file write wsh://qveys@macbook-openclaw/Users/qveys/cible.md
wsh file cat wsh://qveys@macbook-openclaw/Users/qveys/cible.md   # lire
```

Même chaîne de fallback, moins l'étape `ControlMaster` (pas encore de hop à ce
stade). Puis vérifier dans le cockpit avec une commande courte :
`send 'wc -c ~/agents/theo-marceau/TOOLS.md && head -5 …'`.
Doc Wave : [wsh file write/cp](https://docs.waveterm.dev/wsh-reference#file-write)

## Command framing (visual delimiters)

L'utilisateur *regarde* le pane où tu tapes : sans délimiteurs, les `send`
successifs se confondraient. Chaque `send` est donc encadré.

```
┌─[#3] 18:05:59          ← seq incrémental + horodatage
│$ ls /nonexistent-xyz   ← la commande, échoée
ls: /nonexistent-xyz: No such file or directory   ← sortie réelle
└─[#3] exit 1            ← footer : même seq + code de sortie
```

Le footer ne s'imprime **qu'après** le retour de la commande : une commande
interactive (`sudo` attendant un mot de passe, un pager, un `read`) tourne
normalement et la bannière de fermeture n'apparaît qu'à la fin — alimente son
entrée avec `keys` entre-temps. Largeur des règles, palette et mécanique du
helper versionné : `docs/internals.md`. **Exception mesurée** (hop distant) : un
`sudo` cadré peut rendre la main en EOF au lieu d'attendre, auquel cas `keys` arrive
trop tard — `docs/gotchas.md` → « `sudo` ne reçoit pas le TTY ».

**Désactiver :** `WSH_LIVE_SEP=0 scripts/wsh-live.sh send '<cmd>' [session]`
envoie la commande brute, sans framing — utile pour piloter un TUI/REPL que
l'écho supplémentaire dérange. Défaut : `WSH_LIVE_SEP=1`.

## Lire un résultat sans deviner (`output`, `wait-done --print`)

Les marqueurs `┌─[#N]` / `└─[#N] exit <code>` délimitent chaque `send` de façon
déterministe — aucun nombre de lignes à deviner :

```bash
scripts/wsh-live.sh send 'seq 1 500' "$SESS"
scripts/wsh-live.sh wait-done "$SESS" 30 --print   # attend le footer PUIS imprime le segment — un seul appel
# — équivalent à —
scripts/wsh-live.sh wait-done "$SESS" 30
scripts/wsh-live.sh output "$SESS"                 # défaut = le dernier send
```

`output [session] [seq] [--full]` extrait exactement le segment du header au
footer inclus. Pas de troncature aveugle : au-delà de `WSH_READ_MAX` lignes (120
par défaut), il imprime les ~30 premières + une note `« K lignes omises »` + les
~60 dernières (la fin porte les erreurs et le footer). `--full` désactive le
plafond.

Cas dégradés — jamais de mensonge, toujours un message clair sur stderr : segment
sorti du scrollback capturé → repli suggéré sur `read N` ; pane sans marqueurs
(`WSH_LIVE_SEP=0`, `keys`, TUI/REPL) → `output` l'explique et suggère `read N`.
`read [session] [lines]` reste la voie de l'inspection libre.

## Remote shell / lost helpers

Dès que le pane `ssh`/`tailscale ssh`-hop vers un hôte distant, le fichier helper
local n'existe pas là-bas et son sourcing échoue (« command not found »). Deux
façons de prendre les devants.

**Recommandé, hôte connu d'avance — pousser AVANT le hop** (mécanisme complet :
`docs/session-lifecycle.md`) :

```bash
scripts/wsh-live.sh remote-init --pre <host> "$SESS"   # ou : spawn --pre <host>
scripts/wsh-live.sh send 'tailscale ssh <host>' "$SESS"   # le hop lui-même
```

**Sinon — après le hop**, une fois la sonde « situer le shell » confirmant un
écart d'hôte (`spawn --situate` fait ce contrôle et cet appel automatiquement,
best-effort) :

```bash
scripts/wsh-live.sh remote-init "$SESS" <host>   # <host> = ce qu'accepte tailscale ssh/scp
```

Avec `<host>`, `remote-init` pousse les helpers sur cet hôte et enregistre les
chemins, si bien que chaque `send`/`banner` ultérieur garde la forme courte,
pointée sur la copie distante. Si le push échoue (pas de route, `$HOME`
injoignable), il avertit sur stderr et se replie sur le framing inline — il ne
fait **jamais** échouer l'appel. **Un seul hop :** re-hopper vers un TROISIÈME
hôte n'est pas suivi, le framing y repasse en inline (toujours correct, juste pas
optimisé).

**Descendre d'une couche de plus — un conteneur Docker.** Un `docker exec <c>
bash`/`docker compose exec <c> bash` dans une session déjà hoppée est une couche
que le fichier helper poussé pour la couche du dessus (hôte ou Mac) n'atteint
pas : `send`/`banner` continuent d'émettre la forme courte `. '<chemin>' &&
__wsh ...` inchangée, mais `<chemin>` n'existe pas dans le conteneur — le
sourcing échoue (`No such file or directory`, footer perdu — voir
`docs/gotchas.md`). Pas de repli inline ici : le fix est de faire exister le
MÊME chemin une couche plus bas :

```bash
scripts/wsh-live.sh remote-init --container <container> "$SESS"
```

Copie les fichiers helper sep/step dans `<container>` au **même chemin absolu**
déjà enregistré pour la session — chemin identique, donc `send`/`banner` ne
changent en rien : simple transfert de fichiers, pas un nouveau mode de framing.
Best-effort : conteneur injoignable → avertissement stderr et retour non nul,
jamais de hard fail, et volontairement **pas de repli inline** (voir SKILL.md
« Descendre d'une couche »). Transport et rationale : `docs/internals.md`.

**Résoudre le nom du conteneur — jamais `docker ps --filter name=`.** `remote-init
--container` attend le **nom du conteneur**, ce que `docker exec`/`docker cp`
exigent. Si le service Compose porte un autre nom, résous-le **par le service** et
exige **un seul** conteneur en cours d'exécution : `docker ps --filter name=`
filtre par **sous-chaîne**, donc `name=paperclip` rend aussi
`paperclip-bef-paperclip-1` — deux noms pour un flag qui n'en accepte qu'un. Lance
la résolution **depuis le répertoire du projet Compose**, sinon `docker compose ps`
ne voit pas le service :

```bash
ids=$(docker compose ps --status running -q <service>)
count=$(printf '%s\n' "$ids" | grep -c .)
[ "$count" -eq 1 ] || { echo "attendu 1 conteneur, trouvé $count" >&2; exit 1; }
name=$(docker inspect --format '{{.Name}}' "$ids" | sed 's#^/##')
scripts/wsh-live.sh remote-init --container "$name" "$SESS"
```

**ControlMaster sur le hop lui-même.** Pour un hop OpenSSH (pas `tailscale ssh`,
qui ne le supporte pas), envoie-le avec le multiplexage activé :

```bash
scripts/wsh-live.sh send "ssh -o ControlMaster=auto -o ControlPath=~/.cache/wsh-cockpit/cm-$SESS -o ControlPersist=10m <host>" "$SESS"
```

La session interactive du pane EST alors la connexion maîtresse : `push`/`pull`
retrouvent ce socket par le seul nom de session et le réutilisent — pas de nouveau
prompt FIDO2. Ce n'est pas une entorse à « une seule session persistante » : c'est
la même session, utilisable aussi depuis le shell agent. Mécanisme :
`docs/internals.md`.

Sans `<host>`, `remote-init "$SESS"` reste un interrupteur **inline-only** sticky :
tout `send`/`banner` ultérieur utilise le wrapper auto-suffisant jusqu'à
`local-init "$SESS"` — par exemple quand le pane `exit` le hop.

`WSH_LIVE_SEP_REINIT=1` (pour `send`) et `WSH_STEP_INLINE=1` (pour `banner`)
restent valides comme **surcharge ponctuelle**, gagnant sur `remote-init` comme
sur le défaut :

```bash
WSH_LIVE_SEP_REINIT=1 scripts/wsh-live.sh send '<cmd>' [session]
```
