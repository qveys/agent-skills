# INVENTAIRE des skills Hermes — partage potentiel

*Généré le 2026-10-24 05:03 — LECTURE SEULE : aucun skill déplacé, copié, modifié ou supprimé. Scripts : `/opt/data/cache/scratch/skills-inventory/01_inventory.py`, `02_analyze.py`, `03_filediff.py`, `04_report.py`.*

Légende : **PROUVÉ** = constat issu d'un script (hash, comptage, grep). **SUPPOSÉ** = jugement humain sur le rôle d'un skill, à valider par l'utilisateur.

## 1. Résumé chiffré (PROUVÉ)

- Skills trouvés (dossier contenant `SKILL.md`) : **729** dans 10 racines (default + 9 profils) ; + 1 skill partagé `shared-skills/supervision/alert-verify` ; + 1 lien symbolique `default/weekly-review` → `/workspace/brain/.agents/skills/weekly-review` (non compté, hors arborescence).
- Par racine : default 90, eclaireur 88, promo-scout 79, lecteur 73, stratege 73, compagnon 71, trader 71, vigie 65, reviseur 61, relecture 58. `code-promo` : 0 skill (uniquement `webui_state`).
- Bundled (manifeste `skills/.bundled_manifest`, 58 entrées, empreinte = md5 du dossier) : **52** identiques au manifeste, **6** modifiés localement (`computer-use`, `hermes-agent`, `claude-design`, `obsidian`, `github`, `systematic-debugging`). Copies bundled dans les profils : 468.
- Hub (`skills/.hub/lock.json`) : 5 skills installés (1password, agent-merge-conflict-arbiter, grill-me, honcho, whisper).
- Non-bundled, toutes racines confondues : **203** entrées (skills locaux ou hub).
- Clés de skill (dossier `catégorie/nom`) : 105 au total ; **92** présentes dans ≥2 racines ; **13** dans une seule.
- Parmi les clés présentes dans ≥2 racines : 57 identiques (même empreinte), 35 divergentes.
- Skills ayant un secret-like détecté par grep : **0 valeur réelle affichée** ; les occurrences sont des noms de variables d'environnement, des exemples `sk-xxx` ou des placeholders (`<masque>`). Revue manuelle des lignes listées par le grep : aucune valeur de credential réelle identifiée (SUPPOSÉ, revue visuelle).
- Méthode d'empreinte : md5 de chaque fichier du dossier (chemin relatif + contenu), trié. Vérifié : cette méthode reproduit exactement le manifeste pour 52 skills sur 58 (les 6 autres sont les modifiés listés ci-dessus).

## 2. Candidats au partage (dossier commun `/opt/data/shared-skills/<catégorie>/`)

Statut : IDENT = même contenu dans toutes les racines ; DIV = contenu divergent (à réconcilier avant partage). `Ref` = version à retenir (la plus récente *et* la plus riche, PROUVÉ par mtime/taille ; le choix final est SUPPOSÉ).

