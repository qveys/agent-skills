---
name: deleguer-sous-agents
description: "Use when fanning out a repo job to Kanban sub-agents."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [kanban, delegation, fan-out, sub-agents, orchestration]
    related_skills: [kanban-orchestration, kanban-tasks, kanban-worker-dispatch]
---

# Déléguer un lot de travail à des sous-agents (cartes Kanban)

## When to Use

- L'utilisateur dit « délègue à un sous-agent <profil> », « un agent par fichier », « fan-out », « parallélise ces digests / ce lot », « répartis sur plusieurs fichiers ».
- Un lot touche un dépôt ou un dossier de travail (notes, fiches, corpus) et se découpe en unités indépendantes.
- Pas pour router une carte isolée ni diagnostiquer un worker muet : voir `kanban-orchestration` et `kanban-worker-dispatch`.

## Principe

« Déléguer à un sous-agent <profil> » se fait avec le **kanban** : une carte par unité de travail, `assignee: <profil>`. Le dispatcher réclame les cartes `ready` en quelques secondes et lance un worker par carte. C'est le mécanisme de délégation ; il produit de vraies cartes visibles sur le board, pas des appels de sous-agent directs (`delegate_task` n'est pas ce que l'utilisateur demande ici, et ses enfants ne peuvent pas muter le board).

Un lot se découpe en **une carte par fichier source** (ou par unité de travail claire), jamais une carte fourre-tout.

## Créer les cartes

`kanban_create` avec :

- `assignee: <profil>` (profil existant : voir `kanban-orchestration` §1)
- `workspace_kind: dir`, `workspace_path: <racine du dépôt de travail>` — uniquement quand les workers doivent écrire/commiter dans ce dépôt. Le body doit alors nommer le seul sous-dossier autorisé en écriture : `dir` sur un dossier partagé expose aux déchets de scripts à la racine et aux lectures croisées (voir `kanban-orchestration` §2). Sinon `scratch` avec `workspace_path` NULL.
- `skills: ["<skill à forcer>"]` pour charger le contexte métier d'emblée (la skill doit exister dans le profil assigné ou dans un dossier `skills.external_dirs` qu'il déclare)
- `title` : classe d'action + cible lisible
- `body` : auto-suffisant, voir ci-dessous
- `parents` : seulement si la carte doit attendre une autre (voir chaînage)
- `board` : explicite (voir « Suivre les cartes »)

## Un body auto-suffisant

Le worker ne voit que le body de sa carte. Y mettre, en clair :

- la source exacte, en **chemin absolu** ;
- les cibles (quelles fiches / quels fichiers de sortie) ;
- le périmètre et les **exclusions** ;
- le chemin absolu de la racine du dépôt de travail (et s'il est un dépôt git distinct d'un autre) ;
- la **skill de référence à lire** avant d'agir (voir « Skill de référence ») ;
- la règle de clôture : commit explicite (jamais `git add .` ni un dossier) au format convenu par le dépôt, puis push selon la politique du dépôt ;
- la **forme attendue** de la sortie quand elle est contrainte : chemin absolu de l'exemple canonique et squelette à reproduire (voir « Forme attendue »).

