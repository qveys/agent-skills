# Stocker un credential de service dans `$HERMES_HOME/.env`

## Résolution du chemin

`$HERMES_HOME/.env` (sur cette instance : `/opt/data/.env` pour la racine, `/opt/data/profiles/<nom>/.env` pour un profil). Ne jamais coder `~/.hermes` en dur : résoudre depuis l'environnement, le `.env` d'un profil vit sous son propre `$HERMES_HOME`.

## Le binaire CLI n'est pas toujours dans le PATH

Dans un déploiement conteneurisé le lanceur peut vivre hors PATH. Le localiser AVANT de l'invoquer, puis l'appeler par chemin absolu :

```bash
command -v hermes || ls /opt/hermes/.venv/bin/hermes
/opt/hermes/.venv/bin/hermes secrets --help   # exemple d'appel par chemin absolu
```

## Écriture par le writer officiel (à préférer)

Passe par le même parseur que les loaders : une suppression ultérieure ne peut pas ressusciter une ligne dupliquée.

```bash
/opt/hermes/.venv/bin/python -c "
from hermes_cli.config import save_env_value, get_env_path
print(get_env_path())
save_env_value('SERVICE_API_KEY', 'VALUE')
"
```

Ce que fait `save_env_value` : supprime les retours à la ligne, rejette les glyphes non-ASCII (un copier-coller depuis un PDF casse les en-têtes HTTP), met entre guillemets les valeurs contenant espaces ou `#`, écrit via fichier temporaire + fsync + rename, et **préserve le mode existant** du fichier.

Suppression :

```bash
/opt/hermes/.venv/bin/python -c "
from hermes_cli.config import remove_env_value
print(remove_env_value('SERVICE_API_KEY'))
"
```

## One-liner shell (quand seul un shell est disponible)

Idempotent et préservant le mode :

```bash
ENVF="$HERMES_HOME/.env"; KEY=SERVICE_API_KEY
if grep -q "^${KEY}=" "$ENVF"; then
  sed -i "s|^${KEY}=.*|${KEY}=NEW_VALUE|" "$ENVF"
else
  printf '%s=%s\n' "$KEY" "NEW_VALUE" >> "$ENVF"
fi
chmod 600 "$ENVF"
```

## Rituel de vérification (avant de remettre une recette à l'utilisateur)

1. Noter `stat -c %s "$ENVF"` et `stat -c '%a %U:%G' "$ENVF"`.
2. Écrire une valeur bidon ; confirmer la présence de la ligne et que le mode vaut toujours `600`.
3. Supprimer la clé ; confirmer que la taille en octets est revenue à la valeur d'origine et que `grep -c KEY` rend 0.
4. Prouver la présence **sans exposer la valeur** : `grep "^KEY=" "$ENVF" | sed 's/=.*/=<masque>/'`.

## Jamais

- Jamais de credential dans `config.yaml`, un skill, la mémoire, un dépôt Git ou une ligne de log.
- Jamais d'`echo` de la valeur pour « confirmer » l'écriture.
- Jamais deux lignes pour le même service dans `.env` : une seule ligne, réécrite en place.

## Après l'écriture

Le process en cours a déjà figé son environnement : annoncer qu'une **session neuve** est requise, puis faire l'appel authentifié de vérification dans cette session neuve.
