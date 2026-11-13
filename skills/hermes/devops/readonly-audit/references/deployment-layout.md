# Carte des montages et propriété des dossiers (déploiement conteneur unique)

Vérifié sur ce déploiement Hermes : **un seul conteneur**, `HERMES_HOME=/opt/data`.
La doc officielle décrit deux conteneurs partageant un volume — c'est périmé, ne pas s'y fier.

## Montages réels (source : `/proc/self/mountinfo`)

| Montage | Nature | Rôle |
|---|---|---|
| `/opt/data` | volume nommé Docker (`<appName>-compose-<id>_hermes-home`, ext4) | `HERMES_HOME` — tout l'état Hermes |
| `/opt/hermes` | volume nommé (`hermes-agent-src`, ext4) | code + runtimes, immuable |
| `/workspace` | **bind** depuis `/opt/workspace` sur l'hôte (`/dev/sda1`) | données de travail |

`HERMES_RUNTIME_DIR=/opt/hermes/tools` (ffmpeg, python, chromium, node, uv).

Conséquence à retenir : `/workspace` (bind de `/opt/workspace` hôte) et `/opt/data` (volume Docker)
sont deux montages **distincts** mais sur le **même disque physique** : `mountinfo` donne le même
`8:1` (`/dev/sda1`) pour les deux, et `df -h /workspace /opt/data` affiche des chiffres identiques
(constaté le 2026-10-24 : 193G, 85 % utilisés). Déplacer des projets entre l'un et l'autre
ne libère donc aucune place — c'est de l'hygiène de chemins, pas un gain d'espace. Ne pas vendre
ce chantier comme un gain de disque. (Correction d'une version antérieure qui parlait de « device
distinct » : faux, vérifié par `/proc/self/mountinfo`.)

## Ce que la doc réserve à quoi

- `/opt/data` = « single source of truth for **all Hermes state** » (docs `user-guide/docker`,
  § Persistent volumes). Y appartiennent : `.env`, `config.yaml`, `SOUL.md`, `sessions/`,
  `memories/`, `skills/`, `home/`, `cron/`, `hooks/`, `logs/`, `skins/`, `profiles/`.
- `terminal.cwd` = répertoire de travail, **séparé** de `HERMES_HOME` (docs `user-guide/profiles`,
  § « Profiles vs workspaces vs sandboxing »). Un profil ne cloisonne rien : le backend `local`
  donne le même accès fichier que le compte.
- Voies documentées pour les données de travail : `docker_volumes` (`hote:/workspace/projets`),
  `terminal.cwd` en absolu, ou `docker_mount_cwd_to_workspace: true`.

## `HERMES_WRITE_SAFE_ROOT`

Vaut `/opt/data` dans l'image officielle. `agent/file_safety.py` refuse tout chemin hors de cette
racine. Déplacer un montage **exige** d'élargir la variable dans le même changement, sinon plus
aucune écriture ne passe. Syntaxe multi-racines, séparateur `os.pathsep` :

```
HERMES_WRITE_SAFE_ROOT=/opt/data:/workspace
```

## Propriété des dossiers sous `/opt/data` (prouvé par grep du code)

| Dossier | Écrit par | Note |
|---|---|---|
| `installs/` | `pm/environments.py` → `dependency_home_root()/installs` | venvs d'extras, survivent au rebuild |
| `lsp/` | `agent/lsp/install.py` → `get_hermes_home()/lsp` | serveurs de langage |
| `tools/` | `hermes_cli/_launchers.py`, `scripts/ci/setup_toolchain.py` | store d'outils ; `facts.json` liste ce qui y est déclaré |
| `home/` | `hermes_cli/profiles.py` (`_PROFILE_DIRS`) | HOME des sous-processus (`git`, `ssh`, `gh`, `npm`) |
| `workspace/` | `hermes_cli/profiles.py` (`_PROFILE_DIRS`) | dossier de profil légitime **et** espace de travail — ambiguïté de nom assumée par la doc |
| `checkpoints/`, `backups/`, `.curator_backups/`, `state-snapshots/` | Hermes | **exclus** des distributions de profils (`profile_distribution.py`) |
| `models_dev_cache.json` | `agent/models_dev.py` | cache de métadonnées modèles |

**Un store peut contenir un binaire non déclaré.** `tools/facts.json` ne liste que ce que le
gestionnaire connaît ; une entrée non déclarée dedans (ex. un second node) est suspecte, mais pas
prouvée inutile — `_kept_shared_launcher` peut encore la résoudre pour un checkout partagé.
Confirmer avant suppression.

## Où sont les vrais gros volumes

| Bloc | Taille | Régénérable ? |
|---|---|---|
| `workspace/.qmd/cache/qmd/models/*.gguf` | ~2,2 Go | **non** — poids ML téléchargés |
| `workspace/.qmd/cache/qmd/index.sqlite` | ~48 Mo | oui, recréé à la première invocation |
| `profiles/*/checkpoints/store/objects` | ~1,9 Go pour 3 profils | non — snapshots de session |
| `home/.cache/uv`, `home/.npm` | ~950 Mo | oui, si périmés (vérifier la date de dernier accès) |
| `00_INBOX/<export brut>` | jusqu'à 5 Go | non — donnée utilisateur, non indexée, non versionnée |

Ne pas confondre `home/.cache/uv` (périmé, parfois 700 Mo+ à purger) avec `cache/uv` (actif).
Comparer les dates de dernier accès avec `find <dir> -type f -printf '%TY-%Tm-%Td\n' | sort | uniq -c`.

## Déploiement : Dokploy

VPS de l'utilisateur géré par Dokploy, projet `my-hermes-agent`, stack **compose** git-backed
(tag `main`, autoDeploy) : pousser sur le dépôt redéploie. Le compose vit dans le dépôt, pas
hors de lui. Pilote API et pièges d'accès : skill `dokploy-vps` (locale au profil qui la porte, absente des autres).

Garder dans tout compose réécrit : `/init` en tête de chaîne (bypass = plus de chown du volume,
plus de réconciliation des profils), `HERMES_UID`/`HERMES_GID` alignés sur l'hôte, et les mêmes
volumes sur `gateway` **et** `dashboard` (sinon le dashboard ne voit pas le même état).

