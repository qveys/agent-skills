# Pattern veille-techno — cron job avec LLM

> Exemple tiré du projet `/workspace/veille-techno` (présent sur cette instance, nommé « Éclaireur »). Les noms de fichiers sont illustratifs : transposer à son propre projet.

Exemple concret de job Hermes `no_agent=true` qui exécute un cycle de veille technologique complet.

## Structure

```
/workspace/veille-techno/
├── scripts/
│   ├── cycle.py              # point d'entrée CLI (argparse)
│   └── eclaireur-cycle.sh    # wrapper cron (copié dans $HERMES_HOME/scripts/)
├── eclaireur/
│   ├── collectors/           # GitHub, HackerNews, RSS, YouTube
│   ├── extract.py            # publication → technologies (LLM)
│   ├── score.py              # scoring multi-axes + diversité
│   ├── pipeline.py           # orchestration + journal runs
│   ├── learn.py              # apprentissage feedbacks
│   ├── memorize.py           # « Conserver » → Obsidian + Git
│   ├── sources.py            # gestion sources CRUD + discover + OPML
│   └── web/app.py            # FastAPI (port 9470)
├── data/veille.db            # SQLite WAL + FTS5
└── tests/
```

## Wrapper cron (`eclaireur-cycle.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO="/workspace/veille-techno"
PY="/opt/hermes/.venv/bin/python"
LOG="$REPO/data/cycle.log"
cd "$REPO"
{
  echo "=========================================="
  echo "ÉCLAIREUR — cycle $(date '+%Y-%m-%d %H:%M')"
  echo "=========================================="
  "$PY" scripts/cycle.py --max-collect 120 --max-extract 12 --max-score 8
} >> "$LOG" 2>&1
tail -n 12 "$LOG"
```

## Job cron Hermes

```bash
cronjob_manage action=create \
  name="Éclaireur — cycle de veille (quotidien 04h)" \
  schedule="0 4 * * *" \
  script="eclaireur-cycle.sh" \
  workdir="/workspace/veille-techno" \
  no_agent=true \
  deliver="local"
```

## Points clés reproduits

- **Idempotence** : hash SHA1 `canonical:external_id` pour les publications
- **Backfill ≤ 365j** : respecté dans chaque collecteur
- **LLM robuste** : retry 429/5xx, fallback modèle, JSON réparé, max_tokens adaptatif pour modèles raisonnants (≥8000 pour stepfun/step-5-preview)
- **Base SQLite** : WAL + FTS5, migrations idempotentes, FK enforcement
- **Sécurité** : defusedxml pour RSS/YouTube (anti-XXE), secrets lus au runtime depuis auth.json
- **Tests** : 26 tests unitaires + intégration (pipeline, web, apprentissage, mémorisation, sources)

## Après recréation du conteneur

1. Recopier le wrapper : `cp /workspace/veille-techno/scripts/eclaireur-cycle.sh $HERMES_HOME/scripts/eclaireur-cycle.sh`
2. Recréer le job cron avec `cronjob_manage action=create` (workdir mis à jour)
3. Relancer le serveur web persistant
4. Vérifier HTTP 200 sur /healthz

## Points clés supplémentaires (session 2026-10-18)

- **YouTube collector** : flux Atom YouTube via `channel_id` (pas de token), parse `yt:videoId`, auteur, date, thumbnail
- **Sources API (K-12)** : CRUD complet `/api/sources`, `/discover` (auto-détection plateforme), `/import` (OPML), `/discover-from-pub` (découverte depuis publication), sources imposées protégées
- **TemplateResponse** : signature moderne Starlette = `TemplateResponse(request, name, context)` (request en 1er arg)
- **Serveur web persistant** : après modification du code Python, relancer le serveur (kill + redémarrage) pour prendre en compte les changements ; vérifier HTTP 200 sur /healthz
- **Container recreation** : wrapper recopié, cron recréé, web relancé, chemins vérifiés (/opt/data → /workspace)