# Step 3.1 — `README.md` réaligné sur le SKILL dégraissé

Phase 3 · indépendante du bloc 2.x · **Modèle : Haiku**

## Objectif

`README.md` cesse d'être une troisième copie divergente de la liste des
sous-commandes.

## Contexte minimal

La PR #15 a réécrit `SKILL.md` (298 → 122 lignes) et redistribué les docs, mais a
laissé `README.md` (2 674 tokens) intact — décision assumée à l'époque : il n'est
jamais chargé par l'agent, donc le dégraisser ne gagne aucun token. Il est
désormais **partiellement périmé** : il duplique la liste des 21 sous-commandes et
décrit une organisation de docs qui a changé (`docs/internals.md` est nouveau,
`docs/gotchas.md` a été vidé de sa forensique).

Le gain ici n'est pas en tokens, il est en **maintenance** : une seule source de
vérité pour les signatures.

`selftest-docs` vérifie déjà que chaque sous-commande de `wsh-live.sh` apparaît
dans `SKILL.md`. Il ne vérifie rien sur `README.md`.

## Tâches

- [ ] Lire `README.md` et `SKILL.md`, relever les divergences : signatures
      absentes, flags périmés, arborescence de docs fausse.
- [ ] Remplacer la liste dupliquée des sous-commandes par un **renvoi** vers
      `SKILL.md` — ne pas la recopier.
- [ ] Mettre à jour la description de `docs/` : les 5 docs opérationnels + la
      mention que `docs/internals.md` est destiné au mainteneur et volontairement
      non référencé depuis `SKILL.md`.
- [ ] Mentionner `selftest-docs` dans la section des selftests, comme gate
      pré-commit de la documentation.
- [ ] Ne PAS faire entrer `README.md` sous un plafond de `selftest-docs` : il n'est
      pas chargé par l'agent, un plafond n'y aurait pas de sens.

## Critère done

Aucune signature de sous-commande n'est écrite à la fois dans `README.md` et
`SKILL.md`. Un lecteur de `README.md` trouve la bonne arborescence de docs.
`selftest-docs` reste vert.

## Fin de session

Mettre à jour `STATE.md` (statut 3.1, `NEXT: step-4.1`) → commit signé → push →
annoncer `/exit`.
