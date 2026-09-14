# Step 2.3 — Plafond `read`, annonces `push`, usage

Phase 2 · après 2.2 · mécanique · **Modèle : Haiku**

## Objectif

Trois coupes mécaniques sans arbitrage : borner `read`, fusionner les annonces de
transfert, raccourcir la ligne d'usage.

## Contexte minimal

⚠️ **Numéros de ligne d'avant la PR #15 — localise par contenu.**

1. **`read` n'est pas plafonné.** `WSH_READ_MAX` (défaut 120) est appliqué
   uniquement dans `cmd_output`. Le bras `read)` de `wsh-live.sh` valide que
   `LINES` est un entier puis passe directement à `mux_capture` : un `read 5000`
   rend 5000 lignes dans le contexte de l'agent. C'est le seul chemin de sortie
   sans garde-fou.
2. **`wsh-push.sh` annonce trois fois la même chose** : une ligne
   `push: … (N bytes) -> …` (ou `pull: …`), une ligne `transfer: using <METHOD>
   for <DIR>` sur stderr, et une ligne `ok via <METHOD>: …`.
3. **La ligne d'usage** de `wsh-live.sh` énumère 28 sous-commandes dont 14
   `selftest-*` qu'un agent n'appellera jamais (~120 tokens à chaque faute de
   frappe). Les `${1:?usage: …}` de `step-run` répètent trois fois la même
   signature.

## Tâches

- [ ] RED d'abord : ajouter des assertions dans `selftest-live` et
      `selftest-transfer` qui échouent aujourd'hui :
      - `read 5000` borné à `WSH_READ_MAX` avec marqueur de troncature.
      - Contournement explicite (ex. `--full` ou variable dédiée) rendant l'intégralité.
      - Sortie de `wsh-push.sh` condensée en une seule ligne finale.
      - Ligne d'usage de `wsh-live.sh` restreinte à ≤ 2 lignes.
- [ ] Appliquer `WSH_READ_MAX` au bras `read)` : même traitement que `cmd_output`
      (tête + note de troncature + queue), avec un moyen explicite de passer outre.
- [ ] Fusionner les trois annonces de `wsh-push.sh` en **une** ligne finale qui
      porte le sens, la méthode et la taille.
- [ ] Usage : regrouper les `selftest-*` en un seul `selftest-<nom>` avec renvoi,
      plutôt que les énumérer. Dédupliquer les `usage:` de `step-run`.
- [ ] Relancer les selftests : `selftest-transfer`, `selftest-live`,
      `selftest-docs`, ainsi que la suite minimale obligatoire (`selftest-sep`,
      `selftest-output`, `selftest-guard`).

## Critère done

`read <session> 5000` ne renvoie pas 5000 lignes. Un `push` réussi renvoie une
seule ligne. La ligne d'usage tient en ≤ 2 lignes. `selftest-transfer`,
`selftest-live`, `selftest-docs`, `selftest-sep`, `selftest-output`,
`selftest-guard` verts — et `selftest-docs` passe toujours son cas `coverage`
(la liste des sous-commandes de `SKILL.md` reste exhaustive).

## Fin de session

Mettre à jour `STATE.md` (statut 2.3, `NEXT: step-3.1`) → commit signé → push →
annoncer `/exit`.
