# Bug : le token d'amorçage est filtré de l'environnement des sources

## Symptôme

`hydrate_profile_secret_sources()` renvoie `{}` alors que `hermes secrets <src> status`
annonce « applied N secrets ». Aucune exception, aucun log d'erreur au démarrage : le
`ApplyReport` est simplement vide.

## Mécanisme

`hermes_cli/env_loader.py::_hydrate_profile_secret_sources()` construit un environnement
privé en ne retenant que les variables reconnues « globales » par
`agent.secret_scope._is_global_env()` :

```python
local_env = {name: value for name, value in os.environ.items() if _is_global_env(name)}
local_env.update(load_env_file(home / ".env"))
```

`_is_global_env()` teste l'appartenance à `_GLOBAL_ENV_EXACT` (liste fermée dans
`agent/secret_scope.py`) ou un préfixe de `_GLOBAL_ENV_PREFIXES`. Les tokens d'amorçage
des sources de secrets elles-mêmes — `OP_SERVICE_ACCOUNT_TOKEN`, `BWS_ACCESS_TOKEN` —
n'y figurent pas. Le token n'est ni global, ni présent dans `.env` (par conception, il ne
devrait pas y être écrit en clair) → il n'atteint jamais le processus enfant de la source,
qui échoue sur « No accounts configured ».

Ne pas confondre ce chemin avec celui de `hermes secrets <src> status` : le status passe
par un autre code et affiche « applied N secrets » alors que la résolution runtime échoue.
**Le status n'est pas une preuve de résolution.**

## Reproduction A/B

```bash
/opt/hermes/.venv/bin/python -c "
import sys, os; sys.path.insert(0,'/opt/hermes')
from pathlib import Path
from agent.secret_sources.registry import apply_all
cfg={'onepassword':{'enabled':True,'binary_path':'/usr/local/bin/op',
                    'env':{'VAR':'op://<Vault>/<Item>/<field>'}}}
for label, extra in (('sans token',{}),
                     ('avec token',{'OP_SERVICE_ACCOUNT_TOKEN':os.environ['OP_SERVICE_ACCOUNT_TOKEN']})):
    env={'HERMES_HOME':'<home>','HOME':'<home>',**extra}
    r=apply_all(cfg, Path('<home>'), environ=env)
    print(label, sorted(r.provenance) or 'VIDE',
          [w[:90] for s in r.sources for w in s.result.warnings])
"
```

Déterministe : le seul écart entre les deux cas est la présence du token.
- `sans token` → `VIDE`, warning `op read failed … No accounts configured`
- `avec token` → `['VAR']`

Confirmer la cause en amont :

```bash
/opt/hermes/.venv/bin/python -c "
import sys; sys.path.insert(0,'/opt/hermes')
from agent.secret_scope import _is_global_env
print(_is_global_env('OP_SERVICE_ACCOUNT_TOKEN'))   # False => cause confirmée
"
```

## Contournement opérationnel : `.op.env`

Le code prévoit explicitement ce fichier (lu APRÈS `.env`, donc `.env` gagne, et avec
`setdefault` donc une valeur existante n'est jamais écrasée) :

```bash
umask 077
# $HERMES_HOME = home du profil concerné (racine : /opt/data ; profil : /opt/data/profiles/<nom>)
printf 'OP_SERVICE_ACCOUNT_TOKEN=%s\n' "$OP_SERVICE_ACCOUNT_TOKEN" > "$HERMES_HOME/.op.env"
chmod 600 "$HERMES_HOME/.op.env"
```

À créer **pour chaque home** : `/opt/data/.op.env` (racine) ET
`/opt/data/profiles/<nom>/.op.env` (un par profil ; vérifié présent pour les profils existants) — chaque profil a son propre home et relit ce fichier
indépendamment.

Coût du contournement : le token revient en clair sur disque, ce que la migration cherchait
à éviter. C'est le prix de la cause non corrigée en amont.

## Correctifs suggérés (à remonter)

Le plus direct, dans `_GLOBAL_ENV_EXACT` :

```python
# Bootstrap tokens for the bundled secret sources — must reach the source's
# child process or the source silently resolves nothing.
"OP_SERVICE_ACCOUNT_TOKEN", "BWS_ACCESS_TOKEN",
```

Alternative, sans élargir la liste globale, dans `_hydrate_profile_secret_sources()` :
propager explicitement le token configuré pour la source activée.

À défaut de correctif, demander au minimum qu'un échec d'authentification remonte comme
`ErrorKind.AUTH_FAILED` visible au démarrage, plutôt qu'un `ApplyReport` vide.

## Portée

Même défaut attendu pour Bitwarden (`BWS_ACCESS_TOKEN`), par symétrie de conception.
Vérifier avant de conclure que Bitwarden est épargné.
