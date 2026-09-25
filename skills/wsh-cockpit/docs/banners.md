# Bannières d'étapes (`banner` / `wsh-step.sh`)

Détail complet du rendu, de la palette et des règles pour les annonces d'étapes
aérées. Voir `SKILL.md` pour le rappel court (obligatoire pour tout plan
multi-étapes) et la commande `step-run` (raccourci recommandé).

## Obligatoire pour tout plan multi-étapes

Quand tu exécutes un plan dans le cockpit (setup, déploiement, migration, audit…),
**tu dois annoncer chaque phase et chaque étape avec des bannières visuelles aérées**.
L'utilisateur regarde Wave en direct — des `echo "étape 1"` ou des commandes nues
en rafale sont illisibles.

**Interdit :**
```bash
send 'echo "=== PHASE 1 ==="'
send 'echo "ETAPE 1.1 doctor"'
send 'openclaw doctor'    # sans bannière step avant
```

**Obligatoire — utiliser `banner` :**
```bash
COCKPIT="<base directory of this skill>/scripts/wsh-live.sh"   # dossier affiché au chargement du skill

$COCKPIT banner header "Théo Marceau — OpenClaw" "cockpit-theo-plan-225108"
$COCKPIT banner phase  1 6 "Fondations & isolation"
$COCKPIT banner step   1.1 "openclaw doctor"
$COCKPIT send 'openclaw doctor'
$COCKPIT banner step   1.2 "Archivage workspace parasite"
$COCKPIT send 'mv ~/.openclaw/workspace ~/.openclaw/workspace.bak'
$COCKPIT banner done   "Phase 1 terminée"
$COCKPIT banner phase  2 6 "Identité & outils"
$COCKPIT banner step   2.1 "TOOLS.md"
# ...
```

`banner` applique le même mécanisme de helper versionné sourcé une fois par
session que le framing `send` (voir `docs/framing-and-transfer.md` → "Command
framing") : `__wsh_banner` (helper `~/.cache/wsh-cockpit/helpers/wsh-live-step-vN.sh`)
une fois, puis chaque bannière suivante n'est qu'un **appel court et lisible** :
`__wsh_banner done 'msg'` — fini le pavé `printf` de ~700 caractères retapé à
chaque fois. Pas de framing `send` autour (la bannière EST le séparateur visuel).

Si le pane a fait un `ssh` / `wsh ssh` vers un hôte **sans** le helper local, la
fonction sourcée n'existe plus là-bas : pose `WSH_STEP_INLINE=1` pour retomber sur
le one-liner autonome (`wsh-step.sh cmd …`), qui marche partout sans rien sourcer.

Rendu attendu et palette : `docs/internals.md`.

## Règles

- **`banner header`** une fois au début du workflow (titre + nom de session).
- **`banner phase N/T`** au début de chaque phase — avec lignes vides autour.
- **`banner step X.Y`** avant chaque **groupe logique** de commandes (pas chaque
  sous-commande triviale).
- **`banner done`** à la fin de chaque phase.
- **`send`** pour les vraies commandes — le framing `┌─[#N]` reste actif sur `send`,
  les `banner` restent hors de ce cadre pour ne pas doubler le bruit visuel.
- Prévisualiser localement si besoin : `scripts/wsh-step.sh phase 1 6 "titre"`.
- Sorties longues : garde les bannières **en dehors** des pipes (`| head`, etc.).

## Raccourci `step-run`

`step-run "<id>" "<label>" "<commande>" [session]` combine bannière + `send` +
`wait-done --print` (sortie bornée par les marqueurs, voir
`docs/framing-and-transfer.md` → "Lire un résultat sans deviner") en **un seul
appel**, au lieu d'enchaîner 3 appels séparés pour chaque étape. Rend le même
résultat visuel dans Wave ; à utiliser à la place de `banner step` + `send` +
`wait-done` quand l'étape n'a qu'une seule commande.
