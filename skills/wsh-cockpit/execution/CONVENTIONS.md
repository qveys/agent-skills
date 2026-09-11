# Conventions d'exécution — chantier verbosite-runtime

Source maîtresse : l'audit de verbosité consigné dans la PR #15 (section « À
savoir ») et rappelé en contexte dans chaque fiche. Les fiches `step-X.Y` n'en
copient que le strict nécessaire.

Chantier précédent (clos) : `execution/archive-claude-cockpit-wrapper/`.

## Rituel de session (obligatoire)

1. Charger UNIQUEMENT, dans cet ordre : `CONVENTIONS.md` (ce fichier) + `STATE.md`
   + la fiche `step-X.Y` courante. Rien d'autre — surtout pas `docs/internals.md`
   ni l'archive du chantier précédent.
2. **Contrôle modèle** (filet — le relais lance normalement le bon) : comparer le
   modèle actif à la ligne « Modèle : » de la fiche ; mismatch → s'arrêter et
   demander `/model <bon modèle>` (l'agent ne peut pas le faire lui-même).
3. Exécuter la fiche. Ne pas déborder sur l'étape suivante, même s'il « ne reste
   qu'un petit truc ».
4. Fin de session : mettre à jour `STATE.md` (statut, **ligne `NEXT:`**, décisions,
   bloqueurs, mesures avant/après), commit signé, push, puis **annoncer de taper
   `/exit`** (hors relais : `/clear`).

## Relais entre sessions — `execution/next.sh`

Boucle : lit `NEXT:` dans STATE.md → extrait le modèle de la fiche → `claude
--model <modèle>` → au `/exit` du pilote, enchaîne. S'arrête sur `PAUSE`, `FIN`,
fiche introuvable, ou Ctrl+C (5 s de compte à rebours avant chaque lancement).

Filet anti-session-morte : une session qui meurt sans mettre `NEXT:` à jour fait
rejouer la **même** fiche. Les fiches doivent donc rester **rejouables** — pas
d'effet de bord non idempotent sans garde.

Lancement : `./execution/next.sh` depuis `skills/wsh-cockpit/`, idéalement dans un
cockpit visible (skill wsh-cockpit : `spawn` + `send`, bannières obligatoires).

## Règles non négociables

- **Commits signés** (`git commit -S`), messages **en français**, **AUCUNE
  attribution IA** (pas de `Co-Authored-By`, pas de « Generated with »). Jamais
  `--no-gpg-sign`.
  ⚠️ Signature via l'agent SSH 1Password : **l'app 1Password doit être ouverte et
  déverrouillée**, sinon `failed to write commit object`. Si échec : `NEXT: PAUSE`
  + bloqueur dans STATE.md.
- **Branche de travail** : `perf/wsh-cockpit-verbosite`. Push en fin de session.
  **Jamais de push direct sur `master`** : PR exigée (signatures, revue Copilot +
  CodeRabbit, résolution de **tous** les fils de revue). La PR de fin de lot est
  une fiche dédiée.
- **Ne jamais toucher au rendu DANS le pane.** L'utilisateur regarde ce pane :
  règles `─`, couleurs, bannières, lignes vides y restent **intactes**. Tout ce
  chantier ne filtre que ce que les scripts **renvoient à l'agent**.
- **Couper du chatter, jamais de la donnée.** Aucune information nécessaire à une
  décision de l'agent ne disparaît. Dans le doute, garder.
- **bash 3.2 (macOS)** : pas de tableaux associatifs, `set -euo pipefail`,
  `${TMUX:-}`/`${TMUX_PANE:-}`, idiome `${ARR[@]+"${ARR[@]}"}` pour les tableaux
  potentiellement vides.
- **tmux** : JAMAIS de `kill-session` sans cible explicite ancrée `-t "=nom"`,
  JAMAIS de `kill-server`. Sessions de test à préfixe dédié, nettoyées par
  `trap … EXIT`.
- **« Aucun effet Wave » dans les selftests** (précédent posé par `selftest-adopt`,
  suivi par `selftest-wrapper`) : un selftest ne déclenche JAMAIS un vrai bloc Wave
  ni un vrai `claude` — on simule.
- **TDD RED-first** pour tout changement de sortie : montrer l'assertion rouge
  avant le fix, le dire dans STATE.md.
- **Ne pas affaiblir les gardes des lots 1-2** (`session_is_own`,
  `deny_own_session`, `looks_like_session`, ancrage `=`).
- **Selftests verts en fin de chaque fiche touchant `scripts/`** : au minimum
  `selftest-docs`, `selftest-sep`, `selftest-output`, `selftest-live`,
  `selftest-guard`. `selftest-adopt` est **instable de façon connue** (course au
  rendu du pane dans `adopt_pane_ready`) : un échec isolé là n'est pas une
  régression — le consigner, ne pas le chasser.

## Modèle par session

Pas d'opusplan : le blueprint a déjà été payé au découpage, chaque fiche EST le plan.

| Cas | Modèle |
|---|---|
| Défaut (implémentation au contrat clair) | Sonnet |
| Mécanique pur (renommage, renvoi, mesure) | Haiku |
| Fiche de jugement (arbitrage qui redécoupe) | Opus |
| Blocage réel en session | Consigner dans STATE.md, escalader, redescendre |

## Décisions actées (ne PAS re-questionner)

1. **Base = `master` après merge de la PR #15.** Le chantier suppose présents
   `docs/internals.md`, `selftest-docs` et le `SKILL.md` dégraissé.
2. Le périmètre est la **verbosité runtime** : ce que les scripts renvoient à
   l'agent, pas ce que voit l'utilisateur dans le pane (cf. règles ci-dessus).
3. `output` garde son contrat de segment borné par marqueurs. Si le footer
   `└─[#N] exit <code>` est retiré de la sortie **agent**, le code de sortie doit
   rester disponible autrement (ligne `done: #[N] exit N` de `wait-done`, et rc du
   script) — jamais perdu.
4. Toute coupe se mesure : **nombre de lignes renvoyées avant/après**, consigné
   dans STATE.md. Une coupe non mesurée n'est pas terminée.
5. Les plafonds de `selftest-docs` (budget tokens de la doc) ne se relèvent pas
   pour faire passer une fiche : c'est un cliquet délibéré.
6. Artefacts volumineux de chantier dans `execution/`, pas dans `docs/` (réservé à
   ce qui sert le skill livré). Reprise du chantier précédent.
7. La fuite `selftest-gc` (session `cockpit-*-hyg3` par exécution) est un bug
   **préexistant**, pas une régression de la PR #15 — step-1.1 la traite.
