---
name: cron-script-recovery
description: "Use when a cron script fails on a missing path or binary."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [cron, shell, script-repair, path-resolution, binary-locator]
---

# Réparation de scripts CRON avec chemin binaire manquant

## When to Use

- A cron job exits with "No such file or directory" on an absolute binary path (exit 127). The script hardcodes a path that worked on a previous machine but the binary is gone.
- A cron job exits 1 with `cd: <chemin>: No such file or directory` (répertoire/montage déplacé) — voir la variante ci-dessous.

Pour **créer** un job Hermes, suivre `hermes-cron-jobs`. Cette skill répare seulement un wrapper déjà enregistré.

## Root cause signature

```
Script exited with code 127
stderr: /chemin/absolu/vers/binaire: No such file or directory
```

## Variante : répertoire déplacé (montage changé de place)

Signature différente du binaire manquant — **exit 1, pas 127**, et `cd:` dans le stderr :

```
Script exited with code 1
stderr: $HERMES_HOME/scripts/cron-x.sh: line 3: cd: /chemin/du/projet: No such file or directory
```

C'est un répertoire codé en dur qui n'existe plus (montage déplacé, conteneur recréé), pas un binaire absent.

1. Confirmer le montage réel avant d'écrire : `mount | grep <mot>`, `df -h <chemin>`, `ls -ld <chemin>`. Ne jamais deviner le nouveau chemin.
2. **Corriger les deux emplois du chemin** : le `cd` du wrapper ET le `workdir` du job dans `$HERMES_HOME/cron/jobs.json`. Éditer `jobs.json` en Python (`json.load` / `json.dump`, pas `sed` — guillemets échappés) pour préserver la structure.
3. **Grepper tous les wrappers pour l'ancien chemin** : `grep -rn "<ancien-chemin>" "$HERMES_HOME/scripts/"`. Les jobs hebdo/mensuels partagent le même chemin codé en dur mais n'ont pas encore échoué — les réparer dans la même passe, sinon la panne revient au prochain tick lent.
4. Prouver le fix en exécutant le wrapper depuis le shell (le vrai chemin cron), pas seulement en relisant le diff.
5. Rafraîchir `last_status: error` dans `jobs.json` après vérification : l'erreur enregistrée survit au fix et fait ré-alerter tout watchdog qui hache les clés `job-error:`.

## Procedure

### 0. Read-before-write

Avant toute modification : `cat` le script, identifier la/les ligne(s) fautives, confirmer l'existence du binaire. Ne jamais écrire sans avoir lu.

### 1. Localiser le binaire réel

```bash
which <binaire>                    # préférer which pour le PATH résolu
# ou si which retourne vide
find / -name "<binaire>" -type f 2>/dev/null | head -5
```

Ne pas deviner. Confirmer l'existence avant de modifier.

### 2. Lire le script CRON

```bash
cat /chemin/vers/script.sh
```

Identifier les lignes `exec` et vérifier :
- **Un seul `exec` par script** (le dernier). Tout ce qui est après `exec` ne tourne jamais.
- **Pas de `command -grep` ou autre commande inexistante** — une commande inconnue dans un pipe ou une condition tue le script avec `set -euo pipefail` (exit 127).
- **Chemins absolus** pour les chemins de fichiers (vault, workspace, etc.) — un chemin relatif dans un CRON tourne depuis le `workdir` du cron, pas depuis le repo.

### 3. Corriger le chemin binaire

Remplacer par le binaire dans PATH ou le chemin réel confirmé.

Si dans PATH (`which` a retourné un chemin) :

```bash
sed -i 's|"/chemin/absolu/vers/binaire"|<binaire>|g' /chemin/vers/script.sh
```

Si le script doit tourner dans plusieurs conteneurs ou sous plusieurs utilisateurs, utiliser un petit résolveur au début du wrapper au lieu d'un chemin unique : tester les chemins connus puis `command -v <binaire>`, stocker le résultat dans `<BIN>`, échouer avec `exit 127` si vide.

Si hors PATH, utiliser le chemin absolu confirmé.

**N'utiliser que `sed -i` ou `patch` — pas d'écriture manuelle ligne par ligne.**

### 4. Corriger les commandes inexistantes

Si le script contient une commande inexistante (ex. `command -grep` au lieu de `command grep` ou `grep`) :

```bash
sed -i 's|command -grep|grep|g' /chemin/vers/script.sh
```

Identifier et corriger chaque commande invalide, une par une, en lisant le script après chaque correction.

### 5. Vérifier la syntaxe

```bash
bash -n /chemin/vers/script.sh && echo "syntaxe OK" || echo "syntaxe ERRONEE"
```

Tuer la réparation si la syntaxe est erronée.

### 6. Dry-run (si sécurisé)

```bash
timeout 10 bash /chemin/vers/script.sh || true
```

Vérifier le exit code et le stdout/stderr. Signaler que le prochain tick CRON validera.

### 7. Confirmer la résolution

```bash
which <binaire> && <binaire> --version 2>&1 || true
```

Inclure la version dans le rapport.

## Pitfalls

- **Ne pas éditer sans confirmer que le binaire existe.** Un chemin faux écrit produit un script cassé différent.
- **Ne pas utiliser un chemin depuis `find` sans vérifier l'exécutable.** Un fichier sans +x produit un comportement inattendu.
- **Ne pas faire un `sed` global aveugle sur plusieurs scripts.** Chaque script CRON a son propre contexte ; vérifier chaque occurrence.
- **N'utiliser `exec` que pour la dernière commande du wrapper.** `exec` remplace le shell ; tout contrôle ou check placé après ne tournera jamais.
- **Si `set -euo pipefail`, un seul commande échouant tue tout.** Dans le dry-run, utiliser `|| true`.
- **Un `cd:` en échec dans le stderr (exit 1) n'est pas le cas binaire (exit 127)** : traiter comme répertoire déplacé — localiser le montage réel, pas le binaire.
- **Un dry-run `timeout 10` tronque un script qui scanne un grand vault** : il sort prématurément sans conclusion. Lancer ces scripts en background avec notify et attendre la complétion avant de valider.
- **Un chemin relatif dans un script CRON tourne depuis le cwd du cron, pas depuis le repo.** Vérifier que le `cd` pointe vers le bon répertoire.
