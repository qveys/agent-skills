# Dispatch en chaîne — schéma du mapping et procédure de reprise

## Schéma canonique du mapping (Chaîne 3 tiers : Lecteur → Réviseur → Stratège)

Quand un orchestrateur dispatche un lot où chaque source suit une chaîne multi-tiers avec gates d'audit (`lecteur` → `reviseur` → `stratege` → `audit` → `consolidation`), il exporte un artefact complet dans `out/_stray/<timestamp>/` :

```json
{
  "timestamp": "20260926-080117",
  "unique_sources_count": 156,
  "reader_tasks_count": 156,
  "reviewer_tasks_count": 156,
  "strategist_tasks_count": 156,
  "audit_reader_task_id": "t_e7b9dd41",
  "audit_strategist_task_id": "t_5216afac",
  "consolidation_task_id": "t_99e7fddd",
  "corpus_report_task_id": "t_82aa7b6a",
  "sources": [
    {
      "sha256": "b2fa19d4... (64 hex)",
      "filename": "20230806-comment-ouvrir-un-trade-sur-mt4-...txt",
      "duplicates": [],
      "reader_task_id": "t_08a4896b",
      "reviewer_task_id": "t_939c615d",
      "strategist_task_id": "t_be716733",
      "audit_reader_task_id": "t_e7b9dd41",
      "audit_strategist_task_id": "t_5216afac",
      "consolidation_task_id": "t_99e7fddd",
      "corpus_report_task_id": "t_82aa7b6a"
    }
  ]
}
```

Conventions :
- **Indexé par hash canonique** (64 hex), pas par filename — les doublons par nom de fichier sont fréquents et le hash tranche.
- **Tableau sous clé `"sources"`**, avec métadonnées globales de campagne (IDs des gates d'audit et de consolidation).
- **Toujours horodater le répertoire** : `out/_stray/<YYYYMMDD-HHMMSS>/corpus_pass2_kanban_map.json`.
- **Création en lot rapide** : utiliser `/opt/hermes/.venv/bin/python` et importer `hermes_cli.kanban_db` (`create_task`, `link_tasks`, `recompute_ready`) pour instancier des centaines de cartes atomiquement sans dizaines d'allers-retours séquentiels.

## Détection de doublons après dispatch

```python
from collections import defaultdict
groups = defaultdict(list)
for entry in mapping:
    groups[entry["sha256"]].append(entry)
collisions = {h: entries for h, entries in groups.items() if len(entries) > 1}
if collisions:
    # deux cartes ou plus traitent le même livre — investiguer avant de relancer
```

Une collision valide (deux paths équivalents dans l'inventaire qui résolvent au même hash) → on garde la carte de reader la plus avancée (statut `done`) et on archive l'autre. Une collision invalide (même hash déclaré, deux fichiers PDF distincts) → fiche inventaire à corriger.

## Procédure de reprise depuis l'artefact

Si le board est reconstruit ou si la chaîne se casse au milieu, l'artefact permet de rejouer la suite sans recalculer :

1. Charger `_dispatch_history_<date>.json`.
2. Pour chaque entrée où `strat_task_id is None` et `already_done == false` : créer la carte `stratege` enfant du reader avec `parents=[entry["reader_task_id"]]` et `priority = priority_base - len(done)`.
3. Pour chaque entrée avec collision : choisir la carte reader canonique (statut `done` ou hash du body == entry.sha256), archiver les autres avec `kanban_complete(summary="doublon de <canonique>")`.

## Anti-patterns

- **Indexer le mapping par task_id** au lieu du hash : perd toute valeur au premier redémarrage, les task_ids sont régénérés.
- **Écrire seulement dans `out/`** sans miroir dans `knowledge/` : `out/` est décrit dans STRUCTURE.md comme « jetable » ; perdre l'artefact au prochain cron `disk-cleanup` rend la chaîne opaque.
- **Oublier de mettre à jour `strat_task_id`** après création de la carte enfant : à la vague suivante, on re-crée la stratège en double. La procédure de création doit inclure `strat_task_id = kanban_create(...)["task_id"]` immédiatement, et l'artefact réécrit avant le `kanban_create` suivant.
