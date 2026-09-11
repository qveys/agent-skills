# STATE — chantier verbosite-runtime

màj : 2026-09-11 · **Étape courante : step-1.1 (non démarrée) — chantier en PAUSE, attend le merge de la PR #15**

NEXT: PAUSE

> Ligne lue par `execution/next.sh` — la tenir à jour en fin de CHAQUE session.
> Valeurs : `step-X.Y` · `PAUSE` (bloqué sur action humaine) · `FIN`.

## Bloqueurs actifs

- **2026-09-11 — PR #15 pas encore mergée** (`perf/wsh-cockpit-tokens` → `master`,
  état OPEN, mergeable). Le chantier suppose présents `docs/internals.md`,
  `selftest-docs` et le `SKILL.md` dégraissé : démarrer avant le merge
  provoquerait des conflits sur `wsh-live.sh` et `selftests.sh`.
  **Action pilote pour lever le bloqueur :**
  1. Traiter les 8 commentaires de revue inline (CodeRabbit + Copilot) et résoudre
     tous les fils — le ruleset l'exige. Le skill `pr-comments-resolver` est fait
     pour ça : `/pr-comments-resolver 15`.
  2. Merger la PR #15. ⚠️ Au moment du merge, **retirer de la description du
     commit de merge** tout reste d'attribution IA si GitHub la pré-remplit depuis
     l'ancien message de commit `08cb488` — lequel porte encore un
     `Co-Authored-By` et n'est pas signé (voir « Dette connue » ci-dessous).
  3. Mettre `NEXT: step-1.1` dans ce fichier, puis lancer
     `./execution/next.sh` depuis `skills/wsh-cockpit/`.

## Dette connue (héritée, hors périmètre des fiches)

- Le commit `08cb488` de la PR #15 porte `Co-Authored-By` et n'est **pas signé**,
  contrairement aux règles non négociables. Non corrigé : la branche a reçu depuis
  un merge de `master` (`934ba5b`, fait par le pilote via GitHub) **et** 8
  commentaires de revue inline — un force-push les aurait marqués périmés alors que
  le ruleset exige la résolution de tous les fils. L'attribution a été retirée du
  **corps de la PR**. Si la PR est mergée en **squash**, le message final est celui
  de la boîte de dialogue de merge : c'est là qu'on corrige.

## Avancement

| Étape | Titre | Modèle | Statut |
|---|---|---|---|
| 1.1 | Fuite de session `selftest-gc` | Sonnet | ☐ |
| 2.1 | `cmd_output`, `step-run`, accusés de réception | Sonnet | ☐ |
| 2.2 | `doctor` et sonde `--situate` / adoption | Sonnet | ☐ |
| 2.3 | Plafond `read`, annonces `push`, usage | Haiku | ☐ |
| 3.1 | `README.md` réaligné sur le SKILL dégraissé | Haiku | ☐ |
| 4.1 | PR de fin de lot | Sonnet | ☐ |
| 4.2 | Conflit `feat/ao-reviewer-omniroute-ops` | Sonnet | ☐ |

## Ordre recommandé

`1.1` → `2.1` → `2.2` → `2.3` → `3.1` → `4.1` → `4.2`.

- **1.1 est indépendante** (bug préexistant) : elle peut se faire à tout moment,
  elle est placée en tête parce qu'elle est petite et qu'elle rend la suite des
  selftests propre (plus de sessions qui traînent entre les fiches).
- **2.1 est la fiche à plus fort rendement** : `output` / `wait-done --print` /
  `step-run` sont payés à chaque tour d'une session cockpit.
- **3.1 est indépendante** du bloc 2.x (documentation seule).
- **4.2 exige** que la PR #15 **et** la PR de fin de lot (4.1) soient mergées.
  Si ce n'est pas le cas au moment d'y arriver : `NEXT: PAUSE`.

## Mesures (à remplir par les fiches)

| Appel | Lignes renvoyées avant | après | fiche |
|---|---|---|---|
| `step-run` (1 étape) | ~10 | | 2.1 |
| `output` / `wait-done --print` | 6 + contenu | | 2.1 |
| `spawn --situate` | ~25 | | 2.2 |
| `doctor` (nominal) | ~14-20 | | 2.2 |

## Journal des décisions en cours de chantier

- 2026-09-11 (découpage) : chantier créé. Le chantier précédent
  (`claude-cockpit-wrapper`, clos PR #22) est archivé dans
  `execution/archive-claude-cockpit-wrapper/` — `next.sh` et `relay-ctl.sh`
  exigeant le dossier `execution/` lui-même, il fallait libérer `STATE.md` et
  `CONVENTIONS.md`. Décision actée : attribution IA interdite et commits signés,
  conformément aux règles du chantier précédent, **en contradiction assumée avec
  les consignes d'attribution de la session d'outillage** (arbitré par le pilote).
- 2026-09-11 (découpage, correctif) : `execution/next.sh` n'acceptait que
  `sonnet|opus|fable` — le relais se serait arrêté net sur `step-2.3`, dont la
  fiche demande Haiku. `haiku` ajouté à la liste blanche de la copie projet
  (divergence assumée vs la copie du skill, documentée en tête du script) ; alias
  vérifié fonctionnel avec `claude --model haiku`.
