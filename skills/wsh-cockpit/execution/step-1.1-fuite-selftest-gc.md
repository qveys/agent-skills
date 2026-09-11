# Step 1.1 — Fuite de session `selftest-gc`

Phase 1 · indépendante (bug préexistant) · **Modèle : Sonnet**

## Objectif

`selftest-gc` ne doit plus laisser de session tmux derrière lui.

## Contexte minimal

Mesuré le 2026-09-11 : chaque exécution de `scripts/wsh-live.sh selftest-gc`
laisse **une** session `cockpit-selftestgc<pid>-hyg3` vivante. Deux exécutions
consécutives → deux sessions orphelines. Reproduction :

```bash
tmux ls | grep -c selftestgc          # noter
./scripts/wsh-live.sh selftest-gc >/dev/null 2>&1
tmux ls | grep -c selftestgc          # +1 à chaque fois
```

Le suffixe `-hyg3` désigne le cas 20 (« sticky keep ») du selftest. Le trap
d'hygiène `live_selftest_gc_cleanup` est bien armé et appelle `stop "$SESS3"`,
mais la session a reçu un marqueur `keep` (cas 20) : or `stop` relâche une
session `keep` au lieu de la détruire (`teardown_session`). Le trap supprime
ensuite les fichiers marqueurs, mais la session tmux reste vivante.

Bug **préexistant** : la PR #15 n'a touché que des commentaires dans
`scripts/lib/gc.sh` (vérifié, aucune ligne exécutable).

## Tâches

- [ ] Examiner le cas 20 (`SESS3` / `hyg3`) dans `scripts/lib/selftests.sh`
      (`cmd_selftest_gc`) : comprendre l'interaction entre le marqueur sticky `keep`,
      le dispatch `stop` (qui relâche au lieu de détruire tant que `keep` est posé)
      et le trap de nettoyage.
- [ ] RED d'abord : ajouter au selftest une assertion finale qui **échoue**
      aujourd'hui — aucune session au préfixe du selftest ne survit à la fin.
- [ ] Corriger le nettoyage (par exemple retirer le marqueur `keep` avant d'appeler
      `stop`, ou détruire explicitement la session dans le trap). Respecter la règle
      tmux : destruction ancrée `-t "=nom"`, jamais de `kill-server`.
- [ ] Vérifier l'idempotence : 3 exécutions de suite ne laissent rien.
- [ ] Nettoyer les sessions déjà fuitées sur la machine, via
      `./scripts/wsh-live.sh gc --idle=0 --only-session=<nom>` (jamais `tmux kill-session` à la main).
- [ ] Relancer la suite minimale obligatoire : `selftest-docs`, `selftest-sep`,
      `selftest-output`, `selftest-live`, `selftest-guard`.

## Critère done

`tmux ls | grep -c selftestgc` rend `0` après trois exécutions consécutives de
`selftest-gc`, et `selftest-gc` reste vert. L'assertion ajoutée échoue si on
retire le fix. Suite minimale obligatoire verte : `selftest-docs`, `selftest-sep`,
`selftest-output`, `selftest-live`, `selftest-guard`.

## Fin de session

Mettre à jour `STATE.md` (statut 1.1, `NEXT: step-2.1`, mesure) → commit signé →
push → annoncer `/exit`.
