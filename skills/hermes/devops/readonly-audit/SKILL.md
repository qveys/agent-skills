---
name: readonly-audit
description: "Use when « ne modifie rien » : audit en lecture seule."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [audit, readonly, verification, preuves, hermes, kanban]
    related_skills: [kanban-orchestration, hermes-cron-jobs]
---

# Audits en lecture seule (tableau de preuves)

Charger ceci quand la demande est de **vérifier sans rien modifier** (« Ne modifie rien », « rends-moi un tableau », contrôle d'état d'un déploiement Hermes/Kanban/vault). Le livrable est un rapport de preuves vérifiables, pas un correctif ni une opinion.

## When to Use

- L'utilisateur demande une vérification avec « Ne modifie rien » : audit d'état du déploiement Hermes/Kanban, des dépôts ou du vault.
- Une affirmation technique doit être confirmée ou réfutée avant une décision (fichier existant ?, valeur effective d'une config, état d'un service).
- Un rapport de conformité est attendu au format tableau `contrôle | résultat | preuve`, ÉCHEC marqués, sans réparation.

## Contrat (règles toujours actives)

1. **Aucune écriture.** Seules les commandes de lecture : `list` / `show` / `status` / `read` / `stat`, `git status|log|diff|check-ignore`, comptages. Les variantes de contrôle (`--check`, `--dry-run`) sont permises quand elles annoncent elles-mêmes « aucune écriture ». Jamais `switch`, `create`, `add`, `commit`, régénération de projection, ni « juste un petit run pour voir ».
2. **Marquer, pas corriger.** Un contrôle raté se marque ÉCHEC avec sa preuve ; la commande de correction se prépare en texte, ne s'exécute pas. Ne pas remplacer un chemin défaillant par un détour non demandé, ne pas « réparer en passant » (permissions, ownership, état Git).
3. **Format imposé** : tableau `contrôle | résultat | preuve (commande)`, une ligne par contrôle, dans l'ordre de la demande (numéros et libellés repris tels quels). La preuve est la commande **exactement** lancée ; chemin absolu quand le binaire n'est pas sur le PATH. Statuts : ✅ réussi, ⚠️ partiel ou conforme avec réserve (préciser la réserve), ÉCHEC. Puis : Notes courtes, puis Pistes (piste | gain | coût | réversibilité, 1 à 3, triées gain/coût).
4. **Rien d'inventé.** Ne rapporter que l'observé. Distinguer « non défini dans la config » de « valeur par défaut appliquée » ; toute affirmation sur du code cite fichier + ligne.
5. **Ne pas confondre avec une demande de correction.** « Ne modifie rien » se termine par un rapport et des pistes. Si la réparation est ensuite demandée, elle s'applique et se vérifie par un test réel, pas par une note.

## Méthode

- **Batcher les lectures indépendantes** en une salve (git + stat + greps + comptages) ; sérialiser seulement quand une commande dépend de la précédente.
- **Résoudre les chemins avant de conclure** : `readlink -f` + `ls -ld`. Un chemin peut être un montage séparé, un dépôt distinct ou un simple sous-dossier — la conclusion change.
- **Légitimité d'un dossier sous `$HERMES_HOME`** : ne jamais conclure sur le nom. Prouver par deux sources — le code (`grep -rn '"<nom>"' /opt/hermes --include='*.py'`, hors `node_modules`) et la doc officielle. Un dossier est légitime dès qu'un module le référence (`installs`→`pm/environments.py`, `lsp`→`agent/lsp/install.py`, `home`/`workspace`→`hermes_cli/profiles.py`). Un dossier sous `profiles/` sans aucun fichier d'identité (`config.yaml`, `.env`, `SOUL.md`, `profile.yaml`, `auth.json`, `state.db`) et absent de `hermes profile list` est un résidu de profil supprimé.
- **« Valeur effective » d'une clé de config** : config.yaml → défauts du code (`/opt/hermes/hermes_cli/config_defaults.py`) → preuve runtime dans les logs. Absent de config.yaml ≠ pas de valeur : chercher le défaut, puis la valeur appliquée (exemple kanban : skill `kanban-orchestration`).
- **Un fichier demandé introuvable** : le déclarer ÉCHEC après recherche par nom ET par contenu sur tout le périmètre. « Pas au chemin indiqué » ne suffit pas pour dire « n'existe pas ».
- **Un warning n'est pas un fait** : croiser tout signal d'état (scheduler, heartbeat, conformité) avec les traces réelles (dernières exécutions, artefacts) avant de conclure dans un sens ou l'autre.
- Les écarts se qualifient : ⚠️ pour conforme-avec-réserve (seuil proche, marge faible, écart cosmétique) — ne pas simplifier en ✅ ni dramatiser en ÉCHEC.

## Points d'ancrage (cette instance : déploiement Hermes + projet brain ; chemins vérifiés présents, à adapter ailleurs)

