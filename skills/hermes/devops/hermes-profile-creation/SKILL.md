---
name: hermes-profile-creation
description: "Use when creating a Hermes profile; mirror a sibling first."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [hermes, profiles, isolation, cron, skills]
    related_skills: [hermes-profile-isolation, hermes-cron-jobs]
---

# Créer ou étendre un profil Hermes

## When to Use

- Créer un nouveau profil Hermes (satellite de service, rôle dédié), en cloner un, ou étendre un profil existant (skills, `.env`, scripts, jobs cron).
- Diagnostiquer un profil dont une pièce manque (skill introuvable en cron, `.env` absent, pas de job).

Convention de chemins : racine Hermes = `/opt/data` (home du profil `default`) ; un profil vit sous `/opt/data/profiles/<nom>/` et son `HERMES_HOME` pointe dessus. Les `profiles/<nom>/…` relatifs ci-dessous s'entendent sous `/opt/data/`.

`/opt/data/profiles/<nom>/` est une racine hermétique : aucune remontée automatique vers `/opt/data/`. Toute ressource que le profil doit utiliser doit y être copiée explicitement.

## Pré-vol obligatoire : inspecter un profil sibling

Avant toute création, ouvrir un profil existant (`ls /opt/data/profiles/` ; ex. `lecteur`, `stratege`, `trader`) et noter ce qu'il contient :

```bash
ls -la profiles/<sibling>/               # squelette (droits, taille de auth.json vs .env)
ls profiles/<sibling>/skills/             # quelles skills ? copiées (vrai fichier) ou absentes
ls profiles/<sibling>/scripts/            # quels wrappers ?
ls profiles/<sibling>/cron/               # a-t-il déjà des jobs ?
```

Reproduire exactement ce qui existe : vrais fichiers (pas de symlink), mêmes droits (`chmod 600` sur `.env`, `chmod +x` sur les `.sh`). Les raccourcis cassent l'isolement parce que les résolveurs Hermes cherchent dans `profiles/<nom>/` sans remonter ; un symlink peut être ignoré ou créer un warning multiplex qui gare silencieusement la livraison.

## Ce qui est scopé par profil

| Ressource | Chemin profil | Source canonique |
|---|---|---|
| Skills | `profiles/<nom>/skills/<skill>/SKILL.md` | `/opt/data/skills/<skill>/SKILL.md` |
| `.env` (clés API, tokens) | `profiles/<nom>/.env` | `/opt/data/.env` |
| `auth.json` | `profiles/<nom>/auth.json` | `/opt/data/auth.json` |
| Jobs cron | `profiles/<nom>/cron/jobs.json` | `/opt/data/cron/jobs.json` |
| Scripts wrapper cron | `profiles/<nom>/scripts/<name>.sh` | `/opt/data/scripts/<name>.sh` |
| Channels Telegram | `profiles/<nom>/channel_directory.json` | `/opt/data/channel_directory.json` |

## Symptômes typiques quand une pièce manque

- **Skill non trouvée en job cron** : log "[IMPORTANT: skill(s) listed but could not be found and were skipped: <skill>]" → copier `SKILL.md` source vers `profiles/<nom>/skills/<skill>/`.
- **`[blocked_config] delivery platform 'telegram' has no gateway credentials`** : `.env` absent → copier `/opt/data/.env` vers `profiles/<nom>/.env`.
- **Liste de skills vide** : aucune skill n'a été copiée — c'est normal, pas une erreur.
- **Jobs cron `No scheduled jobs`** : créer le job via `hermes -p <nom> cron create ...`.

## Procédure type

