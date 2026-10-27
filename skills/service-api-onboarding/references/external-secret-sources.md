# Sources de secrets externes : sortir la clé de `.env`

Hermes ne stocke pas les secrets que dans `.env`. Trois sources intégrées les tirent au démarrage et les injectent dans `os.environ` — la valeur ne dort alors nulle part en clair sur disque, seul un token d'amorçage reste dans `.env`.

Vérifier ce que l'install supporte AVANT de recommander :

```bash
ls "$(python3 -c 'import agent.secret_sources as s,os;print(os.path.dirname(s.__file__))')"
# -> bitwarden.py  command.py  onepassword.py  registry.py
```

## Les trois sources

| Source | Mécanisme | Quand la choisir |
|---|---|---|
| `command` | Un helper shell (`pass`, `gpg -d`, `secret-tool`, un script) imprime `KEY=VALUE` ; Hermes le lance une fois au démarrage et parse la sortie | **Défaut.** Zéro service tiers, zéro binaire à installer |
| `onepassword` | Références `op://vault/item/field` résolues par le CLI `op` | Seulement si `op` est déjà là (`command -v op`) |
| `bitwarden` | CLI `bws` + UUID de projet BSM | Seulement si un compte BSM existe (`command -v bws`) |

Privilégier `command` sauf si l'utilisateur a déjà un vault : Bitwarden et 1Password n'apportent un gain réel que sur une rotation déjà centralisée.

## `override_existing` diffère selon la source — PROUVÉ

| Source | `override_existing` | Effet sur une valeur restée dans `.env` |
|---|---|---|
| `command` | `false` | la copie en clair **gagne**, le helper est ignoré |
| `onepassword` | `true` | le vault **écrase** silencieusement la copie en clair |
| `bitwarden` | `true` | idem 1Password |

Ne jamais raisonner par analogie d'une source à l'autre. Sous `command`, une ligne oubliée dans `.env` fait croire à une migration réussie alors que la valeur en clair sert encore. Sous 1Password, l'inverse : la valeur en clair est morte sans que personne l'ait retirée, donc une rotation de vault peut sembler « ne pas prendre » si l'on inspecte le mauvais fichier.

Dans les deux cas : **retirer la ligne de `.env` après un `sync` validé**, et le faire dans TOUS les `.env` concernés.

## La section `secrets:` ne s'hérite PAS vers les profils — PROUVÉ

`hermes_cli/env_loader.py::_load_secrets_config()` lit **uniquement** `<home>/config.yaml`.

```bash
/opt/hermes/.venv/bin/python -c "
from pathlib import Path
from hermes_cli.env_loader import _load_secrets_config
print('ROOT :', _load_secrets_config(Path('/opt/data')))
print('PROF :', _load_secrets_config(Path('/opt/data/profiles/<nom>')))
"
```

Sortie observée avec une source `command` active à la racine :

```
ROOT : {'command': {'enabled': True, 'command': '/bin/sh .../fake-vault.sh'}}
PROF : {}
```

**Conséquence :** `hermes secrets onepassword set` (ou un `config set secrets.*`) exécuté au niveau racine n'a **aucun effet** sur les profils. Chaque profil a besoin de sa propre section `secrets:` dans son propre `config.yaml`. Un mapping racine seul laisse les profils sur leur `.env` en clair, sans le moindre avertissement.

Corollaire : le token d'amorçage (`OP_SERVICE_ACCOUNT_TOKEN`, `BWS_ACCESS_TOKEN`) doit être présent dans le `.env` de CHAQUE profil qui utilise la source, sinon ce profil échoue silencieusement l'hydratation au démarrage (fail-open : la source est simplement absente).

### Bootstrap 1Password par `.op.env` — obligatoire dans le chemin profil, PROUVÉ

`env_loader` lit `<home>/.op.env` (gitignored) en appoint avant d'appeler `apply_all`, par `setdefault` : `.env` reste prioritaire. C'est la voie dédiée et gitignored pour faire porter le token au chemin d'hydratation des profils, sans l'ajouter au `.env` déjà suivi.

**Pourquoi c'est obligatoire.** `hydrate_profile_secret_sources()` ne transmet à `apply_all` qu'un environnement privé filtré par `_is_global_env()`, et `OP_SERVICE_ACCOUNT_TOKEN` n'est PAS dans cette liste. Le token est donc retiré avant d'atteindre `op`, qui échoue sur « No accounts configured » — et la source rend `ok=True` accompagné d'un simple WARNING, jamais d'une erreur. L'hydratation rend alors `{}` sans le moindre bruit.

