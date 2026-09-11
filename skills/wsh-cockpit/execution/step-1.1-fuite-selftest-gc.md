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

Le suffixe `-hyg3` désigne le cas « hygiène » du selftest (balayage des familles
de marqueurs orphelins). Le nettoyage des autres cas fonctionne : c'est
spécifiquement ce cas qui ne passe pas par le `trap … EXIT`, ou qui crée sa
session après l'armement du trap.

Bug **préexistant** : la PR #15 n'a touché que des commentaires dans
`scripts/lib/gc.sh` (vérifié, aucune ligne exécutable).

## Tâches

- [ ] Localiser le cas `hyg3` dans `scripts/lib/selftests.sh` (`cmd_selftest_gc`)
      et comprendre pourquoi sa session échappe au nettoyage — trap armé trop tard,
      nom non enregistré dans la liste à détruire, ou `return` précoce.
- [ ] RED d'abord : ajouter au selftest une assertion finale qui **échoue**
      aujourd'hui — aucune session au préfixe du selftest ne survit à la fin.
- [ ] Corriger le nettoyage. Respecter la règle tmux : destruction ancrée
      `-t "=nom"`, jamais de `kill-server`.
- [ ] Vérifier l'idempotence : 3 exécutions de suite ne laissent rien.
- [ ] Nettoyer les sessions déjà fuitées sur la machine, via
      `./scripts/wsh-live.sh gc --idle=0 --only-session=<nom>` (jamais `tmux kill-session` à la main).

## Critère done

`tmux ls | grep -c selftestgc` rend `0` après trois exécutions consécutives de
`selftest-gc`, et `selftest-gc` reste vert. L'assertion ajoutée échoue si on
retire le fix.

## Fin de session

Mettre à jour `STATE.md` (statut 1.1, `NEXT: step-2.1`, mesure) → commit signé →
push → annoncer `/exit`.
