---
name: kanban-tasks
description: "Use when kanban_* tools are absent: CLI task lifecycle."
version: 1.1.0
author: Hermes Agent
license: MIT
triggers: ["kanban", "task_board", "board", "complete the task", "kanban task"]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [kanban, devops, cli, task-management]
    related_skills: [hermes-agent, kanban-orchestration, kanban-worker-dispatch]
---

# kanban-tasks

## When to Use

- The interface does not inject the `kanban_*` function tools (TUI, CLI, headless runs), but the `hermes kanban` CLI binary is available at `/opt/hermes/bin/hermes` (not always on default PATH). Set `HERMES_HOME` to the profile path before invoking (`/opt/hermes/libexec/hermes` also exists):
```bash
HERMES_HOME=/opt/data/profiles/<profile> /opt/hermes/bin/hermes kanban <subcommand> ...
```
- Le partage des boards passe par `HERMES_KANBAN_HOME` (racine Hermes partagée), PAS par `HERMES_HOME` : la résolution lit `HERMES_KANBAN_HOME` sinon la racine par défaut. Si `boards list` n'affiche que `default` alors que les outils fonction voient d'autres boards, la CLI résout une autre racine que le runtime — préfixer les appels de la vraie racine (`HERMES_KANBAN_HOME=/opt/data` sur ce runtime) au lieu de réessayer à l'identique.
- `--board <slug>` est un flag **global placé AVANT la sous-commande** (`hermes kanban --board facebook show t_x`) ; placé après (`show t_x --board facebook`) il échoue sur « unrecognized arguments » (vérifié sur la CLI). Alternative : l'env var `HERMES_KANBAN_BOARD=<slug>` pour un appel ponctuel, ou `boards switch` pour une session interactive.
- You need to orient, block, unblock, comment, or complete a kanban task.
- You have a task ID (`t_<hex>`) and need to move it through the lifecycle without a live function interface.

## Procédure

### 1. S'orienter sur la bonne board
La CLI `hermes kanban` opère sur la board active du profil, qui n'est pas forcément celle où la tâche vit. Toujours vérifier et basculer si besoin :

```bash
hermes kanban boards list          # liste les boards et la board active
hermes kanban boards switch <slug> # change de board (ex: brain, default, trading)
```

Pour un appel ponctuel, préférer l'env var à `switch` : `HERMES_KANBAN_HOME=<root> HERMES_KANBAN_BOARD=<slug> hermes kanban ...`. Créer une board dédiée à un gros chantier (`boards create <slug>`) évite que ses cartes se mélangent au flux quotidien des autres boards.

Le slug de la board est dans le `worker_context` retourné par `kanban_show()`.

### 2. S'orienter sur la tâche
Toujours commencer par lire l'état complet AVANT d'agir :

```bash
hermes kanban show t_<id>          # affiche statut, commentaires, événements, runs
```
Depuis la fonction : `kanban_show(task_id=...)` retourne `body`, `worker_context`, `comments`, `events`, et `runs`.

### 3. Créer et déléguer une tâche (kanban_create)
Depuis la fonction : crée une tâche assignée à un profil, avec des enfants éventuels et des skills force-loaded :

```python
kanban_create(
    title="...",
    assignee="<profil>",
    body="...",
    parents=["t_parent"],     # enfants débloqués quand le parent est done
    skills=["<skill>"],       # force-charge le skill dans le sous-agent dispatché
    workspace_kind="scratch",
)
```

Le paramètre `skills` force le chargement d'une skill dans le sous-agent dispatché, même si le corps de la tâche ne la mentionne pas. C'est la manière fiable de garantir que chaque sous-agent travaille avec la bonne skill.

> **Parent task pitfall** : si le parent est assigné au même profil que celui qui le crée, le dispatcher peut le dispatcher, et l'agent peut ré-exécuter les instructions de création d'enfants → doublons. Force-compléter le parent via CLI juste après la création (`hermes kanban complete --force <id> --summary "<texte>"`) avant son dispatch, ou garder le body du parent comme metadata-only (aucune instruction exécutable).

### 3bis. Création en lot et filiation (CLI)

Quand un chantier demande des dizaines de cartes liées (une carte par élément + une carte de relecture enfant chacune), la CLI en boucle bat l'outil fonction appelé une par une :

```bash
# corps multi-ligne via stdin ; --parent répétable
echo "$body" | HERMES_KANBAN_HOME=<root> HERMES_KANBAN_BOARD=<slug> \
  hermes kanban create "Titre" --assignee <profil> --parent "$tid" --body-file -
```

- `--parent` est répétable : plusieurs parents gate la carte jusqu'au `done` de tous.
- Chaque appel CLI affiche « 1Password: applied N secrets » et coûte ~5 s : un lot de 30-50 cartes dépasse le timeout avant-plan de 300 s — lancer la boucle en `background=true` avec `notify=true`, pas en foreground.
- `kanban list --json` n'accepte PAS `--limit` (contrairement à l'outil fonction) : filtrer côté Python ; `--assignee <profil>` fonctionne.
- Lister l'existant AVANT de créer par lot et sauter les titres déjà couverts — un script tué puis relancé, ou un zombie qui finit tardivement, recrée tout son lot. Après coup : dédoublonner par titre (garder la plus ancienne) et `kanban archive <id>` les doublons.

