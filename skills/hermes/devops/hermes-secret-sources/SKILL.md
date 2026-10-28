---
name: hermes-secret-sources
description: "Use when moving Hermes credentials out of .env into a vault."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [hermes, secrets, credentials, vault, 1password, bitwarden, security]
    related_skills: [hermes-plugin-env-config, hermes-agent]
---

# Sources de secrets Hermes

Migrer les credentials de `$HERMES_HOME/.env` vers une source externe (1Password, Bitwarden,
helper shell), sans casser les profils ni le runtime.

## When to Use

Credentials must move out of a Hermes `.env` into an external secret source, a mapped vault reference does not resolve at runtime, or an external source must be propagated across several Hermes profiles.

- L'utilisateur veut que les clés API/tokens sortent du `.env` en clair
- Une clé doit être ajoutée à un vault puis consommée par Hermes
- Une variable `op://` / vault est mappée mais « ne résout pas » à l'exécution
- Il faut propager une source externe à plusieurs profils Hermes

## Règles permanentes

0. **Un même fournisseur peut exister sous deux noms/variables.** Un provider peut être défini à la fois comme plugin `model-providers` (ex: `opencode-go`, env `OPENCODE_GO_API_KEY`) ET dans le catalogue `models_dev` affiché par le sélecteur (ex: `opencode`, env `OPENCODE_API_KEY`, endpoint différent). Mapper la variable attendue par **l'interface que l'utilisateur regarde** (le catalogue/la liste), pas seulement celle du plugin ; les deux pointent vers le même item 1Password. Diagnostic si « le fournisseur n'apparaît pas dans ma liste » : retrouver sa variable d'env dans le code/catalogue (`grep OPENCODE /opt/hermes/agent/models_dev.py` ou l'inspecter via le cache `/opt/data/models_dev_cache.json`), mapper cette variable, puis recharger la session (l'env des processus lancés AVANT le mapping est figé — un redémarrage du service/session est nécessaire pour voir le fournisseur).

1. **`.env` porte les valeurs, `config.yaml` porte la configuration.** La commande d'un helper
   (`secrets.command.command`) va dans `config.yaml`, jamais dans `.env`. Seul le token
   d'amorçage de la source (`OP_SERVICE_ACCOUNT_TOKEN`, `BWS_ACCESS_TOKEN`) reste dans `.env` —
   c'est par conception.
2. **Ne jamais afficher une valeur de secret.** Comparer par égalité de chaînes et n'afficher que
   `True`/`False` et la longueur. Ne jamais coller une valeur dans le chat : les messages de
   session sont persistés (`state.db`, transcripts).
3. **Sauvegarder avant de retirer.** Copie horodatée de chaque `.env` et `config.yaml` dans un
   dossier `700` contenant des fichiers `600`, avec un `MANIFEST.txt` portant l'horodatage.
4. **Vérifier avant de supprimer.** La valeur résolue par la source doit être *identique* à celle
   du `.env`. Tant que l'égalité n'est pas prouvée, ne pas retirer la ligne en clair.
5. **Ne pas déduire l'héritage.** Vérifier par un test réel qu'une section `secrets:` descend (ou
   non) dans les profils — voir `references/profile-propagation.md`.

## Procédure

### 1. Inventorier sans lire les valeurs

Compter les clés et classer secret / non-secret par nom seul :

```bash
awk -F= '/^[[:space:]]*#/||/^[[:space:]]*$/ {next}
        /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/ {print $1}' "$ENV" \
  | sed 's/[[:space:]]//g' | sort -u |
  grep -E '(API_KEY|_KEY|_TOKEN|_SECRET|_PASSWORD)$'
```

Ne classer secret que ce qui porte un suffixe de credential. `*_TIMEOUT`, `*_DEBUG`, chemins et
IDs de canal sont des réglages : ils restent en clair dans `.env`.

### 2. Vérifier l'accès vault avant tout mapping

```bash
op whoami                          # confirme Type: SERVICE_ACCOUNT
op vault list                      # un service account ne voit QUE ses coffres
op item list --vault <V> --format json
```

Un **service account exige `--vault`** sur toute lecture d'item : sans lui, `op item get` échoue
sur « a vault query must be provided ». Tester une permission d'écriture avant de planifier une
création d'item — voir `references/op-cli-gotchas.md`.

### RÈGLE ABSOLUE : JAMAIS AFFICHER UN SECRET 1PASSWORD

Toute valeur récupérée via `op item get --reveal`, `op read`, ou `op item get --fields <field> --reveal`
**ne s'affiche jamais** — ni dans le chat, ni dans les logs, ni dans les fichiers de sortie, ni dans
les captures d'écran terminales.

- Comparer par égalité de chaînes et n'afficher que `True`/`False` et la longueur.
- Ne jamais coller une valeur dans le chat : les messages de session sont persistés (`state.db`, transcripts).
- Si un `curl`/`terminal` contient un secret résolu via 1Password, masquer la valeur dans la commande
  (ex: `KEY=$(op ...)` puis `curl -H "Authorization: Bearer $KEY"`) et ne jamais `echo $KEY`.
