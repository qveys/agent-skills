---
name: hermes-profile-isolation
description: "Use when creating or debugging a Hermes profile."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [hermes, profiles, isolation, skills, secrets]
    related_skills: [hermes-profile-creation, hermes-secret-sources, hermes-cron-jobs]
---

# Profils Hermes strictement isolés

## When to Use

- Créer ou déboguer un profil Hermes ; une skill/un `.env`/un job « introuvable » dans un profil.
- Partager une skill entre profils via `skills.external_dirs` ; changer le modèle d'un profil ; migrer un job cron d'un profil à un autre.

Racine Hermes = `/opt/data` (profil `default`) ; un profil = `/opt/data/profiles/<nom>/` (son `HERMES_HOME`). Les `profiles/<nom>/…` relatifs s'entendent sous `/opt/data/`.

`/opt/data/profiles/<nom>/` est une racine hermétique : aucune remontée automatique vers `/opt/data/`. Chaque ressource utilisée par un profil doit y être copiée (ou liée) explicitement.

## Ce qui est scopé par profil

| Ressource | Chemin profil | Chemin global (référence) |
|---|---|---|
| Skills | `profiles/<nom>/skills/<skill>/SKILL.md` | `/opt/data/skills/<skill>/SKILL.md` |
| `.env` (clés API, tokens) | `profiles/<nom>/.env` | `/opt/data/.env` |
| `auth.json` | `profiles/<nom>/auth.json` | `/opt/data/auth.json` |
| Jobs cron | `profiles/<nom>/cron/jobs.json` | `/opt/data/cron/jobs.json` |
| Scripts wrapper cron | `profiles/<nom>/scripts/<name>.sh` | `/opt/data/scripts/<name>.sh` |
| Channels Telegram | `profiles/<nom>/channel_directory.json` | `/opt/data/channel_directory.json` |

## Partager une skill entre profils (préféré à la copie)

1. Placer la skill dans le dépôt Git `agent-skills`, sous `skills/hermes/<catégorie>/<skill>/` (catégories : devops, software-development, autonomous-ai-agents, note-taking, supervision) : une seule version, pas de copies qui divergent. Le dépôt est cloné sur le serveur (ex. `/opt/data/agent-skills`) : y committer via le profil default après revue, pousser la branche et fusionner la PR.
2. Le dossier doit être déclaré dans `skills.external_dirs` de CHAQUE profil concerné (à faire lors de la bascule vers le clone : déclarer le sous-dossier `skills/hermes/` du clone, jamais `skills/` ni la racine du dépôt, qui chargeraient aussi les skills non Hermes, `vendor/` et `_template` — vérifier ensuite avec `get_external_skills_dirs()` ci-dessous), y compris default si la skill y vivait.
   **Une copie locale du même nom MASQUE la version partagée** (règle de résolution Hermes) : après le partage, retirer les copies locales identiques ou réconciliées, sinon les mises à jour du partagé sont invisibles pour ce profil.
3. `config.yaml` de default est refusé aux outils patch/write : passer par `HERMES_HOME=/opt/data /opt/hermes/.venv/bin/hermes config set skills.external_dirs '["/opt/data/agent-skills/skills/hermes", "<dossier du lien vault>"]'` (la liste est remplacée en entier : repasser TOUTES les entrées existantes ; le binaire `hermes` peut ne pas être dans le PATH du terminal — `/opt/hermes/bin/hermes` ou `/opt/hermes/.venv/bin/hermes`). Les `config.yaml` des profils se patchent directement, après sauvegarde `config.yaml.bak-<ts>`.
4. Vérifier par profil : `HERMES_HOME=<home> /opt/hermes/.venv/bin/python -c 'import agent.skill_utils as s;print(s.get_external_skills_dirs())'` (seuls les dossiers existants sont retenus).
5. Mettre à jour les chemins absolus cités dans la SKILL.md déplacée.

Changer `terminal.cwd` d'un profil n'affecte pas ses jobs cron qui fixent `workdir` : vérifier `cron/jobs.json` avant.

## Changer le modèle d'un profil (ex. passer sur Anthropic)