| Skill (rel) | Racines actuelles | Statut | Ref proposée | Catégorie partagée | Blocages à lever | Profils qui en profiteraient |
|---|---|---|---|---|---|---|
| `security/1password` | compagnon, default, eclaireur, lecteur, promo-scout, reviseur, stratege, trader, vigie | IDENT | default | `security/` | op:// d'exemple uniquement (PROUVÉ) ; skill hub-installé → ne pas écraser par mise à jour hub | 9 |
| `devops/kanban-orchestration` | default, eclaireur, lecteur, promo-scout, stratege, trader | DIV | default | `devops/` | chemins `/workspace/*` (3) et HERMES_HOME ; 3 copies anciennes (lecteur, stratege, trader) à remplacer | 6 |
| `devops/kanban-worker-dispatch` | default, eclaireur, lecteur, promo-scout, stratege, trader | DIV | default | `devops/` | `/home/hermeswebui` (chemin conteneur) et `/workspace/*` (7) | 6 |
| `devops/kanban-batch-recovery` | default, eclaireur, promo-scout | IDENT | default | `devops/` | marqué `stale` (curator) dans default | 3 |
| `devops/multi-container-services` | default, eclaireur, lecteur, promo-scout, stratege, trader | IDENT | default | `devops/` | aucun (SUPPOSÉ) ; `stale` dans plusieurs copies | 6 |
| `devops/native-lib-load-recovery` | default, eclaireur | IDENT | default | `devops/` | chemin `/workspace/.qmd/libshim` (spécifique à cette instance) | 2 |
| `devops/hermes-gateway-lifecycle` | default, eclaireur | IDENT | default | `devops/` | aucun constat bloquant | 2 |
| `devops/hermes-desktop-gateway-connections` | default, eclaireur | IDENT | default | `devops/` | aucun constat bloquant | 2 |
| `devops/cron-script-recovery` | default, eclaireur, lecteur, promo-scout, stratege, trader | DIV | default | `devops/` | exemples `/opt/data/scripts/cron-x.sh` et `/workspace/brain` (à rendre génériques) | 6 |
| `devops/hermes-cron-jobs` | default, eclaireur, lecteur, promo-scout, stratege, trader | DIV | default | `devops/` | `/opt/data/scripts`, `/opt/data/workspace` (4-5) ; `references/veille-techno-pattern.md` cite `eclaireur-cycle.sh` → à retirer du partage | 6 |
| `devops/hermes-plugin-env-config` | default, eclaireur, lecteur, promo-scout, stratege, trader | DIV | default | `devops/` | `/home/hermeswebui` (2), `/workspace` (1) | 6 |
| `devops/hermes-secret-sources` | default, eclaireur | DIV | default | `devops/` | op:// placeholders uniquement ; nécessite relecture (mentionne le coffre) | 2 |
| `devops/service-api-onboarding` | default, eclaireur | DIV | default | `devops/` | aucun constat bloquant (DIV de 1 fichier) | 2 |
| `devops/readonly-audit` | default, eclaireur, promo-scout | DIV | default | `devops/` | `/workspace/*` (9) et `references/deployment-layout.md` (spécifique au serveur) | 3 |
| `hermes-profile-creation` | default, eclaireur, promo-scout | DIV | default | `devops/` | chemins de profils (HERMES_HOME). Skill à ranger sous devops/ (aujourd'hui à la racine) | 3 |
| `hermes-profile-isolation` | default, eclaireur, promo-scout | DIV | default | `devops/` | `/opt/data/.op.env` (chemin de fichier secret, pas de valeur) ; copies eclaireur/promo-scout plus anciennes | 3 |
| `software-development/git-worktree-workflow` | default, eclaireur, lecteur, promo-scout, stratege, trader | DIV | default | `software-development/` | HERMES_HOME dans `references/worktree-isolation-in-hermes.md` | 6 |
| `software-development/grill-me` | default, eclaireur | IDENT | default | `software-development/` | aucun ; hub-installé ; 0 usage enregistré | 2 |
| `software-development/llm-chat-api-calls` | default | IDENT | default | `software-development/` | aucun ; présent seulement dans default (SUPPOSÉ utile à d'autres) | 1 |
| `software-development/systematic-debugging` | compagnon, default, eclaireur, lecteur, promo-scout, relecture, reviseur, stratege, trader, vigie | DIV | default | `software-development/` | bundled-modifié dans default : Ref=default (+17 lignes) | 10 |
| `software-development/github` | compagnon, default, eclaireur, lecteur, promo-scout, relecture, reviseur, stratege, trader, vigie | DIV | default | `software-development/` | bundled-modifié : chemin `/opt/data/bin/hermes-gh-token` (chemin du conteneur) | 10 |
| `note-taking/obsidian-vault-health` | default, eclaireur, lecteur, promo-scout, stratege, trader | IDENT | default | `note-taking/` | références au vault Second-Cerveau à vérifier (SUPPOSÉ) | 6 |
| `note-taking/obsidian` | compagnon, default, eclaireur, lecteur, promo-scout, relecture, reviseur, stratege, trader, vigie | DIV | default | `note-taking/` | bundled-modifié ; la copie vigie est plus riche (default→vigie : +21/-2 lignes) → à réconcilier | 10 |
| `autonomous-ai-agents/honcho` | compagnon, default, eclaireur | DIV | compagnon | `autonomous-ai-agents/` | hub-installé ; compagnon porte la version la plus récente (+6 lignes) | 3 |
| `autonomous-ai-agents/agent-merge-conflict-arbiter` | default, eclaireur, lecteur, promo-scout, stratege, trader | IDENT | default | `autonomous-ai-agents/` | hub-installé ; identique dans 6 racines — partager = sortir du cycle hub | 6 |
| `mlops/whisper` | default, eclaireur | IDENT | default | `mlops/` | hub-installé ; 0 usage enregistré | 2 |
| `devops/kanban-tasks` | compagnon, vigie | DIV | compagnon | `devops/` | DIV (1 fichier) : Ref=compagnon | 2 |
| `workspace-debug-script-guard` | default, eclaireur, lecteur, promo-scout, reviseur, stratege | DIV | default | `devops/` | DIV : Ref=default ; `/workspace/brain` et `/workspace/trading` (17-20 occurrences) à rendre génériques | 6 |
| `deleguer-sous-agents` | compagnon, vigie | DIV | compagnon | `autonomous-ai-agents/` | DIV : Ref=compagnon ; chemins `/workspace/brain` (3) à rendre génériques | 2 |

## 3. Divergences à réconcilier (PROUVÉ, fichiers différents vs la Ref)

| Skill | Ref | Fichiers différents (nb racines) | Racines en retard / différentes |
|---|---|---|---|
| `autonomous-ai-agents/claude-code` | default | `SKILL.md` (3) | lecteur, promo-scout, reviseur |
| `autonomous-ai-agents/computer-use` | default | `SKILL.md` (9) | compagnon, eclaireur, lecteur, promo-scout, relecture, reviseur, stratege, trader, vigie |
| `autonomous-ai-agents/hermes-agent` | default | `SKILL.md` (9), `references/background-systems.md` (2), `references/cli-reference.md` (4), `references/configuration.md` (4) … | compagnon, eclaireur, lecteur, promo-scout, relecture, reviseur, stratege, trader, vigie |
| `autonomous-ai-agents/honcho` | default | `SKILL.md` (1) | compagnon |
| `creative/baoyu-infographic` | default | `PORT_NOTES.md` (3), `SKILL.md` (3), `references/layouts/bento-grid.md` (1), `references/layouts/binary-comparison.md` (1) … | lecteur, promo-scout, reviseur, trader |
| `creative/claude-design` | default | `SKILL.md` (9) | compagnon, eclaireur, lecteur, promo-scout, relecture, reviseur, stratege, trader, vigie |
| `deleguer-sous-agents` | compagnon | `SKILL.md` (1) | vigie |
| `devops/cron-script-recovery` | default | `SKILL.md` (5) | eclaireur, lecteur, promo-scout, stratege, trader |
| `devops/dokploy-vps` | default | `SKILL.md` (1), `references/network-topology.md` (1) | eclaireur |
| `devops/hermes-cron-jobs` | default | `SKILL.md` (5), `references/deploiement-stockage.md` (1), `references/diagnostic-livraison.md` (5), `references/veille-techno-pattern.md` (5) | eclaireur, lecteur, promo-scout, stratege, trader |
| `devops/hermes-plugin-env-config` | default | `SKILL.md` (4) | lecteur, promo-scout, stratege, trader |
| `devops/hermes-secret-sources` | default | `SKILL.md` (1), `references/git-credentials-1password.md` (1) | eclaireur |
| `devops/kanban-orchestration` | default | `SKILL.md` (5), `references/chain-dispatch-mapping.md` (3), `references/post-dispatch-cleanup-script.md` (3) | eclaireur, lecteur, promo-scout, stratege, trader |
| `devops/kanban-tasks` | compagnon | `SKILL.md` (1) | vigie |
| `devops/kanban-worker-dispatch` | default | `SKILL.md` (3), `scripts/kanban_fix_stale_completion.py` (3) | lecteur, stratege, trader |
| `devops/readonly-audit` | default | `references/deployment-layout.md` (2), `SKILL.md` (1) | eclaireur, promo-scout |
| `devops/service-api-onboarding` | default | `SKILL.md` (1) | eclaireur |
| `hermes-profile-creation` | default | `SKILL.md` (2) | eclaireur, promo-scout |
| `hermes-profile-isolation` | default | `SKILL.md` (2) | eclaireur, promo-scout |
| `media/youtube-content` | default | `scripts/fetch_transcript.py` (3) | lecteur, promo-scout, reviseur |
| `note-taking/obsidian` | default | `SKILL.md` (9), `references/vault-backup-audit.md` (1) | compagnon, eclaireur, lecteur, promo-scout, relecture, reviseur, stratege, trader, vigie |
| `productivity/brain-review-automation` | default | `SKILL.md` (5) | eclaireur, lecteur, promo-scout, stratege, trader |
| `productivity/docx` | default | `scripts/docx_comments.py` (3), `scripts/docx_common.py` (3), `scripts/docx_revisions.py` (3), `scripts/docx_validate.py` (3) … | lecteur, promo-scout, reviseur |
| `productivity/google-workspace` | default | `scripts/_hermes_home.py` (3), `scripts/google_api.py` (3), `scripts/gws_bridge.py` (3) | lecteur, promo-scout, reviseur |
| `productivity/pdf` | default | `SKILL.md` (1), `scripts/_raster.py` (3), `tests/test_pdf_skill.py` (3) | compagnon, lecteur, promo-scout, reviseur |
| `productivity/powerpoint` | default | `scripts/pptx_edit.py` (3), `scripts/pptx_from_template.py` (3), `scripts/pptx_render.py` (3), `tests/test_powerpoint_skill.py` (3) | lecteur, promo-scout, reviseur |
| `productivity/xlsx` | default | `scripts/csv_to_xlsx.py` (3), `scripts/xlsx_create.py` (3), `scripts/xlsx_edit.py` (3), `scripts/xlsx_read.py` (3) … | lecteur, promo-scout, reviseur |
| `research/grounded-citations` | default | `scripts/_hermes_home.py` (3), `scripts/sources.py` (3) | lecteur, promo-scout, reviseur |
| `software-development/git-worktree-workflow` | default | `SKILL.md` (5), `references/repo-owned-gates.md` (3) | eclaireur, lecteur, promo-scout, stratege, trader |
| `software-development/github` | default | `SKILL.md` (9), `references/auth.md` (9) | compagnon, eclaireur, lecteur, promo-scout, relecture, reviseur, stratege, trader, vigie |
| `software-development/hermes-agent-skill-authoring` | default | `SKILL.md` (3) | lecteur, promo-scout, reviseur |
| `software-development/systematic-debugging` | default | `SKILL.md` (9) | compagnon, eclaireur, lecteur, promo-scout, relecture, reviseur, stratege, trader, vigie |
| `sync-profile-skills` | compagnon | `SKILL.md` (1) | vigie |
| `traitement-export` | compagnon | `SKILL.md` (1), `references/facebook.md` (1), `references/imessages.md` (1) | vigie |
| `workspace-debug-script-guard` | default | `SKILL.md` (5) | eclaireur, lecteur, promo-scout, reviseur, stratege |

Lecture : `diff` résumé de SKILL.md (ex. `hermes-cron-jobs` : +82/-62 lignes entre default et eclaireur) disponible dans `analysis.json` (clé `div`).

## 4. Skills à garder locaux (spécifiques à un rôle ou à un vault) — SUPPOSÉ

| Skill | Racines | Motif |
|---|---|---|
| `archives-conversations` | compagnon | export Facebook / Second-Cerveau |
| `revision-fiche-personne` | compagnon | fiches Personne du vault |
| `traitement-export` | compagnon, vigie (DIV) | export personnel |
| `vault/inbox-triage` | compagnon | vault personnel |
| `vault-skill-sync` | compagnon, vigie | synchronisation vault (chemins /workspace/brain) |
| `sync-profile-skills` | compagnon, vigie | outil de sync entre profils, chemins de profil en dur — à revoir plutôt qu'à partager |
| `eclaireur-veille` | eclaireur | rôle Éclaireur |
| `research/promo-code-hunting` | promo-scout | rôle promo-scout |
| `research/trading-pdf-reading` | default, eclaireur, lecteur, promo-scout, reviseur (IDENT) | collectif trading ; `/workspace/trading` (9) — partageable seulement après paramétrage |
| `productivity/brain-review-automation` | 6 racines (DIV) | vault Second-Cerveau |
| `weekly-review` | eclaireur, lecteur, promo-scout, stratege, trader (IDENT) ; default = lien symbolique | rituel perso ; **homonyme** du skill `weekly-review.backup` et d'un skill externe (cf. prompt système) → renommer avant tout partage |
| `devops/dokploy-vps` | default, eclaireur (DIV) | items 1Password serveur-spécifiques (IDs) → garder local |
| `devops/hermes-database-maintenance` | compagnon | chemins `/opt/data/kanban/boards` et `/workspace` |
| `devops/git-divergence` | compagnon | candidat générique possible (SUPPOSÉ) : à relire |
| `devops/backup-safety-audit` | vigie | audit de sauvegardes (SUPPOSÉ supervision) : à garder chez vigie |
| `devops/kanban-tasks` | compagnon, vigie | à réconcilier avant tout |
| `research/qmd` | compagnon | voir archivage |

## 5. Candidats à l'archivage (PROUVÉ = compteurs ; décision SUPPOSÉ)

- `weekly-review.backup` (default) : dossier de sauvegarde d'un skill homonyme ; 0 usage.
- `research/qmd` (compagnon) : 0 usage, état active, aucun doublon.
- `autonomous-ai-agents/honcho` : 0 usage dans les 3 racines (default, compagnon, eclaireur) ; hub-installé → vérifier avant retrait.
- `mlops/whisper`, `software-development/grill-me` : 0 usage (default/eclaireur) ; hub-installés → vérifier avant retrait.
- `corpus-synthesis`, `devops/kanban-batch-recovery`, `note-taking/obsidian-vault-health`, `devops/kanban-orchestration`, `devops/multi-container-services` : marqués `stale` par le curateur dans ≥1 racine (PROUVÉ, `.usage.json`).
- Copies anciennes à remplacer (même nom, version antérieure) : à traiter avec la réconciliation de la section 3 plutôt qu'en archivage.

Caveat : le compteur `use_count` est celui de `.usage.json` ; il ne couvre que la période où le suivi existe, et un skill chargé par un cron peut être légitime sans usage visible.

## 6. Proposition d'`external_dirs` par profil (SUPPOSÉ, à valider)

Règle de résolution (énoncé de la tâche, non re-vérifiée dans le code Hermes) : un skill local masque un partagé de même nom. Donc, pour qu'un skill partagé prenne effet, il faut **retirer** la copie locale identique (étape à faire seulement après validation, et en gardant la sauvegarde). Les copies *bundled* ne doivent pas être retirées : elles sont réinstallées par la synchronisation bundled.

```yaml
# proposition — profils default et vigie (ont déjà supervision)
skills:
  external_dirs:
    - /opt/data/shared-skills/supervision
    - /opt/data/shared-skills/devops
    - /opt/data/shared-skills/security
    - /opt/data/shared-skills/software-development
    - /opt/data/shared-skills/note-taking
    - /opt/data/shared-skills/research        # seulement corpus-synthesis
    - /opt/data/shared-skills/autonomous-ai-agents  # honcho, deleguer-sous-agents après réconciliation
# autres profils (eclaireur, lecteur, promo-scout, relecture, reviseur, stratege, trader, compagnon)
#   même liste SAUF supervision ; lecteur/stratege/trader/promo-scout/reviseur : ajouter research/trading-pdf-reading après paramétrage des chemins /workspace/trading
```

Les dossiers `devops/`, `security/`, `software-development/`, `note-taking/`, `research/`, `autonomous-ai-agents/` n'existent pas encore sous `/opt/data/shared-skills/` : à créer après validation (rien n'a été déplacé).
Note : le dossier `external_dirs` est déclaré au niveau `skills.external_dirs` dans `config.yaml` (confirmé dans `default` et `vigie`). Les autres profils n'ont pas de bloc `external_dirs` ; l'ajout se fait dans leur `config.yaml`, après validation.

## 7. Profils qui en profiteraient (SUPPOSÉ)

- **eclaireur** (88 skills, le plus de skills) : devops/*, security/1password, software-development/*, note-taking/obsidian-vault-health.
- **promo-scout** (79), **lecteur** / **stratege** / **trader** (73/73/71) : devops/* (Kanban, cron, env-config) et security/1password ; research/trading-pdf-reading une fois les chemins paramétrés.
- **relecture** (58), **reviseur** (61) : security/1password, software-development/*.
- **compagnon** (71), **vigie** (65) : security/1password, devops/* ; vigie reçoit déjà supervision.

## 8. Points d'attention

- `hub` : 5 skills gérés par le hub (1password, agent-merge-conflict-arbiter, grill-me, honcho, whisper). Les partager hors du hub peut casser leurs mises à jour.
- Profil `code-promo` : 0 skill. `profiles/.deleted/` contient des restes (`webui-dev`, `code-promo`) : hors inventaire.
- Les copies de profils ont souvent des versions *plus anciennes* que default (mtimes de septembre) : la réconciliation doit partir de default lorsque c'est la version la plus à jour.

