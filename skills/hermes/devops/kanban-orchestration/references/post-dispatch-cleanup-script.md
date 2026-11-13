# Post-dispatch cleanup — script `kanban_post_dispatch.py`

Le projet `trading` dispose d'un script de post-dispatch qui matérialise la procédure « Cartes à archiver » du SKILL.md :

- **Emplacement** : `<projet>/tools/kanban_post_dispatch.py` (ex. `/workspace/trading/tools/kanban_post_dispatch.py`, présent sur cette instance).
- **Modes** : `--dry-run` (audit sans modification) ou mode réel.
- **Cible** : un board (`--board trading`) ou une tâche unique (`--task t_XXXX`).

## Quand l'utiliser

- Après un gros dispatch (≥ 20 cartes), pour ramasser les commentaires « annulation nécessaire » oubliés.
- Avant une nouvelle vague, pour vérifier qu'aucune carte ne traîne avec un hash inventé dans le body.
- En cron `no_agent` toutes les 10-15 min pendant une vague active.

## Conventions à respecter dans les commentaires

Le script scanne les threads et applique deux règles :

1. **Marqueur d'annulation** : un commentaire commençant par `**Annulation nécessaire** :` déclenche l'archivage. Pour pointer vers un remplaçant, inclure `remplacement: t_XXXX` dans le corps.
2. **Marqueur de rétractation** : un commentaire commençant par `**Rétractation**` postérieur à l'annulation **annule** l'effet — la carte n'est pas archivée. Toujours rétracter explicitement les fausses alertes plutôt que d'effacer le commentaire d'origine (le thread conserve l'historique).

## Diagnostic d'un `rc=0 protocol violation` récurrent

Le script ne corrige pas ce cas — pour le diagnostic, sortir du script et inspecter la base :

```python
import sqlite3
conn = sqlite3.connect('<KANBAN_ROOT>/kanban/boards/<board>/kanban.db')
cur = conn.cursor()
cur.execute("""
    SELECT id, started_at, ended_at, error FROM task_runs
    WHERE task_id = ? ORDER BY id
""", ('t_XXXX',))
for row in cur.fetchall():
    print(row)
```

Si plusieurs runs se succèdent en ~60-120s et crasent tous avec `crashed/crashed`, c'est un **timeout** (`terminal.timeout` ou `runtime.lifetime_seconds`), pas un worktree. Voir la ligne correspondante dans la section « Pièges qui coûtent du temps » du SKILL.md pour le correctif profil.

## Anti-patterns

- **Lancer le script sans `--dry-run` la première fois** sur un board inconnu : toujours un audit avant l'action, surtout si le board a des commentaires anciens qui n'avaient pas vocation à être scannés comme « annulation ».
- **Confondre « Annulation nécessaire » avec « Rétractation »** dans le même thread : le marqueur temporel compte, pas l'ordre textuel. Si on rétracte avant d'avoir annulé, l'annulation postérieure sera respectée par le script.