- CLI `hermes` hors PATH des shells d'outils (install docker) : `/opt/hermes/libexec/hermes` ou `/opt/hermes/bin/hermes` (`--version` pour confirmer).
- `qmd` hors PATH : `/workspace/.qmd/npm/bin/qmd`. Index : `/workspace/.qmd/cache/qmd/index.sqlite`, collection `second-cerveau`. `qmd status` = état de l'index ; `qmd search "<query>" -c second-cerveau` = BM25 sans LLM, test rapide.
- **Invoquer qmd sans ses wrappers** : `bin/qmd` et `bin/qmd-cpu` codent `/workspace` en dur (`XDG_CACHE_HOME`, `QMD_CONFIG_DIR`, `QMD_REAL`), racine absente du conteneur → `not found`. Appeler le binaire réel avec les chemins résolus : `XDG_CACHE_HOME=/workspace/.qmd/cache QMD_CONFIG_DIR=/workspace/.qmd/config LD_LIBRARY_PATH=/workspace/.qmd/libshim QMD_FORCE_CPU=1 /workspace/.qmd/npm/bin/qmd --help`. Le shim `libshim/libc.so` reste requis (les `.so` préconstruits déclarent `DT_NEEDED libc.so`).
- Kanban : racine partagée `<KANBAN_ROOT>` (`$HERMES_KANBAN_HOME`, sinon `/opt/data` — pas le home d'un profil) ; board courant dans `<KANBAN_ROOT>/kanban/current` ; stockage par board `<KANBAN_ROOT>/kanban/boards/<slug>/` (board `default` : `<KANBAN_ROOT>/kanban.db`) ; `hermes kanban --board <slug> …` opère ailleurs **sans** changer le courant ; `boards switch` écrit — interdit en audit.
- Dépôts : `/workspace/brain` (remote Gitea `brain.git`) et son vault `/workspace/brain/Second-Cerveau` (dépôt **séparé**, remote `second-cerveau.git`). Carte complète des montages et de la propriété des dossiers : `references/deployment-layout.md`. Nature d'un dossier : `<dir>/.git` **dossier** = dépôt autonome ; `.git` **fichier** (`gitdir: …`) = sous-module ou worktree. Preuve d'exclusion : `git check-ignore -v <chemin>` (exit 0 + la règle). Un worktree ne matérialise que les fichiers suivis : un dossier ignoré est absent des worktrees — le vérifier par glob (`wt/*/<chemin>`), jamais par supposition.
- Propreté ≠ alignement : `git status --porcelain | wc -l` prouve l'absence de changements locaux, mais l'alignement se prouve **sans réseau** par `git rev-list --left-right --count <branche>...origin/<branche>` (`0 0` = aligné, sur les refs connues). Pour savoir quel commit a absorbé un lot trouvé sale au contrôle précédent : `git log -2 --format='%h %cI %s'` et `git reflog --date=iso`.
- Cron : `hermes cron list` (CLI) et `$HERMES_HOME/cron/jobs.json` donnent par job : schedule, workdir, script, `last_run_at`, `last_status`, `next_run_at`. Wrappers dans `$HERMES_HOME/scripts/`, copies versionnées possibles côté dépôt.
- Comptages exacts : `find <dir> -name "*.md" -type f | wc -l` (un index tiers, type qmd, peut être décalé du disque — citer les deux si pertinent).

## Pièges

- **Ne pas « vérifier » avec un outil qui écrit.** Le contrôle d'une projection est `node scripts/crew-check.mjs --check` (il imprime « Aucune écriture » : citer ce point comme preuve), jamais `crew-project.mjs`.
- **Ne pas changer l'état qu'on inspecte** : cibler (`--board`, filtres) plutôt que basculer (`switch`, `checkout`).
- **Ne pas conclure « en panne » devant un warning**, ni « conforme » devant un silence : le tableau cite des commandes, pas des impressions.
- **Un dossier nommé `cache` n'est pas une preuve de régénérabilité.** Lister son contenu avant d'annoncer un gain : des poids de modèles (`.gguf`, `.safetensors`, `.onnx`) sont des artefacts téléchargés, pas un cache — les purger impose un re-téléchargement. Distinguer l'index (régénérable, l'outil le recrée à la première invocation) des poids (non). Ne chiffrer un gain qu'après inspection ligne par ligne, jamais après lecture du seul `du`.
- **Un chemin codé en dur dans un wrapper est une bombe à retardement de montage.** Avant de proposer de déplacer un point de montage, recenser les occurrences (`grep -rn '<ancienne-racine>/'` sur configs, scripts, skills, cron) : chaque chemin en dur change de sens ou casse. Livrer l'inventaire fichier par fichier, non appliqué.
- Un échec qui résiste se rapporte tel quel, avec la commande de correction préparée en texte : la discipline lecture seule prime sur l'envie de diagnostiquer en modifiant.