- Sortie terminale : rediriger vers fichier si le secret pourrait apparaître, puis lire le fichier
  sans l'afficher (ex: `read_file` avec offset/limit pour ne pas voir le secret).

### 3. Mapper, dans le bon fichier

Racine puis **chaque profil concerné**, un par un :

```bash
hermes secrets onepassword set VAR "op://<Vault>/<Item>/<field>"
# forme équivalente, qui ré-applique les sources dans la foulée et confirme le compte :
hermes config set secrets.onepassword.env.VAR "op://<Vault>/<Item>/<field>"
hermes -p <profil> secrets onepassword set VAR "op://<Vault>/<Item>/<field>"
hermes -p <profil> config set secrets.onepassword.enabled true
hermes -p <profil> config set secrets.onepassword.binary_path /usr/local/bin/op
```

**Préférer l'UUID d'item au nom** dans la référence `op://` : `op://<Vault>/<UUID>/credential`.
Le nom d'item (`VPS-DOKPLOY Cloudflare Service Auth`) change au renommage (coquille corrigée, etc.)
et casse le mapping silencieusement — `status` reste vert, `op read` échoue. L'UUID est stable.

Mapper exactement les clés que le profil utilisait, ni plus ni moins : déduire la liste depuis la
sauvegarde de son `.env`, pas depuis le config racine.

### 4. Prouver la résolution AVANT de retirer quoi que ce soit

```bash
/opt/hermes/.venv/bin/python - <<'PY'
import sys, os; sys.path.insert(0, '/opt/hermes')
from pathlib import Path
from hermes_cli.env_loader import hydrate_profile_secret_sources
for k in ('VAR_A', 'VAR_B'):
    os.environ.pop(k, None)          # sinon la valeur déjà présente masque le test
vals = hydrate_profile_secret_sources('/opt/data')
env = {}
for line in Path('/opt/data/.env').read_text(errors='replace').splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, _, v = line.partition('=')
        env[k.strip()] = v.strip().strip('"').strip("'")
for k, v in sorted(vals.items()):
    print(f'{k:26} dans .env={k in env!s:6} identique={env.get(k) == v!s:6} len={len(v)}')
PY
```

Vider `os.environ` de la clé avant le test : une valeur déjà chargée fait croire à une résolution
qui n'a pas eu lieu.

**Pour 1Password : créer un `.op.env` dans chaque home de profil** (`/opt/data/.op.env`,
`/opt/data/profiles/<nom>/.op.env`) contenant `OP_SERVICE_ACCOUNT_TOKEN=...` — sans lui,
l'hydratation de profil rend `{}` malgré un `status` vert.

### 5. Retirer, puis re-vérifier

Retirer les lignes mappées, remettre le mode `600`, puis relancer l'étape 4 : les clés doivent
toujours résoudre, cette fois uniquement depuis la source externe.

### 6. Diagnostiquer un « ça ne résout pas »

Si `hydrate_profile_secret_sources()` renvoie `{}` alors que `hermes secrets <src> status`
annonce « applied N secrets », le problème est l'environnement passé à la source, pas le mapping.
Isoler par A/B sur `apply_all` :

```bash
/opt/hermes/.venv/bin/python -c "
import sys, os; sys.path.insert(0,'/opt/hermes')
from pathlib import Path
from agent.secret_sources.registry import apply_all
cfg={'onepassword':{'enabled':True,'binary_path':'/usr/local/bin/op','env':{'VAR':'op://V/I/field'}}}
for label, extra in (('sans token',{}),('avec token',{'OP_SERVICE_ACCOUNT_TOKEN':os.environ['OP_SERVICE_ACCOUNT_TOKEN']})):
    env={'HERMES_HOME':'/opt/data','HOME':'/opt/data',**extra}
    r=apply_all(cfg, Path('/opt/data'), environ=env)
    print(label, sorted(r.provenance) or 'VIDE', [w[:90] for s in r.sources for w in s.result.warnings])
"
```

Si le cas « sans token » échoue et « avec token » passe, le token d'amorçage est filtré en amont :
voir `references/source-scoping-bug.md`.

## Références

- `references/git-credentials-1password.md` — helper Git qui lit un identifiant depuis 1Password,
  vérification sans fuite, usage avec `git push`
- `references/source-scoping-bug.md` — bug `_GLOBAL_ENV_EXACT` / token d'amorçage, repro A/B,
  correctifs suggérés, et le contournement `.op.env`
- `references/profile-propagation.md` — pourquoi la section `secrets:` ne descend pas dans les
  profils, et la commande qui cible vraiment un profil
- `references/op-cli-gotchas.md` — pièges de la CLI `op` (catégorie, `--vault`, permissions
  service account, item renommé)
- `references/source-precedence.md` — `override_existing` par source, échelle de précédence,
  alias de profil

## Voir aussi

- Skill `hermes-plugin-env-config` — variables d'environnement lues à l'import, redémarrage,
  topologie multi-conteneurs
- Skill `hermes-agent` — commandes CLI générales (bundled)
- Skill `1password` — CLI `op`, méthodes d'authentification (bundled)