1. `hermes profile create <nom> --clone-from <sibling> --description "<rôle en une ligne>"` pour partir d'un profil frère : config, `.env`, skills et plugins sont copiés, les canaux messaging sont volontairement laissés de côté (un token de bot en double ferait deux passerelles se battre sur le même bot). `--no-alias` évite de créer un wrapper shell ; `--clone-channels` copierait aussi les canaux (refusé si la source est servie par un gateway multiplexé) ; `--no-skills` crée un profil sans skills bundled. `hermes profile rename <old> <nom>` si on renomme.
2. **Réécrire `SOUL.md`** : le clone apporte celui du frère, qui décrit SA mission et sera faux pour le nouveau profil. Lire le fichier cloné en entier avant de l'écraser — `write_file` refuse un fichier existant jamais relu dans la session.
3. Pour chaque skill **locale** voulue (les skills du dossier partagé — clone du dépôt `agent-skills` — sont visibles sans copie si le `config.yaml` du profil liste ce dossier dans `skills.external_dirs`) : `mkdir -p profiles/<nom>/skills/<skill> && cp /opt/data/skills/<skill>/SKILL.md profiles/<nom>/skills/<skill>/`.
4. `cp /opt/data/.env profiles/<nom>/.env && chmod 600 profiles/<nom>/.env`.
5. Pour chaque wrapper cron : `cp /opt/data/scripts/<name>.sh profiles/<nom>/scripts/ && chmod +x ...`.
6. `hermes -p <nom> cron create ...` pour chaque job à migrer (jamais `cp jobs.json` — la clé `script` résout contre le `HERMES_HOME` du profil courant, l'ID et la trace doivent être créés par la CLI du bon profil).
7. `hermes -p <nom> skills list` puis `hermes -p <nom> cron list` pour vérifier.

Un profil cloné sans canaux n'a pas de section `platforms:` dans son `config.yaml` : c'est un **satellite**, il ne possède aucune plateforme et doit passer par `gateway.profile_routes` du propriétaire pour livrer (cf. `hermes-cron-jobs`, section satellite). C'est la forme voulue pour un profil de service — pas une pièce manquante à réparer.

## Pièges

- **Bot Telegram unique** : un seul profil peut posséder le bot Telegram actif. Si on copie `/opt/data/.env` tel quel, on hérite de `TELEGRAM_BOT_TOKEN` du défaut et un warning multiplex apparaît. Trois issues selon l'intention : accepter le doublon (couvert par multiplex — fonctionne en pratique mais log un warning), supprimer `TELEGRAM_BOT_TOKEN` du profil doublon (échec propre du cron), ou créer un bot dédié au nouveau profil.
- **`hermes cron create --prompt "@file"`** ne résout PAS le `@file` — le prompt est persisté littéralement. Passer le prompt directement comme dernier argument (échapper `\n` si multi-lignes).
- **`hermes config set` sur une clé liste REMPLACE la liste entière.** `config set gateway.profile_routes '[{...}]'` écrase toutes les entrées existantes : poser la route d'un nouveau profil de cette façon efface en silence celle des autres. Toujours passer la liste complète fusionnée (anciennes + nouvelles entrées) et vérifier par `diff` contre un backup. Sauvegarder le `config.yaml` avant toute écriture de clé liste.
- **L'outil `patch` / `write_file` refuse d'écrire un `config.yaml` Hermes** (« Refusing to write to Hermes config file »). Passer par `hermes config set <clé> '<json>'` (ou `hermes config edit`) ; ne pas contourner le garde-fou.
- **`worktree: true` dans le profil + cron hors dépôt Git** : worker dispatché échoue en silence. Garder `worktree: false` sur les profils non-git.
- **Modèle dérivé par `codex_gpt55_autoraise`** : une session Telegram qui pin un modèle peut basculer le `default` du profil. Restaurer explicitement via patch dans `config.yaml` après.
- **Création de symlink `.env`** : les résolveurs de tokens ne suivent pas tous les symlinks, et le multiplex gate refuse. Toujours vraie copie.

## Commandes utiles

- `hermes profile list` — vue d'ensemble (modèle, gateway, alias, warnings).
- `hermes profile rename <old> <new>` — renommée ET déplacement physique du dossier.
- `hermes -p <nom> skills list` / `cron list` / `cron runs <job_id>` — vue locale au profil.
- `hermes cron run <job_id>` depuis `HERMES_HOME=<profil>` (ou `-p <nom>`) pour tester sans attendre l'échéance.
- `hermes project create --primary <path> --use` — ancre un workspace sans worktree (utile pour profils `worktree: false`).