# Propagation de la section `secrets:` vers les profils

## La règle

`hermes_cli/env_loader.py::_load_secrets_config()` lit **uniquement** `<home>/config.yaml`.
Il n'y a aucun mécanisme d'héritage du config racine vers les profils pour cette section.

Preuve par test (source `command` active dans le config racine) :

```bash
/opt/hermes/.venv/bin/python -c "
import sys; sys.path.insert(0,'/opt/hermes')
from pathlib import Path
from hermes_cli.env_loader import _load_secrets_config
print('RACINE :', _load_secrets_config(Path('/opt/data')))
print('PROFIL :', _load_secrets_config(Path('/opt/data/profiles/<nom>')))
"
```

Attendu : la racine renvoie la section, le profil renvoie `{}`.

## Conséquence

Un `hermes secrets <src> set VAR ...` exécuté à la racine **n'a aucun effet sur les profils**.
Après avoir retiré une clé du `.env` d'un profil sans y ajouter la source, ce profil a un
`.env` nettoyé ET aucune source : ses clés sont simplement absentes. Le symptôme n'est pas
une erreur, c'est un silence.

Ne jamais déduire l'héritage d'une section de config : le tester. Une section qui descend
pour un usage (skills, cron) ne descend pas forcément pour `secrets:`.

## La commande qui cible vraiment un profil

`hermes config set` sans flag écrit dans le config racine. Pour cibler un profil :

```bash
hermes -p <profil> config set secrets.onepassword.enabled true
hermes -p <profil> config set secrets.onepassword.binary_path /usr/local/bin/op
hermes -p <profil> secrets onepassword set VAR "op://<Vault>/<Item>/<field>"
```

Vérifier que l'écriture a atterri au bon endroit :

```bash
grep -A6 '^secrets:' "/opt/data/profiles/<nom>/config.yaml"
```

## Quelles clés mapper par profil

Déduire la liste depuis la **sauvegarde du `.env` du profil**, pas depuis le config racine :
les profils n'utilisent pas tous le même jeu de clés. Mapper exactement ce que le profil
utilisait — ni plus (exposition inutile), ni moins (clé manquante).

Un profil sans `config.yaml` n'a aucune section à patcher : il faut la créer. `hermes -p <nom>
config set` la crée au besoin.

## Token d'amorçage par profil

Le token doit aussi être visible depuis le home du profil. Voir
`references/source-scoping-bug.md` : créer `/opt/data/profiles/<nom>/.op.env` en plus de
`/opt/data/.op.env` (racine Hermes ; depuis un profil, `$HERMES_HOME` désigne le profil).

## Vérification finale par profil

Boucler sur chaque profil et comparer le jeu résolu au jeu attendu — jamais supposer que ce
qui marche pour l'un marche pour l'autre :

```bash
/opt/hermes/.venv/bin/python -c "
import sys, os; sys.path.insert(0,'/opt/hermes')
from hermes_cli.env_loader import hydrate_profile_secret_sources
KEYS=('VAR_A','VAR_B')
for prof in ('<profil1>','<profil2>'):
    for k in KEYS: os.environ.pop(k, None)
    print(prof, sorted(hydrate_profile_secret_sources(f'/opt/data/profiles/{prof}')))
"
```
