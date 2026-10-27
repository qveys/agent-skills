---
name: kanban-orchestration
description: "Use when routing cards to Kanban workers."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [kanban, dispatch, orchestration, profiles, workers]
    related_skills: [hermes-plugin-env-config, kanban-worker-dispatch, kanban-batch-recovery, kanban-tasks]
---

# Orchestration Kanban : router du travail vers un worker

## When to Use

- Confier un lot de travail à un worker dispatché, créer ou router des cartes Kanban, planifier une chaîne multi-profils.
- Diagnostiquer une carte qui ne démarre pas, qui s'auto-bloque ou dont le statut ne reflète pas le disque.
- Piloter les boards (`--board`, `boards list`), régler la concurrence, archiver après dispatch.

**Convention de chemins.** `KANBAN_ROOT` = `$HERMES_KANBAN_HOME` s'il est défini, sinon la racine Hermes partagée (`/opt/data` sur cette instance). Le board est **commun à tous les profils** : ne pas le chercher sous le `HERMES_HOME` d'un profil (`/opt/data/profiles/<nom>`), qui n'a ni `kanban.db` ni `kanban/` (vérifié dans `hermes_cli/kanban_db.py::kanban_home`). Board `default` : `<KANBAN_ROOT>/kanban.db` et `<KANBAN_ROOT>/kanban/logs/` ; autre board : `<KANBAN_ROOT>/kanban/boards/<slug>/{kanban.db,logs/,workspaces/}`. Les noms de profils (`lecteur`, `reviseur`, `stratege`…) et les chemins `trading/…` des exemples illustrent une campagne de corpus ; adapter à ses propres profils.

Charger ceci pour confier un lot de travail à un worker dispatché, créer une carte, ou diagnostiquer une carte qui ne démarre pas. Le job de l'orchestrateur est le routage et la spécification, pas l'implémentation.

## Procédure

### 1. Vérifier qu'un profil existe pour l'assignee

Inventorier d'abord les profils réellement configurés avec `hermes profile list`, puis utiliser leur identifiant exact comme assigné. Distinguer un nom de rôle dans la prose d'un identifiant explicitement exigé : si l'utilisateur impose un identifiant exact et demande l'arrêt s'il manque, ne pas le remplacer silencieusement par une variante, même accentuée différemment. Signaler la variante existante pour décision, sans créer ni renommer de profil.

Le dispatcher ne spawn que si `profile_exists(assignee)` est vrai. Sinon la carte reste `ready` **indéfiniment, sans aucun bruit** — c'est l'échec le plus silencieux du système.

Créer un profil uniquement si cette création est autorisée ; les commandes ci-dessous ne sont pas des commandes de vérification :

```bash
hermes profile create <nom> --clone-from default --clone-config
```