### 4. Faire traiter un commentaire sur une tâche terminée
Un commentaire sur une carte `done` conserve une consigne dans le fil, mais ne relance pas la tâche et ne déclenche pas son exécution. Pour garantir le suivi, crée une carte de reprise distincte, assignée au profil chargé de la relecture, et lie les cartes terminées concernées comme parents. Regroupe-les en une seule carte si le périmètre de relecture est cohérent; détaille les livrables à inspecter, les critères de correction et le compte rendu attendu. Garde les cartes originales en `done` afin de préserver leur historique, puis relis la nouvelle carte pour vérifier son assignation, son statut et ses liens.

### 5. Bloquer (needs_input)
Quand une entrée humaine est requise, bloquer avec `kind=needs_input` :

Depuis la fonction : `kanban_block(task_id=t_xxx, kind="needs_input", reason="...")`
Depuis la CLI :
```bash
hermes kanban block t_<id> --kind needs_input --reason "..."
```
Le motif doit pointer vers l'artefact qui porte la question (ex: le chemin d'un brief).

### 6. Débloquer après réponse
Après qu'un commentaire réponse est apparu (vérifié via `show`) :

Depuis la CLI :
```bash
hermes kanban unblock t_<id>
```
Depuis la fonction : `kanban_unblock(task_id=...)` (si disponible).

### 7. Compléter
Écrire la réponse dans l'artefact, puis compléter :

```bash
hermes kanban complete t_<id> \
  --summary "<résumé 5 lignes max>" \
  --metadata '{"decision": "GO", "checks": {...}, ...}' \
  --force
```

## Pièges

- **Board par défaut trompeuse** : la CLI peut être sur une board différente de celle de la tâche. `show` échoue avec « no such task ». Vérifier `boards list` et `switch` avant de toute opération. Ce n'est pas un défaut de la tâche, c'est un board mismatch.
- **`--force` pour les tâches still claimed** : si le worker run est toujours `claimed`/`running` (le worker a disparu sans libérer), `complete` sans `--force` échoue avec une erreur de live-claim guard. `--force` contourne ce garde-fou et ferme le run.
- **Metadata en JSON valide** : passer `--metadata` avec une chaîne JSON correctement échappée en bash (doubles guillemets externes, simples guillemets internes, ou `--metadata` avec un fichier). Un JSON cassé échoue silencieusement ou invalide la complétion.
- **Summary max 5 lignes** : le résumé est lisible par les humains et les agents en aval. Le garder concis.
- **Pas de données sensibles dans les commentaires/metadata** : ils sont durables et stockés dans la base SQLite partagée par tous les profils — jamais de PII, de tokens ou de données personnelles.


- **Completed tasks may auto-reset to ready** : An automated reviewer may re-queue completed tasks for a re-read pass (anti-redundancy check, coquille verification). Expect some tasks to cycle `done → ready → running → done` and do not treat the first completion as final.

- **A comment added after the claim is never read** : a dispatched worker reads the card's comment thread only when it is claimed. A comment posted while the card is already `running` is not seen by the current run. To guarantee a late constraint is applied, either put it in the `body` at creation, or comment while the card is still `todo`/gated by an unfinished parent — a gated card is promoted to `ready` later and reads the thread at claim time. Do not rely on commenting a live card to steer it.

- **Statut ouvert n'est pas un worker.** Seul `running` signifie qu'un agent est dessus. `review` attend un verdict et ne se relance pas. `todo` avec un parent non `done` reste gate. `ready` depuis des heures avec `running` à 0 dans `kanban stats` n'est pas pris. Avant de dire qu'une file avance, lire `kanban stats`. Ne pas `complete` une carte parce qu'elle est la dernière ouverte : le livrable nommé doit exister sur disque (chercher aussi un renommage git), et une relecture dont le dernier verdict est non conforme reste ouverte tant que les phrases citées sont encore dans le fichier. Pour la faire bouger quand on est l'assigné : corriger ces phrases, puis `complete`. Clore une carte `review` dont le livrable existe promeut l'enfant `todo`.

- **Fan-out that overlaps writes must be serialized** : when several cards of the same profile edit the same files (shared fiches, a journal, a landscape note) or push to the same git repo, running them in parallel corrupts the output — last-writer-wins on shared files, and concurrent pushes race. Chain them with parents (`t2.parents=[t1]`, `t3.parents=[t2]`, …) so each worker starts only after the previous one has committed; each child stays in `todo` until its parent is `done`, then auto-promotes. Chain the whole lot if every card writes a shared side file, not only the cards whose primary targets overlap. Order the chain so the broadest, most aggregating source runs last, so its rebuild wins for the files it shares with narrower sources. Use `--parent` and `--idempotency-key` (the source path) so a restarted create loop does not duplicate. `show --json` can omit parent links : read the text `show` before concluding a card is unlinked. A `done` summary is not proof : the named file must have moved or changed, and a multi-thousand-message card closed in minutes is a signal to recoup the quotes.

## Références
- `hermes kanban --help` et `hermes kanban <subcommand> --help` pour les options détaillées.
- `kanban-orchestration` (routage, boards, dispatch) et `kanban-worker-dispatch` (diagnostic d'un worker muet).
- `hermes-agent` : skill hub, `references/background-systems.md` couvre la théorie du kanban (delegation, cron, curator).