**Créer un `.op.env` par home** : racine + chaque profil qui utilise la source. Mode `600`, le token seul dedans. Le token dans le `.env` du profil marche aussi (chargé sans filtre dans ce chemin), mais `.op.env` est l'emplacement dédié :

```bash
umask 077
printf 'OP_SERVICE_ACCOUNT_TOKEN=%s\n' "$OP_SERVICE_ACCOUNT_TOKEN" > "/opt/data/.op.env"
chmod 600 "/opt/data/.op.env"
# idem dans /opt/data/profiles/<nom>/.op.env
```

### `status` peut mentir : deux chemins, deux environnements — PROUVÉ

`hermes secrets onepassword status` s'exécute dans l'environnement complet du process, où le token est visible : il annonce « applied 1 secret ». `hydrate_profile_secret_sources()` — le chemin que prennent réellement les tours routés vers un profil — travaille sur l'environnement privé filtré, où ce même token a disparu. **Un `status` vert ne prouve donc rien pour un profil.**

Vérifier par le chemin réel :

```bash
/opt/hermes/.venv/bin/python -c "
import os, sys; sys.path.insert(0,'/opt/hermes')
os.environ.pop('SERVICE_API_KEY', None)
from hermes_cli.env_loader import hydrate_profile_secret_sources
vals = hydrate_profile_secret_sources('$HERMES_HOME')
print('hydratees:', sorted(vals.keys()) or 'VIDE')
"
```

`VIDE` signifie que la source est bien configurée mais que le token n'arrive pas : le symptôme est un `.op.env` manquant, pas une référence `op://` cassée. Confirmer ensuite que la valeur est la bonne sans l'afficher — la comparer à `op read` par égalité de chaînes, en ne montrant que la longueur et le préfixe.

### Diagnostiquer une source qui résout d'un côté et pas de l'autre

Reproduire en opposant deux environnements privés : la cause se lit sans aucun credential réel.

```bash
/opt/hermes/.venv/bin/python -c "
import os, sys; sys.path.insert(0,'/opt/hermes')
from pathlib import Path
from agent.secret_sources.registry import apply_all
cfg = {'onepassword': {'enabled': True, 'binary_path': '/usr/local/bin/op',
       'env': {'SERVICE_API_KEY': 'op://<vault>/<item>/<field>'}}}
for label, env in (('sans token', {'HERMES_HOME': '$HERMES_HOME'}),
                   ('avec token', {'HERMES_HOME': '$HERMES_HOME',
                                   'OP_SERVICE_ACCOUNT_TOKEN': os.environ['OP_SERVICE_ACCOUNT_TOKEN']})):
    rep = apply_all(cfg, Path('$HERMES_HOME'), environ=env)
    print(label, '->', sorted(rep.provenance.keys()) or 'VIDE')
    for s in rep.sources:
        print('   ok=', s.result.ok, [w[:90] for w in s.result.warnings])
"
```

Sans token : `VIDE` plus un warning « op read failed … No accounts configured ». Avec token : la variable sort. Le diagnostic est fait — la cause est le filtrage d'environnement, pas la référence.

## `op` en compte de service : deux particularités

**`op item get` exige `--vault`.** Un compte de service ne peut pas interroger sans coffre explicite : sans le flag, `op item get "<item>" --format json` échoue sur « a vault query must be provided when this command is called by a service account ». `op item list --vault <vault>` et `op item get "<item>" --vault <vault>` fonctionnent.

**Lire la structure sans exposer la valeur** — champ, identifiant de champ et présence :

```bash
op item get "<item>" --vault "<vault>" --format json | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('item:', d.get('id'))
for f in d.get('fields',[]):
    lbl = f.get('label') or f.get('id')
    print('  %s id=%s a_une_valeur=%s' % (lbl, f.get('id'), bool(f.get('value'))))
"
```

Le nom de champ réel sert à bâtir la référence ; `op read "op://..." | wc -c` confirme la résolution par la longueur, jamais par affichage. `op whoami` peut annoncer « Using configuration at non-standard location » : bruit bénin, l'authentification est bonne dès que `User Type: SERVICE_ACCOUNT` apparaît.

### Alias de profil

Actif par défaut (`secrets.profile_alias: false` pour le couper) : sous un profil nommé, un secret du vault nommé `FOO_<PROFILE>` hydrate aussi `FOO`, **uniquement** si le nom finit par `_API_KEY`, `_TOKEN`, `_SECRET`, `_KEY` ou `_PASSWORD`. Une variable fournie sous son nom canonique bat toujours l'alias. Utile pour donner à chaque profil sa propre clé dans un vault partagé.

## Recette 1Password (`op://`)