Sans CLI `hermes` dans le PATH, passer par la source (importable depuis le venv de l'app) :

```python
from hermes_cli.profiles import create_profile
create_profile("<nom>", clone_from="default", clone_config=True, description="...")
```

Le clone **retire les canaux de messagerie** : garder un jeton de bot copié fait que deux gateways se disputent le même bot. Vérifier ensuite que le profil a bien `config.yaml` + `.env` — sans identifiants, le worker démarre mais ne peut rien faire.

### 2. Choisir le workspace

Sélectionner d'abord le board explicitement : passer `board=<slug demandé>` à chaque appel `kanban_*`, lectures et vérifications comprises. `tenant` et `project` ne sélectionnent pas le board : une carte peut porter le bon tenant sur le mauvais tableau. Vérifier la carte créée par `kanban_show` avec le même `board`. Lors d'une correction de routage, suspendre la carte mal routée avant toute reprise ailleurs et conserver les références croisées ; ne pas supprimer l'historique ni supposer que le seul changement de statut garantit l'arrêt du processus.

`workspace_path` est résolu dans le **conteneur de la dispatcher**, pas dans celui d'où l'on écrit la carte. Un chemin parfaitement valide pour soi peut être `Permission denied` (ou ENOENT) pour elle, et le spawn échoue.

En cas de doute : `workspace_kind: scratch` **avec `workspace_path` NULL** — la dispatcher crée alors `<board>/workspaces/<id>/`, jetable et toujours accessible. `scratch` + un `workspace_path` explicite est traité comme un chemin legacy : le worker travaille *directement* dans ce dossier (cwd), et ses brouillons atterrissent dans le projet.

**Jamais `dir` (ni `scratch` + path) sur un dossier de projet partagé** — racine d'un dépôt, corpus, dossier où d'autres cartes écrivent. Avec N workers parallèles la racine devient une décharge de `extract_v3.py` / `full_text.txt`, et un worker peut lire par erreur l'extrait d'un autre (faux blocage « mauvais fichier source » observé). Le corps de la carte donne les chemins absolus du projet à lire et le seul sous-dossier autorisé en écriture. Une **carte d'orchestration** dont la consigne impose `dir <projet>` reproduit le problème à chaque relance : corriger sa consigne, pas seulement les cartes filles. Exception : `dir` sur la racine d'un dépôt seulement si les workers doivent y commiter, le body nommant le seul sous-dossier autorisé en écriture (voir `deleguer-sous-agents`).

Le workspace est figé **au claim** (`set_workspace_path` juste après `claim_task`). Modifier `workspace_kind`/`workspace_path`/`skills`/`body` sur une carte n'affecte que les dispatches futurs : les workers déjà `running` gardent leur cwd et leur contexte jusqu'à la fin de leur run — vérifier avec `readlink /proc/<pid>/cwd`, pas avec la ligne de tâche.

### 2b. Plusieurs workers dans un même dossier partagé

Quand des cartes doivent écrire dans un projet commun (fiches, corpus), prévenir la pollution du dossier avant de lancer le lot :

1. Fournir l'outillage partagé dans le projet (`tools/`) et l'imposer dans le corps de chaque carte + un skill forcé (`skills` = JSON `["<skill>"]` sur la carte) ; sinon chaque worker réinvente son extracteur/venv et laisse des `*_v2.py` à la racine.
2. Faire écrire les sorties temporaires dans `$HERMES_KANBAN_WORKSPACE` (les outils partagés doivent y écrire par défaut, jamais dans le cwd).
3. Poser un balayeur sans LLM (cron `no_agent`, ~10 min) qui **déplace** les intrus de la racine vers `out/_stray/<horodatage>/` — jamais de suppression : un worker en cours peut encore lire son brouillon.
4. Retirer le balayeur quand les runs lancés avant la correction sont terminés.

Avant de canonicaliser un outil partagé, observer un worker réel (journal de run, commentaires de carte) pour figer la chaîne qu'il utilise effectivement, pas celle qu'on imagine.

### 3. Rédiger la carte

Pour un nouveau projet, créer d'abord le dossier de travail, puis le board dédié avec un `default_workdir` explicite. Ne jamais changer le board courant global simplement pour créer ou vérifier des cartes : passer `--board <slug>` à chaque commande, afin de préserver les autres flux.

Le corps doit porter ce que le worker ne peut pas déduire :

- les **décisions d'architecture**, tranchées par l'orchestrateur (le worker ne doit pas les rediscuter ni choisir à la place d'un autre lot) ;
- les **voies mortes déjà prouvées**, énoncées comme telles, pour qu'il ne les ré-explore pas ;
- des **critères d'acceptation** vérifiables un par un, chacun avec sa commande ;
- les **contraintes d'environnement vécues** (accès indisponibles, outils refusés hors d'une racine, chemins réels) ;
- les chemins exprimés dans la **vue du worker**, pas la sienne.

#### Identifiants explicites (IDs) plutôt que titres ou noms ambigus

Dans le corps de chaque carte de lecture/synthèse, lister **les IDs** (`sha256-<hash>`, `task_id` parent, identifiants d'objets partagés) plutôt que les titres d'ouvrages ou de fichiers. Les titres prêtent à confusion (deux livres avec un titre proche, fautes de frappe, accents) ; les IDs sont stables et vérifiables par grep. Quand un regroupement thématique est incomplet (certains items n'ont pas pu être ajoutés comme parents par contrainte technique), les inclure **dans le corps ou via commentaire** avec instruction explicite de les intégrer — sinon la synthèse se déclenche sans eux.

#### Campagne lecture → revue → extraction stratégique (exemple : corpus de livres/transcripts)

Quand l'objectif est de refaire un corpus avec contrôle de rigueur, planifier la chaîne complète avant de créer les cartes : une carte `lecteur` produit la fiche canonique, une carte `reviseur` enfant (`parents=[reader_task_id]`) vérifie la fiche contre la source et le template, puis une carte `stratege` enfant (`parents=[reviewer_task_id]`) extrait les findings/enseignements exploitables. Ne crée pas un lot de cartes lecteur seules pour ajouter la revue ou la stratégie après coup : les dépendances doivent exister dès le dispatch pour éviter des validations orphelines, doubles traitements ou synthèses sur fiches non revues.

- Vérifier d'abord que les profils `lecteur`, `reviseur` et `stratege` existent réellement, ont `config.yaml` + `.env`, et `worktree: false` si leurs workspaces ne sont pas des dépôts Git.
- Créer une chaîne par SHA-256 unique ; pour les fichiers binaires doublons, lister les autres filenames dans le corps de la même carte au lieu de créer plusieurs lecteurs qui écriraient le même `knowledge/books/sha256-<hash>.md` ou `knowledge/transcripts/sha256-<hash>.md`.
- **Filtrage des sources avant dispatch en batch :** Toujours vérifier et filtrer la liste brute pour exclure les formats parasites (ex. `.textclipping`, `.DS_Store`, fichiers non cibles ou templates) avant la génération des cartes afin de ne pas saturer le board de tâches invalides.
- **Gating de parallélisme par vagues (Wave DAG) :** Pour borner strictement le parallélisme à $K$ tâches simultanées (ex. $K=3$) sur un lot de $N$ éléments avec pipeline $R \rightarrow Rev \rightarrow S$ :
  1. Partitionner les $N$ éléments en vagues de taille $K$ ($W_0, W_1, \dots, W_m$).
  2. Chaîne interne par élément : $R_i \rightarrow Rev_i \rightarrow S_i$.
  3. Inter-vagues : pour toute vague $w > 0$, les $K$ cartes $R$ initiales prennent comme parents `parents=[S_{w-1, 1}, S_{w-1, 2}, \dots, S_{w-1, K}]` (toutes les cartes terminales $S$ de la vague $w-1$).
  4. La vague $w$ ne démarre que quand la vague $w-1$ est 100% terminée, garantissant au maximum $K$ workers actifs à tout instant sur le lot.
- **Instanciation en masse via `hermes_cli.kanban_db.create_task` :** Pour injecter proprement des centaines de cartes sans latence API, exécuter un script avec `/opt/hermes/.venv/bin/python` et `PYTHONPATH=/opt/hermes` en passant la connexion SQLite du board (`sqlite3.connect('<KANBAN_ROOT>/kanban/boards/<board>/kanban.db')`). `create_task()` gère automatiquement la création atomique, le calcul de statut (`ready` si aucun parent, `todo` sinon), les liens `task_links`, les événements `task_events` (`created`, `dependency_wait`) et l'idempotence.
- Mettre les idempotency keys par étape et par corpus, par exemple `corpus-pass2:read:<sha>`, `corpus-pass2:review:<sha>`, `corpus-pass2:nectar:<sha>` ou `transcripts:read:<sha>`, `transcripts:review:<sha>`, `transcripts:strat:<sha>`, puis une carte finale de consolidation thématique dépendante de toutes les cartes `stratege`.
- Exporter un mapping durable `(sha256, filename(s), reader_task_id, reviewer_task_id, strategist_task_id, final_consolidation_task_id)` dans `out/_stray/<timestamp>/` ou un artefact Kanban ; ne jamais le laisser à la racine.
- Le corps lecteur doit nommer la source, le SHA attendu, le template associé (`knowledge/books/TEMPLATE.md` ou `knowledge/transcripts/TEMPLATE.md`), `tools/` (notamment scripts d'audit dédiés `tools/audit_transcript_fiches.py`), `STRUCTURE.md`, `IDEA.md` et `AGENTS.md`. Il doit aussi imposer la clôture Git de la fiche : vérifier `git status --short`, ne jamais utiliser `git add .`, stage uniquement la fiche cible, lancer `python3 tools/test_pre_commit_hook.py` et `git diff --check`, puis faire un commit dédié (`docs(knowledge): add pass2 fiche <sha12>` ou `docs(transcripts): add fiche <sha12>`) ; si la fiche existe déjà sans modification, ne pas créer de commit vide et le signaler dans le handoff. Le corps réviseur doit lister les critères de rejet (sections manquantes, couverture textuelle/pages qui ne somme pas, placeholders, citations non sourcées, hypothèses non réfutables, erreurs ASR non signalées) et exiger l'usage de `kanban_request_changes` plutôt que `kanban_block` en cas de non-conformité documentaire pour permettre le retour automatique au lecteur. Le corps stratège doit nommer `knowledge/strategy/TEMPLATE.md` et produire `knowledge/synthesis/sha256-<hash>.synthesis.md` sans règle exécutable ; il doit aussi imposer la clôture Git de la synthèse : vérifier `git status --short`, ne jamais utiliser `git add .`, stage uniquement le fichier de synthèse, lancer `python3 tools/test_pre_commit_hook.py` et `git diff --check`, puis faire un commit dédié ; si la synthèse existe déjà sans modification, ne pas créer de commit vide et le signaler dans le handoff.
- La carte finale de consolidation thématique reconstruit `knowledge/guidelines/` à partir des synthèses validées et prépare seulement des hypothèses/playbooks documentaires sous `knowledge/strategy/`, jamais un statut `simulation` ou `active réelle` sans validation explicite de l'utilisateur.

### 4. Créer, puis VÉRIFIER la prise en charge

Ne jamais conclure « carte créée » = « travail lancé ». Vérifier d'abord l'état réel du gateway avec `hermes gateway status`; s'il est déjà actif, ne pas le redémarrer. Attendre au moins un intervalle de dispatcher (embarquée dans le gateway, 60 s, verrou singleton) plus le démarrage du worker, puis lire la ligne de tâche (`status`, `current_run_id`, `last_failure_error`) **et** le journal de run par tâche :

```bash
tail -20 "$KANBAN_ROOT/kanban/logs/<task_id>.log"        # board default
tail -20 "$KANBAN_ROOT/kanban/boards/<slug>/logs/<task_id>.log"   # autre board
```

- **Un `last_failure_error` renseigné prouve que la dispatcher a essayé et échoué — c'est le contraire de « en attente normale ».**
- **Une transition de statut via le tableau de bord (`dashboard/direct`) replonge immédiatement la carte dans le cycle de dispatch.** Passer une carte bloquée en `ready` à la main ne fait pas *attendre* — la dispatcher reclaim au tick suivant et un nouveau worker spawn, souvent sans aucun commentaire pour le cadrer. Avant tout `ready` manuel sur une carte déjà vue par un worker, écrire d'abord le commentaire de cadrage (motif de reprise, ce qui doit changer). Sinon le nouveau run fait la même chose que le précédent et l'utilisateur reçoit une clôture « done » sans valeur ajoutée.
- **Pour rafraîchir la raison d'un blocage existant, utiliser `add_comment` — pas `block_task`.** `block_task` exige un état `running`/`ready` ; sur une carte déjà `blocked` il retourne `False` silencieusement, sans modifier la raison ni produire d'événement. Le commentaire est l'unique primitive qui marche pour rafraîchir le motif visible d'une carte bloquée.

### 5. Surveiller et débloquer proprement

Pour une mise en place arrêtée avant tout lancement, rechercher d'abord une carte de suivi existante et conserver la décision attendue dans son corps ou ses commentaires. Si une nouvelle carte est nécessaire, la créer directement avec `initial_status: blocked`, une clé d'idempotence et un assigné vérifié ; relire ensuite cette carte par son identifiant. Ne pas appeler `kanban_block` sur une carte déjà créée bloquée : le blocage initial suffit et une seconde transition est invalide. Ne pas annoncer que les workers ont démarré dans ce cas.

Avant de relancer une carte bloquée ou de réconcilier des boards, vérifier aussi le processus d'origine : `block_task` peut libérer le claim sans envoyer de signal au worker. Un ancien processus peut donc encore créer des cartes malgré `blocked`. Sur l'hôte confirmé, vérifier l'identité PID par la commande et la carte avant une terminaison ciblée, puis constater sa sortie avant reprise. Recalculer les correspondances SHA-256 juste avant le transfert : des cibles absentes lors du premier audit peuvent avoir été créées entre-temps. Préserver corps, runs, événements, commentaires et références des pièces jointes ; ne pas convertir un ancien `done` en validation indépendante.

Un worker qui meurt sans conclure est auto-bloqué après la limite d'échecs de spawn. `kanban_unblock` re-queue la carte : corriger la cause **d'abord**, sinon elle se re-bloque au cycle suivant.

### 5a. Cartes bloquées sur une cause devenue obsolète

Quand une carte reste `blocked` parce que la cause a disparu (autorisation acquise, migration exécutée, doublon résolu), **ne pas débloquer aveuglément** :

1. Vérifier l'état réel avec `kanban_show(board=..., task_id=...)` — la carte peut déjà être `running`/`done` sans qu'on le sache (un autre worker l'a reprise), et `kanban_unblock` retourne alors `not blocked or unknown`.
2. Si la cause du blocage est obsolète mais qu'une fiche existe déjà au chemin canonique, **ne pas débloquer** : relancer la lecture risquerait un écrasement ou une double fiche. Documenter la cause obsolète dans un commentaire (`add_comment`) et router la carte vers la consolidation (validation, pas régénération).
3. `block_task` **ne peut pas** modifier la raison d'un blocage existant — il exige un état `running` ou `ready`. Pour rafraîchir la narrative d'une carte déjà `blocked`, utiliser uniquement `add_comment` (et garder le `last_failure_error` intact si pertinent). Enchaîner avec un `kanban_unblock` quand l'utilisateur a accepté la reprise.
4. Vérifier l'unicité du livrable avant tout débloquage : un script Python sur la base du board (mode `ro`) qui croise `book_id` et fichiers réels dans `knowledge/books/` évite les surprises d'écrasement.

### 5b. Vérifier une allégation sur le contenu d'un PDF

Quand un worker signale qu'un PDF ne contient pas le livre annoncé, **toujours vérifier directement** avant d'agir :

```python
# Utiliser le venv du PROJET (qui contient pypdf/pypdfium2/pdfplumber),
# PAS le venv hermes (qui n'a pas ces paquets).
import pypdf
r = pypdf.PdfReader("/chemin/du.pdf")
print(len(r.pages))
for i in [0, 1, 2]:  # page de titre, page de copyright, table des matières
    print(f"--- p{i+1} ---")
    print(r.pages[i].extract_text()[:600])
```

L'orchestrateur peut avoir une lecture contaminée (extraction d'un run voisin laissé à la racine, par exemple). La vérification directe tranche la dispute sans dépendre d'aucun worker.

## Pièges qui coûtent du temps

- **`worktree: true` dans le profil du worker.** Le CLI tente de créer un worktree au démarrage, échoue hors dépôt Git, et sort en `rc=0` **sans appeler** `kanban_complete` ni `kanban_block` → « protocol violation » → auto-blocage, avec un statut qui n'explique rien. Mettre `worktree: false` dans tout profil de worker dont le workspace n'est pas un dépôt Git.
- **Ne jamais inventer de hash dans le body d'une carte.** Une fiche canonique se nomme `sha256-<hash>.md` et son chemin source est `<projet>/books/<filename>`. Toujours récupérer ces deux chaînes dans l'inventaire officiel (`knowledge/books-inventory.json` produit par `tools/inventory.py`) **avant** `kanban_create`, et **jamais** générer un hash par complétion de motifs. Si l'inventaire est manquant, le relancer. Une carte avec hash inventé → fiche à un chemin qui n'existera jamais → worker forcé d'inventer à nouveau le contenu. Vérification : pour chaque carte créée en batch, relire au moins un échantillon et confirmer que `sha256` fait 64 caractères hex et matche le filename dans l'inventaire.
- **Un worker peut corriger un hash inventé, mais pas toujours silencieusement.** Avec `pypdf` ou `pdfplumber` le worker a accès à un calcul de SHA-256 indépendant ; il peut détecter que le hash du body de la carte ne correspond pas au fichier et écrire la fiche au bon chemin canonique. Conséquence : une carte avec hash inventé dans le body ne signifie pas nécessairement fiche-perdue. Avant d'annoter « annulation », toujours croiser `kanban_show` + `ls knowledge/books/` + l'inventaire.
- **Sauvegarder le mapping lecteur→stratège.** À chaque dispatch en chaîne (lecture → consolidation), exporter dans un artefact (`out/reader_to_strat_map.json` ou équivalent) la table `(sha256, filename, reader_task_id, strat_task_id)`. Les vagues suivantes peuvent re-dispatcher sans recalculer la chaîne, et le board peut être reconstruit à partir de cet artefact en cas d'incident.
- **Le journal de run est la preuve, pas le statut.** `<KANBAN_ROOT>/kanban/logs/<task_id>.log` (board `default`) ou `<KANBAN_ROOT>/kanban/boards/<slug>/logs/<task_id>.log` contient la sortie réelle du worker (l'abandon worktree, par exemple) qu'aucun champ de la carte ne montre.
- **Le worker tourne dans un autre conteneur que soi.** Il ne voit pas les chemins qui n'existent que là où l'on écrit la carte. Copier les références nécessaires dans un **montage partagé**, en 644/755 (sinon illisibles), et pointer la carte dessus. Le contrat lui-même va dans le **corps de la carte** : le worker peut ne pas pouvoir lire la source.
- **Choisir le modèle de chaque sous-agent, ne pas hériter par défaut.** `delegate_task` donne aux enfants le modèle du parent (souvent le plus cher) sauf `delegation.model`/`delegation.provider` dans `config.yaml` ; l'utilisateur surveille ses quotas. Une carte Kanban accepte `model`/`provider` par carte : y router les relectures neutres (autre fournisseur) et les tâches mécaniques (modèle léger), et dire quel modèle a tourné dans le compte rendu.
- **Ne pas confier une suite à soi-même.** Un lot suivant part vers le profil spécialiste, pas vers l'orchestrateur.
- **`kanban_list` avec filtre large peut timeout sur un gros board.** Préférer filtrer sur `assignee` ou lire la base SQLite directement avec `mode=ro` pour les audits : plus déterministe, et retourne la liste complète sans plafond de pagination.
- **`sqlite3` CLI n'est pas dans le PATH par défaut** sur les images minimales. Utiliser Python `sqlite3.connect('file:.../kanban.db?mode=ro', uri=True)` depuis n'importe quel venv qui a sqlite3 (tous).
- **Les tâches Kanban et les fiches disque sont deux sources indépendantes qui divergent.** Le board ne reflète pas forcément l'état du filesystem (fiches manquantes, fiches orphelines). Avant de compter des « livres lus » ou des « fiches produites », croiser les deux : tâches `assignee='lecteur'` title LIKE 'Lire et documenter%' (113) vs fichiers `sha256-*.md` dans `knowledge/books/` (89). Les titres des tâches nécessitent une normalisation : retirer les suffixes `(reprise)`, `[DOUBLON]`, `[FICHE EXISTE]` avant de dédoublonner, sinon on compte des lectures multiples comme des livres distincts. Les fiches sur disque peuvent aussi utiliser des en-têtes variés (`# Fiche de lecture`, `# Fiche documentaire`, `# Fiche de connaissance`, `# Fiche de recherche`) — ne pas filtrer uniquement sur `# Fiche de lecture` pour le décompte.
- **Débloquer une carte de lecture alors qu'une fiche existe déjà au chemin canonique écrase le travail existant.** Toujours croiser `book_id` ↔ `knowledge/books/<sha256>.md` avant un `kanban_unblock` ; en cas de doute, ajouter un commentaire qui pointe vers la consolidation au lieu de débloquer.
- **`rc=0 protocol violation` a trois causes distinctes — le diagnostic dépend de l'existence du livrable.**

  **Cause 1 — worktree (cf < 5s, même profil pour toutes les cartes).** Le worker tente un worktree, échoue hors-dépôt, sort en rc=0 sans rien faire. Corriger `worktree: false` dans le profil, puis SQL reset en masse.

  **Cause 2 — timeout (cf ≈ `lifetime_seconds`, PDFs longs).** Le worker fait le travail (fiche écrite) mais se fait tuer avant d'appeler `kanban_complete`. Corriger le profil (`terminal.timeout: 300`, `lifetime_seconds: 900`), puis SQL reset. Livrable **existe déjà** sur disque.

  **Cause 3 — stale run (fiche existe, mais `kanban_complete` échoue).** Le worker a terminé et écrit la fiche, puis appelle `kanban_complete` mais le claim est expiré ou le run est considéré stale par le kernel → `kanban_complete` retourne `could not complete (unknown id, stale run, or already terminal)`. **Ne pas ré-Dispatcher** — la fiche existe. Corriger en SQL direct :

  ```python
  import sqlite3, re, os
  db = '<KANBAN_ROOT>/kanban/boards/<board>/kanban.db'
  fiche_dir = '<projet>/knowledge/books'
  fiches = {f for f in os.listdir(fiche_dir)
            if f.startswith('sha256-') and '_atomic' not in f}
  conn = sqlite3.connect(db)
  cur = conn.cursor()
  cur.execute("""
      SELECT id, body, status FROM tasks
      WHERE assignee='<profile>' AND status IN ('running','blocked')
  """)
  for tid, body, status in cur.fetchall():
      m = re.search(r"sha256-([0-9a-f]{64})", body or "")
      if not m:
          continue
      sha = m.group(1)
      if any(f"sha256-{sha}" in f for f in fiches):
          cur.execute(
              "UPDATE tasks SET status='done', consecutive_failures=0 WHERE id=?",
              (tid,)
          )
          print(f"Marked done: {tid} (fiche existed)")
  conn.commit()
  conn.close()
  ```
  Toujours faire ce fix **avant** de débloquer ou dispatcher à nouveau — évite un re-traitement innecesaire d'un PDF de 500+ pages.

  **Protocole de diagnostic en une commande** (à exécuter dès la première notif « gave up », pas de re-injection manuelle une par une) :
  ```python
  import sqlite3, os, re
  db = '<KANBAN_ROOT>/kanban/boards/<board>/kanban.db'
  fiche_dir = '<projet>/knowledge/books'
  fiches = {f for f in os.listdir(fiche_dir)
            if f.startswith('sha256-') and '_atomic' not in f}
  conn = sqlite3.connect(db)
  cur = conn.cursor()
  for tid in ['t_XXXX', 't_YYYY']:
      cur.execute(
          "SELECT id, status, worker_pid, consecutive_failures, body FROM tasks WHERE id=?",
          (tid,)
      )
      row = cur.fetchone()
      if not row:
          continue
      tid, status, pid, cf, body = row
      m = re.search(r"sha256-([0-9a-f]{64})", body or "")
      sha = m.group(1)[:16] if m else "?"
      fiche = any(f"sha256-{m.group(1)}" in f for f in fiches) if m else False
      alive = False
      if pid:
          try:
              os.kill(pid, 0); alive = True
          except:
              pass
      print(f"{tid}: {status} cf={cf} alive={alive} fiche={fiche}")
      # action : fiche + done → SQL mark done
      # action : no fiche + alive=True → wait
      # action : no fiche + alive=False → SQL unblock
  conn.close()
  ```

  **Mode batch (N cartes simultanées, même notif) :** au lieu de N appels unitaires, lancer le diagnostic sur **tous les task_ids** en une seule passe Python — produit une table complète `tid → {status, alive, fiche, action}`. Pour chaque ligne où `fiche=True` : SQL `UPDATE tasks SET status='done' WHERE id=?`. Pour chaque ligne où `fiche=False` ET `alive=False` : SQL `UPDATE tasks SET status='ready', consecutive_failures=0 WHERE id=?`. Ne réinjecter manuellement que les cartes qui n'ont ni fiche ni worker vivant. C'est le schéma appliqué dans la procédure de monitoring du board.

  **Cause la plus fréquente : `lifetime_seconds: 300` (5 min) trop court.** Le worker fait le travail (fiche écrite) mais se fait tuer avant d'appeler `kanban_complete` → auto-blocage après 2 échecs. Config corrigée pour PDFs longs (>500 pages) dans le profil `lecteur` : `terminal.timeout: 300`, `lifetime_seconds: 900` (15 min).

  **Quand la cause est un timeout partagé (N cartes, même erreur, même profil)**, corriger d'abord le profil (`terminal.timeout: 300`, `lifetime_seconds: 900`), puis réinitialiser les cartes en masse par SQL — plus efficace que N appels `kanban_unblock` :

  ```python
  import sqlite3
  db = '<KANBAN_ROOT>/kanban/boards/<board>/kanban.db'
  conn = sqlite3.connect(db)
  cur = conn.cursor()
  # Identifier : même erreur + 2+ échecs consécutifs
  cur.execute("SELECT id FROM tasks WHERE status='blocked' AND assignee='<profile>' AND consecutive_failures >= 2")
  ids = [r[0] for r in cur.fetchall()]
  placeholders = ','.join('?' * len(ids))
  cur.execute(f"UPDATE tasks SET status='ready', consecutive_failures=0, block_recurrences=0 WHERE id IN ({placeholders})", ids)
  conn.commit()
  ```
  Note : la colonne de la DB s'appelle `consecutive_failures` — **pas `fail_count`** (n'existe pas). Valider avec l'utilisateur avant de modifier un profil partagé.

  **Cas particulier : fiche déjà écrite mais tâche en `running` (worker killed avant `kanban_complete`).** Dans ce cas, `kanban_complete` échoue avec « stale run ». Corriger directement en SQL :
  ```python
  import sqlite3, re, os
  db = '<KANBAN_ROOT>/kanban/boards/<board>/kanban.db'
  fiche_dir = '<projet>/knowledge/books'
  fiches = {f for f in os.listdir(fiche_dir) if f.startswith('sha256-') and '_atomic' not in f}
  conn = sqlite3.connect(db)
  cur = conn.cursor()
  cur.execute("SELECT id, body, status FROM tasks WHERE assignee='<profile>' AND status IN ('running','blocked')")
  for tid, body, status in cur.fetchall():
      m = re.search(r"sha256-([0-9a-f]{64})", body or "")
      if not m: continue
      sha = m.group(1)
      if any(f"sha256-{sha}" in f for f in fiches):
          cur.execute("UPDATE tasks SET status='done', consecutive_failures=0 WHERE id=?", (tid,))
          print(f"Marked done: {tid} (fiche exists)")
  conn.commit()
  conn.close()
  ```
  Coupler ce fix avec un扫干净 des processus zombies (`ps aux | grep hermes`) pour s'assurer qu'aucun vieux worker ne tourne encore sur la carte.
- **Doublon silencieux dans un dispatch en batch.** Quand on crée N cartes en parallèle depuis une liste `(filename, sha256)`, deux cartes pour le même `sha256` peuvent être créées par erreur (par exemple deux paths équivalents dans l'inventaire, ou deux tentatives). Le mapping `out/<dispatch>_map.json` avec `(sha256 → [task_ids])` permet de détecter les collisions par clé après-coup — toujours indexer par hash et trier, et inspecter les entrées où la liste dépasse 1.
- **Hermes venv ≠ project venv.** Le venv de l'app hermes (`/opt/hermes/.venv`) ne contient ni pypdf, ni pypdfium2, ni pdfplumber — utiles pour vérifier les PDF. Pour lire un PDF côté orchestrateur, utiliser `<projet>/.venv/bin/python` (qui contient ces paquets après installation selon la skill `trading-pdf-reading`, locale au profil qui la porte).
- **`block_task` ne modifie pas un blocage existant.** Pour rafraîchir la raison d'une carte déjà `blocked`, utiliser `add_comment`. `block_task` exige un état `running` ou `ready` et retourne silencieusement `False` sinon.

## CLI `hermes kanban` : boards et réglages de concurrence

- **Board courant** = défaut des appels CLI : `hermes kanban boards list` le marque ; le slug vit dans `<KANBAN_ROOT>/kanban/current`. Chaque board autre que `default` a son stockage `<KANBAN_ROOT>/kanban/boards/<slug>/` : `board.json` (`default_workdir`, `project_id`), `kanban.db`, `workspaces/`, `logs/`.
- **Cibler un autre board sans changer le courant** : flag global `--board <slug>` placé AVANT la sous-commande (`hermes kanban --board brain create "<titre>" --assignee <profil>`), ou `HERMES_KANBAN_BOARD=<slug>` dans l'environnement. `boards switch` change le courant — à réserver aux cas où c'est voulu.
- **`boards show` n'accepte aucun slug** : `show` (alias `current`) imprime le slug du board courant et rien d'autre (`hermes kanban boards show trading` → `error: unrecognized arguments: trading`). Pour l'inventaire des boards, `boards list` (le courant est marqué `●`) ; pour les métadonnées d'un board précis, lire `boards/<slug>/board.json`.
- `hermes kanban assignees` = profils connus + compteurs par profil (blocked/done/todo) du board courant : premier réflexe avant de promettre un routage, ou pour auditer qui est dispatchable.
- **Réglages de concurrence : globaux, jamais par board.** `kanban.max_in_progress` est un plafond HOST (tous boards, les deux lanes) ; non défini ⇒ défaut dérivé mémoire `clamp(MemTotal/512 MiB, 2, 8)`, la valeur effective est loggée au démarrage du dispatcher dans `gateway.log` (« memory-derived default max_in_progress=N »). `kanban.auto_decompose` est global aussi (défaut `True`, `auto_decompose_per_tick: 3`). À côté : `max_in_progress_per_profile` (cap par profil) et `max_spawn` (plafond unique, appliqué à chaque board). Défauts documentés : `hermes_cli/config_defaults.py` ; `board.json` ne porte aucun réglage de dispatch.
- Sur cette install, la CLI peut être absente du PATH des shells d'outils : invoquer `/opt/hermes/bin/hermes` (ou `/opt/hermes/libexec/hermes` ; les deux existent, vérifier avec `ls`). `hermes kanban` pour un autre profil : `HERMES_HOME=/opt/data/profiles/<profil>` ; le board reste commun (voir `KANBAN_ROOT`).

## Piloter le board et les profils sans la CLI (import `hermes_cli`)

Quand la CLI n'est pas utilisable (pas de shell), importer `hermes_cli` depuis le venv de l'app plutôt que d'écrire en SQL brut sur la base du board :

```python
from pathlib import Path
from hermes_cli.kanban_db_connect import connect
from hermes_cli.kanban_db_workspace import _set_task_column

# Board par défaut : <KANBAN_ROOT>/kanban.db ; tout autre board : <KANBAN_ROOT>/kanban/boards/<slug>/kanban.db
# (une requête sur la mauvaise base renvoie 0 ligne sans erreur — vérifier le compte avant d'UPDATE).
conn = connect(db_path=Path(KANBAN_ROOT) / "kanban" / "boards" / BOARD / "kanban.db")
_set_task_column(conn, task_id, "workspace_kind", "scratch")
_set_task_column(conn, task_id, "workspace_path", None)
_set_task_column(conn, task_id, "last_failure_error", None)
_set_task_column(conn, task_id, "skills", json.dumps(["<skill>"]))  # skill forcé au dispatch
_set_task_column(conn, task_id, "body", body + BLOC_OUTILLAGE)        # append, ne pas réécrire
conn.commit()
```

Les lignes de `kanban_db_connect` sont des `sqlite3.Row` : convertir en `tuple(r)` avant `Counter`/affichage, sinon chaque ligne est un objet distinct.

```python
```

Même approche pour la configuration d'un profil, en pointant `HERMES_HOME` sur le profil :

```python
from hermes_cli.config import set_config_value
set_config_value("worktree", "false", force=True)
```

## Cartes à archiver après un dispatch

Une carte « annulation nécessaire » doit être retirée du flux `ready` pour qu'aucun worker ne la picke. Procédure :

1. Commenter la carte avec le motif précis (quelle autre carte la remplace, ou pourquoi annuler) — le commentaire est durable, le statut ne l'est pas.
2. Mettre la carte à un statut terminal non-bloquant. Avec l'API Kanban actuelle : si `kanban_complete` est accessible, l'appeler avec un `summary` court (par exemple « Annulé — doublon de t_XYZ »). Sinon, ajouter `kanban_block` n'est **pas** la bonne primitive : `block_task` est réservé aux blocages externes. À défaut d'outil d'archivage, ajouter un commentaire final qui pointe vers la carte de remplacement et **changer `assignee` vers un profil qui n'existe pas** : la dispatcher ne spawnera plus et la carte restera `ready` mais inerte (moins dangereux qu'un `blocked` qui attire l'attention du triage).

### Avant d'annoter « annulation », **vérifier** que le travail n'a pas déjà été fait

Un commentaire « annulation nécessaire » lu en isolation (par le triage ou par un futur orchestrateur) déclenche un archivage erroné si la carte est entre-temps passée en `done`. Procédure de vérification obligatoire :

1. Appeler `kanban_show(board=..., task_id=...)` et lire `status`, `current_run_id`, `last_failure_error`, `events[].kind` et `runs[].outcome`.
2. Si `status == done` ou si un événement `attached`/`completed` est présent avec une fiche attachée, **ne pas annoter l'annulation** : le worker a livré, le livrable existe. Poster à la place un commentaire qui pointe vers le livrable (chemin canonique + tâche parente s'il y en a une).
3. Croiser le hash du body avec l'inventaire (`knowledge/books-inventory.json`). Si le hash du body est manifestement inventé mais que la fiche livrée existe au bon chemin canonique (vérifier `knowledge/books/<sha256>.md`), alors le worker a recalculé le hash et écrit au bon endroit — pas une annulation, juste un défaut de spécification dans la carte.
4. Si les vérifs 1-3 confirment l'annulation, procéder aux étapes 1-2 ci-dessus. Sinon, rétracter tout commentaire antérieur qui parlait d'annulation.

## Fiches écrites avec un nom de fichier à hash inventé

Quand un worker écrit une fiche à un chemin `sha256-<X>.md` où `<X>` est un hash inventé dans le body de la carte (au lieu du vrai hash `<Y>`), deux cas :

- **Le vrai hash `<Y>` existe aussi comme chemin canonique avec une fiche plus complète** : la fiche au chemin inventé est une version précoce/stale. Candidat à la suppression, mais **ne pas supprimer sans validation de l'utilisateur** — la version précoce peut contenir des hypothèses non reportées dans la version finale.
- **Seul le chemin inventé a une fiche** : la fiche est valide mais mal nommée. Candidat au renommage vers le chemin canonique, **toujours après validation** parce que cela modifie l'état partagé.

Dans les deux cas, le diagnostic passe par :

1. Lister les fichiers de `knowledge/books/`.
2. Pour chaque fichier, vérifier si son hash est dans `knowledge/books-inventory.json` (hash canonique connu) ou s'il diverge.
3. Pour chaque hash divergent, chercher le vrai hash dans l'inventaire et vérifier si une fiche existe au bon chemin.

Ne **jamais** exécuter la suppression ou le renommage automatiquement : préparer la liste, commenter la carte de synthèse du projet, attendre l'accord explicite.

## Vérification

- [ ] Le dossier du projet existe et son chemin est explicite.
- [ ] Le board dédié existe et les commandes de création/lecture le ciblent explicitement.
- [ ] Les cartes d'architecture ou de contrat précèdent les cartes d'implémentation dépendantes.
- [ ] L'assignee correspond à un profil qui existe réellement.
- [ ] Le profil a de quoi tourner (`config.yaml` + `.env`).
- [ ] `workspace_kind` / `workspace_path` sont valides dans le conteneur de la dispatcher.
- [ ] La carte porte décisions, voies mortes prouvées, critères vérifiables, chemins vus par le worker.
- [ ] Une prise en charge **réelle** a été observée (`running` + journal de run), pas seulement `ready`.
- [ ] Les références nécessaires sont lisibles depuis le conteneur du worker.
- [ ] Pour une carte de lecture débloquée : fiche absente au chemin canonique (sinon risque d'écrasement).
- [ ] Pour une carte bloquée dont la cause est obsolète : action prise via commentaire, pas débloquage, et routage explicite vers la consolidation.
- [ ] Avant de comptabiliser les « livres du corpus » : croiser le nombre de tâches `Lire et documenter` distinctes (titres normalisés) avec le nombre de fiches `sha256-*.md` sur disque, et documenter l'écart.

## Voir aussi

- `references/chain-dispatch-mapping.md` — schéma du mapping lecteur→stratège, détection de doublons, procédure de reprise depuis l'artefact.
- `references/post-dispatch-cleanup-script.md` — outil `kanban_post_dispatch.py` qui matérialise l'archivage et le hash-check, conventions de marqueurs dans les commentaires, diagnostic d'un `rc=0` récurrent.
- Skill `hermes-plugin-env-config` — environnement de plugins, topologie multi-conteneurs, contrat d'extension WebUI.
- Skill `sdlc-review` (si présente dans le profil) — verdict sur un handoff reçu dans la voie review.
- Skills `kanban-worker-dispatch` (diagnostic d'un worker muet), `kanban-batch-recovery` (reprise en lot), `kanban-tasks` (cycle de vie via la CLI), `deleguer-sous-agents` (fan-out).
- Skill `readonly-audit` — vérifications en lecture seule (tableau contrôle | résultat | preuve).
