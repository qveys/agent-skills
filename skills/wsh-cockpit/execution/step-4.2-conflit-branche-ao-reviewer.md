# Step 4.2 — Conflit `feat/ao-reviewer-omniroute-ops`

Phase 4 · après 4.1 · exige deux merges préalables · **Modèle : Sonnet**

## Objectif

Réconcilier la branche `feat/ao-reviewer-omniroute-ops` avec le `SKILL.md`
dégraissé, sans perdre la règle qu'elle apportait.

## Contexte minimal

**Prérequis : la PR #15 ET la PR du lot (fiche 4.1) doivent être mergées dans
`master`.** Si ce n'est pas le cas, mettre `NEXT: PAUSE` et s'arrêter — c'est une
action du pilote.

Le commit `318eb6e` (branche `feat/ao-reviewer-omniroute-ops`, non mergée) ajoutait
2 lignes à l'ancien `SKILL.md`, juste avant le paragraphe sur le wrapper
`claude-cockpit` :

> Si l'utilisateur nomme un cockpit (exemple : `cockpit-omniroute-171628`), adopte
> et utilise cette session. N'en crée pas une seconde.

La PR #15 a réécrit `SKILL.md` de fond en comble : le merge **conflictera** sur ce
fichier. La règle n'est pas perdue — elle a été reprise dans le bloc « Règles
impératives » du nouveau `SKILL.md` sous la forme :

> **Cockpit nommé par l'utilisateur** (ou listé dans `WSH_COCKPIT_ADOPT`) :
> adopte-le, n'en crée pas une seconde.

La résolution attendue est donc : **garder la version réécrite**, écarter les 2
lignes de `318eb6e` comme déjà intégrées. Ne pas les réinsérer : cela
réintroduirait un doublon que `selftest-docs` (cas `no-dup`) est là pour empêcher.

Le skill `conflict-resolve` est disponible si le conflit dépasse ce seul fichier —
`318eb6e` touche aussi d'autres skills, qui n'ont rien à voir avec ce chantier et
ne doivent **pas** être modifiés ici.

## Tâches

- [ ] Vérifier les prérequis (`gh pr view 15`, et la PR du lot). Sinon : `PAUSE`.
- [ ] Dans un **worktree dédié** (jamais en basculant la branche du worktree
      principal), merger `master` dans `feat/ao-reviewer-omniroute-ops`.
- [ ] Résoudre le conflit sur `SKILL.md` en gardant la version `master`
      (dégraissée), sans réinsérer les 2 lignes de `318eb6e`.
- [ ] Vérifier que la règle survit exactement une fois : la chercher dans
      `SKILL.md`, et lancer `selftest-docs` (les cas `rules` et `no-dup`).
- [ ] Ne toucher à aucun autre skill de la branche.
- [ ] Pousser la branche. Si elle a une PR ouverte, y expliquer la résolution en
      un commentaire.

## Critère done

`feat/ao-reviewer-omniroute-ops` contient `master` sans conflit, `selftest-docs`
vert, et la règle « cockpit nommé par l'utilisateur » présente **une seule fois**
dans `SKILL.md`. Aucun autre skill modifié par cette fiche.

## Fin de session

Mettre à jour `STATE.md` (statut 4.2, `NEXT: FIN`) → commit signé → push →
annoncer `/exit`.
