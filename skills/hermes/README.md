# Skills Hermes

Skills propres aux agents [Hermes](https://hermes-agent.nousresearch.com/docs), partagés entre tous les profils d'une instance.

Structure : `skills/hermes/<catégorie>/<skill>/SKILL.md`

| Catégorie | Contenu |
|---|---|
| `devops/` | Kanban, cron, profils, secrets, sauvegardes, Git |
| `software-development/` | Worktrees, scripts jetables, outillage de dev |
| `autonomous-ai-agents/` | Délégation à des sous-agents |
| `note-taking/` | Synchronisation des skills du vault |
| `supervision/` | Vérification d'alertes Grafana |

Consommation par Hermes : cloner ce dépôt sur le serveur et déclarer **ce dossier seulement** dans `skills.external_dirs` de chaque profil (`/opt/data/agent-skills/skills/hermes`). Hermes parcourt les sous-dossiers et utilise le dossier parent comme catégorie. Ne pas déclarer `skills/` ni la racine : les skills non Hermes, `vendor/` et `_template` seraient chargés aussi.

Ajouter une skill : la placer dans la catégorie existante la plus proche (en créer une seulement si aucune ne convient), via une PR comme pour le reste du dépôt.
