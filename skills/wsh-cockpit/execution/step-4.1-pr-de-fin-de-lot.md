# Step 4.1 — PR de fin de lot

Phase 4 · après 3.1 · clôt la partie code du chantier · **Modèle : Sonnet**

## Objectif

Ouvrir la PR du chantier verbosité runtime vers `master`, revue incluse.

## Contexte minimal

Branche : `perf/wsh-cockpit-verbosite`. Cible : `master`. Ruleset : commits signés,
revue Copilot + CodeRabbit, **résolution de tous les fils de revue** avant merge.

Règles de message : **français, aucune attribution IA** (ni `Co-Authored-By`, ni
« Generated with ») — ni dans les commits, ni dans le corps de la PR. C'est
précisément ce qui a été raté sur la PR #15 (voir « Dette connue » dans STATE.md) :
ne pas répéter l'erreur.

La PR doit porter le **tableau de mesures avant/après** consolidé depuis STATE.md :
c'est le livrable chiffré du chantier.

## Tâches

- [ ] Relire le diff complet du chantier (`git diff master...HEAD`) et vérifier
      qu'aucune coupe n'a emporté de la donnée (décision actée n°4 de
      CONVENTIONS.md : couper du chatter, jamais de la donnée).
- [ ] Lancer la suite complète, en noms **complets** de sous-commande
      (`wsh-live.sh` rejette toute abréviation du type `-sep` : message d'usage et
      code 2) : `selftest-docs`, `selftest-sep`, `selftest-output`,
      `selftest-live`, `selftest-gc`, `selftest-cache`, `selftest-claim`,
      `selftest-oneshot-ssh`, `selftest-transfer`, `selftest-guard`,
      `selftest-tab`, `selftest-wrapper`, `selftest-attach`, `selftest-adopt`.
      Consigner le résultat.
      `selftest-adopt` instable connu → le dire, ne pas le chasser.
- [ ] Vérifier qu'aucune session `cockpit-*` ne traîne après la suite (c'est
      l'objet de la fiche 1.1).
- [ ] Ouvrir la PR : titre en français, corps avec le tableau de mesures, la liste
      des coupes, et ce qui a été **délibérément laissé** de côté.
- [ ] Traiter les commentaires de revue et résoudre tous les fils
      (`/pr-comments-resolver <n>`).

## Critère done

PR ouverte, CI/revues passées, tous les fils résolus, **prête à merger** — le merge
lui-même est une action du pilote, pas de l'agent.

## Fin de session

Mettre à jour `STATE.md` (statut 4.1, numéro de PR, `NEXT: PAUSE` en attendant le
merge du pilote) → commit signé → push → annoncer `/exit`.
