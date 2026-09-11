# Step 2.2 — `doctor` et sonde `--situate` / adoption

Phase 2 · après 2.1 · **Modèle : Sonnet**

## Objectif

`doctor` ne renvoie plus que ce qui est actionnable ; la sonde de `--situate` et
d'adoption ne renvoie plus 20 lignes brutes pour 3 valeurs.

## Contexte minimal

⚠️ **Numéros de ligne d'avant la PR #15 — localise par contenu.**

1. **`doctor`** (`scripts/lib/doctor.sh`) imprime une ligne par check via
   `doc_line`, soit ~14-18 lignes de `ok …` sur le cas nominal, alors que seuls les
   `warn`/`fail` sont actionnables. Il y a ~36 sites d'appel de `doc_line`. Le
   verdict final existe déjà (`doctor: ok`).
2. **Sonde `--situate` / adoption** : `situate_session` (`wsh-live.sh`) et
   `adopt_print_probe` (`scripts/lib/session.sh`) font un `read 20` complet et en
   **réimpriment les 20 lignes** — framing et blob du helper inline compris — pour
   n'extraire que 3 valeurs (`WSH_SITUATE_HOST=`, `pwd`, `whoami`). ~90 % de
   déchet. Mesuré : un `spawn --situate` renvoie ~25 lignes pour 4 informations
   utiles.

Contrainte forte : la sortie brute de la sonde reste nécessaire **en interne**
(détection du hop, décision d'appeler `remote-init`). On ne change que ce qui est
**imprimé**, pas ce qui est calculé.

## Tâches

- [ ] RED d'abord : assertions sur le nombre de lignes renvoyées par `doctor` en
      non-TTY (cas nominal) et par `spawn --situate`, qui échouent aujourd'hui.
- [ ] `doc_line` : en non-TTY, ne pas imprimer les `ok` — les compter. Le verdict
      final devient `doctor: ok (N checks)` / liste des seuls non-`ok` puis
      `doctor: N check(s) en échec`. En TTY, garder la sortie détaillée (un humain
      la lit).
- [ ] Sonde : condenser l'impression en une ligne du type
      `situate: host=<h> pwd=<p> user=<u>`. Garder la sortie complète disponible en
      interne pour la détection de hop.
- [ ] Idem pour `adopt_print_probe` : la sonde d'adoption doit rester **visible**
      (c'est une exigence : jamais d'adoption silencieuse) mais en une ligne, pas
      vingt.
- [ ] Museler les annonces internes de `send` et `wait-done` dans `situate_session`
      (via `>/dev/null` ou silence non-TTY, comme fait pour `step-run` dans 2.1)
      afin de ne pas gonfler la sortie de `spawn` avec les accusés intermédiaires.
- [ ] Relancer les selftests pertinents ainsi que la suite minimale obligatoire
      (`selftest-sep`, `selftest-output`, `selftest-guard`).
- [ ] Mesurer avant/après, reporter dans STATE.md.

## Critère done

`doctor` en non-TTY sur une machine saine renvoie ≤ 3 lignes ; `spawn --situate`
renvoie ≤ 4 lignes en réutilisation et ≤ 5 lignes en création fraîche, incluant les
3 valeurs de la sonde condensée ; l'adoption reste visiblement sondée. `selftest-adopt`
(instable connu — consigner, pas chasser), `selftest-live`, `selftest-docs`,
`selftest-sep`, `selftest-output`, `selftest-guard` verts.

## Fin de session

Mettre à jour `STATE.md` (statut 2.2, `NEXT: step-2.3`, mesures) → commit signé →
push → annoncer `/exit`.
