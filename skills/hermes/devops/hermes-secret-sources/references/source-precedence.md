# Précédence entre sources de secrets

Échelle appliquée par `agent/secret_sources/registry.py::apply_all()`, du plus spécifique au
plus général :

1. **`secrets.preserve_existing: [VAR]`** — la valeur `.env`/shell gagne toujours, même contre
   une source en `override_existing: true`. Réserve aux secrets qui diffèrent volontairement
   par profil (ex. un token de plateforme propre à chaque profil).
2. **Valeur `.env`/shell préexistante** — sauf si la source gagnante a `override_existing: true`.
3. **Sources mappées** (`op://` explicites, `env:` renseigné) — classent avant les sources bulk.
4. **Sources bulk** (dump d'un projet entier) — à forme égale, la première source qui claim la
   variable gagne ; les suivantes sont ignorées avec un avertissement, jamais en silence.

`override_existing` ne s'applique **jamais** entre deux sources : il n'écrase que le `.env`.
Aucune source ne peut écraser le token d'amorçage d'une autre.

## `override_existing` par défaut, par source

| Source | Défaut | Conséquence |
|---|---|---|
| `onepassword` | `true` | le vault écrase une valeur oubliée dans `.env` |
| `bitwarden` | `true` | idem, la rotation centrale prend effet sans nettoyer `.env` |
| `command` | `false` | le `.env` gagne — l'inverse des deux autres |

**Ne jamais raisonner par analogie entre sources.** Le défaut inversé de `command` est le piège
le plus coûteux : une valeur laissée dans `.env` est écrasée sous 1Password (donc inoffensive)
mais gagne sous `command` (donc on croit être protégé alors que la valeur en clair est
toujours lue). Après toute migration vers `command`, retirer la ligne du `.env` est obligatoire.

Lire le défaut dans la source plutôt que le supposer : `agent/secret_sources/<src>.py`,
méthode `override_existing(cfg)`.

## Alias de profil

Actif par défaut (`secrets.profile_alias: false` pour le désactiver). Sous un profil nommé, une
variable `FOO_<PROFILE>` fournie par la source hydrate aussi `FOO`, ce qui permet à un vault
partagé de porter des valeurs distinctes par profil.

Restrictions :
- seuls les suffixes de credential sont aliasés (`_API_KEY`, `_TOKEN`, `_SECRET`, `_KEY`,
  `_PASSWORD`) ; un nom arbitraire suffixé n'hydrate rien ;
- le suffixe est le nom du profil en majuscules, tirets remplacés par `_` (`promo-scout` →
  `_PROMO_SCOUT`) ;
- une variable fournie directement sous son nom canonique bat toujours l'alias.

Utile pour un seul token de plateforme partagé entre profils, inutile — et risqué — si chaque
profil doit porter sa propre valeur sans alias.

## Sources activables simultanément

On peut combiner plusieurs sources (ex. un projet Bitwarden d'équipe + un vault 1Password
personnel). L'ordre explicite se donne par `secrets.sources: [<nom>, …]` ; à défaut, l'ordre
d'enregistrement s'applique. Les sources mappées restent prioritaires quelle que soit la liste.

Un doublon sur une même variable produit toujours un avertissement au démarrage — le traiter
comme un signal de configuration à corriger, pas comme un bruit.