Le **body est immuable** et aucun outil ne permet de l'éditer : composer le body complet **avant** l'appel `kanban_create`, jamais après. Une carte créée sans body est réclamée par le dispatcher en quelques secondes et lance un worker sans périmètre ; un `kanban_comment` posté juste après atterrit sur une carte déjà `running`, qui ne le relira pas. Pour rattraper une carte créée sans body : la clôturer (`kanban_complete` avec un résumé d'annulation) et refaire le travail par une carte neuve correctement parentée, pas par un commentaire.

## Forme attendue et exemple canonique

Quand la sortie doit suivre une mise en page précise et que l'utilisateur désigne une note de référence, recopier dans **chaque** body le chemin de cette note et le squelette à produire (frontmatter, sections, ordre). Ne pas compter sur un `kanban_comment` : une carte déjà `running` ne le relira pas et sortira une forme non conforme, qu'il faut ensuite rattraper par une carte de reprise.

Symptômes d'une forme demandée mais absente du body : titres à emojis là où l'exemple n'en a pas, frontmatter regroupé par des commentaires `#`, section de liens manquante, blocs d'interaction non conformes. Les écrire d'emblée dans le body évite tout le cycle.

## Chaîner quand les sorties se recouvrent (pitfall majeur)

Si plusieurs cartes écrivent **les mêmes fichiers** (mêmes fiches, mêmes repères partagés), ne pas les lancer en parallèle : deux workers qui écrivent le même fichier en simultané le corrompent et se percutent au push. Chaîner avec `parents` : la carte N a `parents: [<id de N-1>]`, elle reste `todo` (`gated_by`) et est promue en `ready` quand le parent passe `done`.

Constat de terrain : des lots lancés en parallèle ont produit des collisions d'écriture (deux cartes sur la même fiche au même moment) et des répétitions à relire ensuite. Sérialiser est le choix sûr dès que le recouvrement existe.

**Le chaînage se décide avant de créer la carte suivante.** `parents` doit être passé dans l'appel `kanban_create` : un `kanban_link` a posteriori est refusé dès que l'enfant est `running` (réponse « child is already running »), et une carte créée sans parent passe `ready` en quelques secondes. Deux cartes sœurs visant la même fiche tournent alors en parallèle et écrivent le même fichier. Si le chaînage a été oublié, ne pas tenter de le rattraper : suivre les deux cartes et vérifier les fichiers livrés après coup.

## Ordre dans une chaîne « repartir de zéro »

Quand une même cible est visée par plusieurs sources et que chaque carte reconstruit **à partir de zéro** (ignore les fichiers existants), la dernière carte de la chaîne écrase les précédentes pour cette cible. Placer les sources les **plus larges en dernier** (exports de groupe, sources couvrant plusieurs entités) et les sources étroites d'abord, pour que le fichier final porte l'information la plus riche.

Pitfall : ce classement par ordre fait perdre le détail des sources étroites, puisque seule la dernière carte survit pour la cible. Quand une carte aval vise des cibles déjà produites par une carte amont, préférer la **consolidation** à la reconstruction : lui demander explicitement, dans le body, de partir du fichier existant et d'y intégrer seulement ses apports (statuts `NEW / CONFIRM / REFINE / UPDATE`, règle anti-redondance respectée), et de ne créer de zéro que les fichiers qu'aucune carte amont n'a produits. Le préciser noir sur blanc, sinon le worker reconstruit par défaut et écrase le travail amont.

## Exclusions pour les lots de reprise

Quand on rejoue un lot complet, exclure explicitement dans chaque body les fichiers partagés non concernés (index, fichiers de repère, notes personnelles de l'utilisateur, créations de notes hors périmètre), sinon les workers se marchent dessus. Les nommer par chemin absolu, noir sur blanc.

## Skill de référence

Si le dépôt de travail porte sa propre copie de la skill (ex. `<dépôt>/.agents/skills/<nom>/SKILL.md`), le body pointe vers elle : c'est la source de vérité, à jour. La copie du profil (`/opt/data/profiles/<profil>/skills/`) peut être en retard ; faire lire la version du dépôt. Si la skill vit dans le dépôt partagé (clone `agent-skills`, `skills/<nom>/…`), c'est ce dossier qui fait foi.

Pour **corriger** cette skill, éditer la copie qui fait foi avec les outils fichier (`patch`), pas `skill_manage` qui écrit la copie du profil quand l'utilisateur veut la version du dossier. Réaligner la copie du profil ensuite si besoin (skill `sync-profile-skills`, si le profil la possède).

## Consignes et corrections en cours de route

- Écrire toute contrainte directement dans le **body** au moment de `kanban_create`. Un `kanban_comment` ajouté après coup n'est lu qu'au moment où le worker réclame la carte : une carte déjà `running` ne le relira pas et produira selon le body d'origine. Placer dans le body ce qui doit s'appliquer à coup sûr (forme attendue, exclusions, périmètre).
- `kanban_unblock` ne vise que les cartes `blocked` ; une carte `done` ne peut pas être rouverte et le body d'une carte ne peut pas être édité. Pour rejouer une carte terminée, créer une **nouvelle carte**.
- Pour insérer une carte de reprise ou de correction dans une chaîne existante sans casser la sérialisation : lui donner `parents: [<carte précédente>]`, puis la déclarer parent de la carte suivante avec `kanban_link(parent_id=<nouvelle>, child_id=<suivante>)`. La suivante, déjà parente de la précédente, attend alors les deux et l'ordre reste séquentiel. Insérer la reprise **avant** les cartes aval qui consolident la même cible : placée après, elle reconstruit à zéro et écrase la consolidation.

## Vérifier après création

1. `kanban_list(assignee="<profil>", status="ready")` puis `kanban_show` sur la première carte : elle doit passer `running` (events `claimed` + `spawned`).
2. Les enfants doivent apparaître `todo` avec `gated_by` = leur parent.
3. Après `done`, vérifier les artefacts réels et pas la notification : lire les fichiers livrés, `git log --oneline` et `git status --short` du dépôt de travail, état de la branche face à `origin`. Une carte `done` sans commit visible demande une inspection avant de clôturer le lot.
4. Quand plusieurs cartes proches visent le même contenu, comparer les sources et livrables avant d'ajouter une nouvelle carte : désigner un livrable canonique, clôturer les doublons après contrôle et mettre à jour les dépendances aval pour attendre une seule voie canonique. Ne pas laisser des cartes sœurs redondantes créer une fausse file d'attente ou demander un renommage sans besoin fonctionnel.

## Suivre les cartes et les workers

Passer `board` explicitement sur **chaque** appel kanban (`kanban_create`, `kanban_list`, `kanban_show`, `kanban_comment`) et garder le même board du premier au dernier appel du lot : sans lui, la résolution du board actif peut viser un autre board que celui des cartes créées, et un appel légitime répond `unknown task` pour une carte qui existe pourtant.

Pour savoir où une carte a atterri, quelles cartes existent et où en est un worker, interroger directement la base du board avec le module `sqlite3` de Python en lecture seule (la commande `sqlite3` peut ne pas être installée) :

    python3 - <<'PY'
    import sqlite3
    KANBAN_ROOT = '/opt/data'  # ou $HERMES_KANBAN_HOME ; PAS le home d'un profil
    c = sqlite3.connect(f'file:{KANBAN_ROOT}/kanban.db?mode=ro', uri=True)  # board « default »
    for r in c.execute("select id,status,assignee,substr(title,1,60) from tasks order by created_at desc limit 20"):
        print(r)
    PY

Les boards nommés vivent sous `<KANBAN_ROOT>/kanban/boards/<slug>/kanban.db` (le board `default` est `<KANBAN_ROOT>/kanban.db`) ; `<KANBAN_ROOT>/kanban/current` indique le board actif. Le journal d'exécution d'un worker est `<KANBAN_ROOT>/kanban/logs/<task-id>.log` (board `default`) ou `<KANBAN_ROOT>/kanban/boards/<slug>/logs/<task-id>.log` : le lire est le moyen le plus direct de vérifier qu'un worker a trouvé sa spec et ce qu'il écrit. (Chemins vérifiés dans `hermes_cli/kanban_db.py` ; l'ancien `/home/hermes/.hermes` n'existe plus.)

Pendant l'exécution, suivre aussi le dépôt de travail (`git log --oneline`, `git status --short`) : les commits des workers y apparaissent avant que les cartes ne passent `done`.

## Clôture

Quand on délègue, on n'écrit pas soi-même dans le dépôt de travail : la règle commit+push est portée par chaque carte. Si l'orchestrateur a lui-même écrit dans le dépôt, il commite et pousse son propre travail.

## Corrections après le lot

Des ajustements livrés après coup (périodes, périmètre, dates) ne justifient pas de relancer des cartes : éditer directement les fichiers concernés, puis commiter et pousser. Réserver une nouvelle carte à une vraie reprise de traitement.

Une date donnée à la précision du mois (« débuté en novembre 2025 ») ne devient pas un jour précis inventé : poser une ancre explicite (le 1er du mois) et la signaler, ou demander le jour à l'utilisateur.

Si l'information reçue contredit la source déjà citée dans la fiche (début annoncé postérieur au premier message documenté), le signaler et demander plutôt que d'écraser silencieusement.