```bash
hermes secrets onepassword setup --account <compte> --token-env OP_SERVICE_ACCOUNT_TOKEN

# mapper — À REFAIRE dans le config.yaml de chaque profil concerné
hermes secrets onepassword set OPENROUTER_API_KEY "op://<vault>/<item>/<field>"

hermes secrets onepassword sync          # dry-run : résout et montre ce qui s'applique
hermes secrets onepassword status        # config + binaire + références + auth
hermes secrets onepassword sync --apply  # exporte dans le shell courant
```

`set` valide et stocke la référence dépouillée. `sync` reste un dry-run tant que `--apply` n'est pas passé. Ne retirer les lignes `.env` qu'après un `sync` sans erreur, et refaire le contrôle dans chaque profil.

## Recette `command` (vérifiée de bout en bout)

Le helper tourne via `/bin/sh -c`, timeout 3 s, sortie plafonnée à 1 Mio, stderr capturé et **jeté** (pour qu'un diagnostic ne fuite pas de valeur). Il tourne une seule fois au démarrage, avec une clé vide.

```bash
hermes config set secrets.command.enabled true
hermes config set secrets.command.command "/bin/sh $HOME/.local/bin/hermes-vault.sh"
```

Le `command` va dans `config.yaml` (c'est un réglage), la valeur reste dans le helper chiffré — jamais l'inverse.

## Piège : `override_existing` est `false` par défaut sur `command`

L'échelle de précédence est : `.env`/shell gagne, sauf si la source déclare `override_existing: true` (Bitwarden et 1Password le font, `command` non). Sources mappées (VAR→référence explicite) > sources bulk ; à forme égale, la première source à réclamer une variable gagne. `preserve_existing: [VAR]` fait gagner `.env` même contre `override_existing: true`.

**Après une migration, supprimer la ligne de `.env`.** Sinon l'utilisateur croit sa clé hors de `.env` alors que la copie en clair gagne silencieusement la précédence. C'est le piège principal de cette feature.

## Vérifier une source de secrets sans credential réel

Tester avec un helper bidon, puis nettoyer, plutôt que de remettre une config non éprouvée :

```bash
# 1. helper factice, construit via write_file (PAS un heredoc — voir le piège plus bas)
#    KEYNAME="SERVICE_API_KEY"
#    printf '%s=%s\n' "$KEYNAME" "DUMMY_999"
chmod 700 /path/to/fake-vault.sh

# 2. injection effective dans os.environ ?
python3 -c "
import os
from pathlib import Path
os.environ.pop('SERVICE_API_KEY', None)
from agent.secret_sources.registry import apply_all
rep = apply_all({'command': {'enabled': True, 'command': '/bin/sh /path/to/fake-vault.sh'}},
                Path(os.environ['HERMES_HOME']))
print('applied_any:', rep.applied_any)
print('provenance:', sorted(rep.provenance.keys()))
print('conflicts:', rep.conflicts)
print('in environ:', bool(os.environ.get('SERVICE_API_KEY')))
"

# 3. nettoyage + contrôle de non-pollution
hermes config unset secrets.command.enabled
hermes config unset secrets.command.command
rm -f /path/to/fake-vault.sh
echo "pollue ? [${SERVICE_API_KEY:-<absent>}]"
```

`apply_all(secrets_cfg, home_path)` rend un `ApplyReport` : `.applied_any`, `.provenance` (dict var → `AppliedVar`), `.conflicts`. `AppliedVar` n'expose pas d'attribut `origin` — ne pas le lire.

## Piège : le rédacteur de secrets corrompt les heredocs de test

Le rédacteur (`security.redact_secrets`, actif par défaut) réécrit toute ligne en forme `MOT=secret` AVANT qu'elle n'atteigne le disque. Un `cat > f <<'EOF'` contenant `printf 'SERVICE_API_KEY=valeur'` arrive sur disque tronqué à `SERVICE_API_KEY=***`, fichier muet et débogage absurde.

**Construire la ligne via une variable** pour que le motif `KEY=VALUE` n'apparaisse jamais dans le texte de la commande :

```sh
KEYNAME="SERVICE_API_KEY"
printf '%s=%s\n' "$KEYNAME" "DUMMY_999"
```

Même règle pour tout test de credential : écrire le fichier avec `write_file`, jamais par heredoc shell.

## Rituel de retrait d'une ligne `.env` (migration aboutie)

L'ordre compte : un retrait fait avant la preuve d'égalité est irréversible côté vault.

1. **Prouver l'égalité valeur à valeur.** Comparer la valeur résolue par la source à celle du `.env` par égalité de chaînes, en n'affichant que booléen et longueur. Une clé absente du `.env` (cas d'une clé neuve) rend `False` sans être une anomalie : distinguer « identique », « différent » et « pas dans `.env` ».

```bash
/opt/hermes/.venv/bin/python -c "
import sys; sys.path.insert(0,'/opt/hermes')
import os
from pathlib import Path
for k in ('KEY_A','KEY_B'): os.environ.pop(k, None)
from hermes_cli.env_loader import hydrate_profile_secret_sources
vals = hydrate_profile_secret_sources('\$HERMES_HOME')
env = {}
for ln in Path('\$HERMES_HOME/.env').read_text(errors='replace').splitlines():
    ln = ln.strip()
    if not ln or ln.startswith('#') or '=' not in ln: continue
    k,_,v = ln.partition('='); env[k.strip()] = v.strip().strip(chr(34)).strip(chr(39))
for k in sorted(vals):
    print('%-24s dans_env=%-6s identique=%-6s len=%d' % (k, k in env, k in env and env[k]==vals[k], len(vals[k])))
"
```

2. **Sauvegarder les `.env` concernés** dans un dossier `700` horodaté, avant la moindre suppression. Sans ce filet, une égalité mal lue coûte les valeurs d'origine.

```bash
TS=\$(date -u +%Y%m%dT%H%M%SZ); D="\$HERMES_HOME/.secrets-migration-backup"
mkdir -p "\$D"; chmod 700 "\$D"
cp -p "\$HERMES_HOME/.env" "\$D/env-root.\$TS"
for p in <profil1> <profil2>; do cp -p "/opt/data/profiles/\$p/.env" "\$D/env-\$p.\$TS"; done
```

3. **Retirer la ligne, pas le fichier.** Filtrer par nom de clé en préservant commentaires et blancs, puis remettre le mode `600`.

```python
from pathlib import Path
KEYS = {'KEY_A', 'KEY_B'}
p = Path('$HERMES_HOME/.env')
out, removed = [], []
for ln in p.read_text(errors='replace').splitlines(keepends=True):
    s = ln.strip()
    key = s.partition('=')[0].strip() if ('=' in s and not s.startswith('#')) else None
    if key in KEYS:
        removed.append(key)
    else:
        out.append(ln)
p.write_text(''.join(out), encoding='utf-8')
p.chmod(0o600)
print('retirees :', sorted(removed))
```

4. **Re-vérifier après retrait** : `hydrate_profile_secret_sources()` doit encore rendre les variables, sinon la copie `.env` servait réellement et la sauvegarde doit être restaurée.

Un `grep -cE '^(KEY_A|KEY_B)=` sur chaque `.env` confirme qu'aucune copie en clair ne subsiste. Sous 1Password (`override_existing: true`) une copie oubliée est masquée, pas supprimée : elle ressort à la prochaine rotation du vault.

## `op://` par NOM d'item : fragile au renommage — PROUVÉ

Une référence `op://<vault>/<item>/<field>` adresse l'item **par son nom**. Renommer, déplacer ou recatégoriser l'item dans 1Password rend le mapping mort : `op read` échoue sur « isn't an item in the \"<vault>\" vault », et `hermes secrets onepassword status` affiche toujours la référence sans signaler qu'elle est irrésolvable.

Après toute édition du vault par l'utilisateur (création d'items, renommage, rangement), **revalider chaque référence avec `op read`** avant de déclarer la config vivante :

```bash
op read "op://Hermes/KEY_A/credential" >/dev/null 2>&1 && echo OK || echo 'MAPPING MORT'
```

Réparer par un `remove` puis un `set` sur le nouveau nom. `remove` sur une référence morte échoue lui aussi mais retire bien le mapping : considérer le retrait fait dès que la ligne « removed mapping » apparaît.

Pour une référence destinée à durer, viser l'**UUID** de l'item (`op://<vault>/<uuid>/<field>`) plutôt que son nom : `op item get <item> --vault <vault> --format json` le rend dans `id`.

**Convention de champ** : sur un item `API_CREDENTIAL` créé côté 1Password, le champ porteur de valeur est `credential` (libellé `identifiant`). `notesPlain`, `username`, `type`, `filename`, `validFrom`, `expires` et `hostname` sont présents mais vides. Lire la structure réelle avant de bâtir la référence — ne pas supposer `password`.

## Ne pas capturer

L'absence de `bws`/`op` sur un hôte est un état d'environnement, pas une règle. La règle durable est : **vérifier `command -v` avant de promettre Bitwarden ou 1Password**, les assistants `setup` sachant installer leur CLI eux-mêmes.