1. Donner l'identifiant au profil sans copier le secret : `hermes -p <nom> secrets onepassword set ANTHROPIC_TOKEN "op://<Vault>/<UUID>/credential"` (comparer d'abord, sans afficher, la valeur 1Password à celle du `.env` racine).
2. `hermes -p <nom> config set model.default <modèle>` puis `model.provider anthropic` : changer de provider **efface** `base_url`/`api_mode` ; les reposer comme le profil default (`https://api.anthropic.com`, `anthropic_messages`).
3. Le profil a besoin de son propre `.op.env` (`install -m 600 /opt/data/.op.env <profil>/.op.env`), sinon `hydrate_profile_secret_sources('<profil>')` rend `{}` et le modèle n'a pas de clé (cf. skill `hermes-secret-sources`).
4. Prouver par un appel réel : `env -u ANTHROPIC_TOKEN -u ANTHROPIC_API_KEY hermes -p <nom> chat -q "..." --oneshot`, puis lire `model`/`billing_provider` de la session dans `<profil>/state.db` (table `sessions`) — la sortie `--oneshot` n'affiche pas la réponse.
5. Vérifier `fallback_providers` : un repli sur un modèle `:free` renvoie les données sensibles vers un fournisseur gratuit dès que le principal échoue ; le signaler.

## Symptômes typiques quand une pièce manque

- **Skill non trouvée en job cron** : log "[IMPORTANT: skill(s) listed but could not be found and were skipped: <skill>]" → copier `SKILL.md` du profil défaut vers `profiles/<nom>/skills/<skill>/`.
- **`[blocked_config] delivery platform 'telegram' has no gateway credentials`** : `.env` absent → copier `/opt/data/.env` vers `profiles/<nom>/.env` (vraie copie, pas symlink — convention des profils existants).
- **Liste de skills vide** (`hermes -p <nom> skills list` montre "0 enabled") : aucune skill n'a été copiée — c'est normal pour un nouveau profil, pas une erreur.
- **Jobs cron `No scheduled jobs`** : aucun job n'a été créé dans le profil. Créer avec `hermes -p <nom> cron create ...`.

## Migrer un job cron (et ses fichiers) d'un profil vers un autre

1. Copier le wrapper (vraie copie, `chmod +x`) dans `profiles/<dest>/scripts/` — le CLI vérifie l'existence du script sous `$HERMES_HOME/scripts/` à la création.
2. Créer le job sur le profil destination avec les mêmes champs : `HERMES_HOME=<dir du profil dest> hermes cron create "<schedule>" --name "..." --script <nom>.sh --workdir <absolu> --deliver local --no-agent`.
3. Vérifier `cron list` des DEUX profils (job actif chez le dest, absent du source) AVANT de supprimer l'ancien — l'ordre create→vérifier→remove évite une fenêtre sans job.
4. `hermes cron remove <id>` sur le profil source, puis supprimer le wrapper du source (une copie versionnée dans le dépôt du projet reste le canon ; la copie Hermes se re-synchronise de là).
5. Exécuter le wrapper manuellement depuis sa nouvelle place (voir `hermes-cron-jobs` §Vérifier pour les wrappers longs).

**Le dépôt du projet ne suit pas le profil** : les projets partagent `/workspace/<projet>` (pattern trading : un répertoire partagé, plusieurs profils qui y travaillent et y ont leur `cwd`). Un dépôt git n'entre pas dans le dossier d'un profil — c'est de l'état de projet, pas de l'état de profil (aspiré par les pre-update backups). Seules les pièces scopées par profil migrent : job `jobs.json`, wrapper `scripts/`, outputs `cron/output/`.

## Commandes utiles

- `hermes profile list` — vue d'ensemble, indique modèle, gateway, alias.
- `hermes profile rename <old> <new>` — renomme ET déplace le dossier physique.
- `hermes -p <nom> skills list` — skills visibles depuis ce profil.
- `hermes -p <nom> cron list` — jobs planifiés dans ce profil (sinon par défaut).
- `hermes project create --primary <path> --use` — ancre un workspace; ne force PAS un worktree (utile pour les profils `worktree: false`).

## Pièges

- **Bot Telegram unique** : un seul profil peut posséder le bot Telegram actif. Copier `.env` du défaut crée un warning "shares its telegram credential" et gare le duplicate. Solutions : retirer `TELEGRAM_BOT_TOKEN` du `.env` du profil doublon, OU donner un bot distinct au nouveau profil.
- **`hermes cron create --prompt "@file"`** ne résout PAS le `@file` — le prompt est persisté littéralement. Passer le prompt directement comme dernier argument (échapper `\n` si multi-lignes).
- **Modèle qui dérive automatiquement** : `codex_gpt55_autoraise: true` (défaut) peut faire basculer le modèle pendant une session — restaurer explicitement via patch dans `config.yaml`.