---
name: service-api-onboarding
description: "Use when wiring an external service API to Hermes."
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [api, credentials, secrets, dokploy, cloudflare, vps]
---

# Onboarding d'une API de service externe

Brancher un service tiers (Dokploy, Cloudflare, un panneau VPS, toute API REST/tRPC) sur Hermes pour que l'agent puisse l'appeler pour de vrai — et non se contenter de lire sa doc.

## When to Use

- L'utilisateur veut donner à Hermes l'accès à une API distante (panneau d'hébergement, VPS, SaaS interne) et parle de « stocker la clé API de façon sécurisée », ou demande un endroit « plus sûr que `.env` ».
- Une clé ou un token doit entrer dans `.env`, ou une clé déjà présente doit être tournée / supprimée.
- Un endpoint d'API rend 3xx vers un portail SSO, 401 ou 403 et il faut établir si le problème est réseau, politique d'accès ou credential.

Ne PAS utiliser pour : appeler un LLM provider (voir `hermes-agent`), ni pour récupérer une page web bloquée (voir `blocked-page-recovery`).

## Règles permanentes

1. **Un secret va dans `$HERMES_HOME/.env`, jamais dans `config.yaml`.** `.env` porte les valeurs, `config.yaml` porte les réglages. Le fichier reste en mode `600`.
2. **Ne jamais demander à l'utilisateur de coller un secret dans le chat** — pas même une valeur de test. Les transcripts de session et `state.db` le persistent. Lui remettre une commande à exécuter lui-même, ou écrire via `save_env_value` avec une valeur fournie hors bande ; un helper bidon se construit aussi hors bande.
3. **Vérifier la procédure d'écriture AVANT de la remettre à l'utilisateur.** Écrire une valeur bidon, contrôler que la ligne arrive et que mode et taille sont préservés, puis la supprimer et contrôler que le fichier est revenu à l'identique. Une recette de credential non testée n'est pas une recette.
4. **Vérifier l'accessibilité par l'appel COMPOSÉ, pas header par header.** Quand un SSO (Cloudflare Access) se superpose à une clé métier, la sonde valide porte les deux familles d'en-têtes à la fois : un `302` renvoyé à un appel porteur de la seule clé métier ne dit RIEN de la validité de cette clé — le SSO l'a interceptée avant l'origine. Sonder nu, puis composé ; c'est le second code HTTP qui fait foi.
5. **Laisser `security.redact_secrets` actif** (défaut quand la clé est absente de `config.yaml`) : il masque les sorties d'outil en forme de secret avant qu'elles n'entrent dans le contexte et les logs. Ne jamais le désactiver pour « débugger » une clé.
6. **Énoncer la surface d'exposition.** Quand `hermes-home` est un volume partagé entre plusieurs conteneurs (typique : agent + webui), une clé dans `.env` est lisible par tous. Le dire au moment d'en ajouter une.
7. **Ne jamais écrire un helper de test de credential par heredoc shell.** Le rédacteur réécrit la ligne `KEY=valeur` avant le disque et le fichier arrive muet. Écrire le fichier avec `write_file` en construisant la ligne via une variable.
8. **Un secret ne vit pas dans un seul `.env`.** Chaque profil a le sien : `$HERMES_HOME/.env` plus `profiles/<nom>/.env`. Inventorier les NOMS de tous les fichiers avant de stocker, tourner ou supprimer quoi que ce soit — sinon on migre la moitié des copies en clair et on le croit terminé.
9. **La section `secrets:` ne s'hérite pas du config racine vers les profils.** `_load_secrets_config()` lit uniquement `<home>/config.yaml` : un `hermes secrets onepassword set` fait à la racine n'a AUCUN effet sur les profils. Mapper dans chaque `config.yaml` concerné, séparément. Voir `references/external-secret-sources.md`.
10. **`hermes secrets <source> status` ne prouve PAS l'hydratation.** `status` tourne dans l'environnement complet du process ; le chemin réel des profils, `hydrate_profile_secret_sources()`, filtre cet environnement et peut rendre `{}` malgré un `status` vert annonçant « applied N secrets ». Ne déclarer une source opérationnelle qu'après avoir vu `hydrate_profile_secret_sources()` rendre la variable — et, pour 1Password, après avoir créé un `.op.env` dans chaque home.
11. **Une référence `op://` bâtie sur le NOM de l'item casse au renommage.** Renommer ou déplacer un item dans le vault rend le mapping mort silencieusement côté `status`, et `op read` échoue sur « isn't an item in the "<vault>" vault ». Après toute édition du vault par l'utilisateur, revalider chaque référence avec `op read` avant de croire la config vivante — et **préférer l'UUID d'item au nom** quand la stabilité compte.
12. **Ne retirer une ligne de `.env` qu'après égalité de valeur prouvée.** Comparer la valeur résolue par le vault à celle du `.env` par égalité de chaînes, sauvegarder les `.env` concernés dans un dossier `700`, puis retirer et re-vérifier l'hydratation. Rituel complet : `references/external-secret-sources.md`.
13. **Inventorier le vault AVANT de demander à l'utilisateur de créer un item.** Un service account ne voit que ses coffres, et l'item demandé existe déjà souvent sous un titre que l'on n'aurait pas deviné — coquille comprise. `op item list --vault <V>` en amont coûte une commande ; demander une création à l'utilisateur coûte un aller-retour.

## Cloudflare Access + Service Token (pattern prouvé)

Quand l'API cible est derrière Cloudflare Access (tout le domaine, y compris `/swagger` et `/api/*`) :

1. Créer un **Service Token** dans Zero Trust → Access → Service Auth.
2. Deux secrets en plus dans le vault : `CF_ACCESS_CLIENT_ID` et `CF_ACCESS_CLIENT_SECRET`.
3. L'appel de test et TOUS les appels opérationnels portent **les deux familles d'en-têtes simultanément** :

```bash
curl -H "CF-Access-Client-Id: $CID" -H "CF-Access-Client-Secret: $CSEC" \
     -H "x-api-key: ${SERVICE_API_KEY}" https://host/api/endpoint
```

Un appel sans les deux en-têtes CF rend `302` vers le portail SSO — ce n'est PAS un échec de la clé métier. Ne jamais conclure « clé invalide » sur un 302.

## tRPC double-encapsulation (Dokploy et assimilés)

Certains endpoints tRPC exigent un doublet `input={"json":{...}}` :

```bash
# Échoue (400 expected object)
curl -G --data-urlencode 'input={"projectId":"XXX"}' .../api/trpc/endpoint
# Passe
curl -G --data-urlencode 'input={"json":{"projectId":"XXX"}}' .../api/trpc/endpoint
```

Tester systématiquement les deux formes ; documenter la forme qui fonctionne dans la skill du service.

## Procédure

1. **Obtenir l'endpoint et le schéma d'auth.** URL de base exacte + header attendu (Dokploy : `x-api-key`). Le lire dans la doc du service, ne pas le deviner.
2. **Inventorier les secrets existants.** `scripts/inventory-env-secrets.sh` liste les NOMS de variables par `.env`, jamais les valeurs. À faire avant tout ajout, rotation ou suppression. Si la cible est 1Password, y ajouter `op item list --vault <V>` : l'item demandé par l'utilisateur existe déjà la plupart du temps, et son titre exact n'est presque jamais celui qu'on devine.
3. **Sonder l'accessibilité.** `curl -sI --max-time 15 <url>`, lire le status et `www-authenticate`. Murs et remèdes : `references/access-diagnosis.md`.
4. **Stocker le credential** avec la recette vérifiée de `references/secret-storage.md`.
5. **Vérifier par un appel authentifié réel** (endpoint de liste en lecture seule) dans une session neuve, et rapporter le code HTTP obtenu.
6. **Consigner pour l'utilisateur** : où le secret vit, qui peut le lire, comment le révoquer.

Note : après une écriture dans `.env`, une **session neuve** est nécessaire — l'environnement est figé au démarrage du process.

## Quand préférer un gestionnaire de secrets externe

Si l'utilisateur demande un stockage « plus sûr que `.env` » (fichier `.secret`, vault, coffre), la réponse est oui et elle est intégrée : trois sources tirent les clés au démarrage au lieu de les garder en clair. Détail, échelle de précédence et recette vérifiée : `references/external-secret-sources.md`.

Recommandation par défaut : la source **`command`** (helper shell local) — aucun service tiers. Bitwarden et 1Password n'apportent un gain réel que si l'utilisateur les utilise déjà ; vérifier `command -v bws op` avant de les proposer, les assistants `setup` installant leur CLI eux-mêmes.

**`override_existing` est inversé selon la source** — ne pas raisonner par analogie. `command` est en `false` (la copie `.env` restante gagne), 1Password est en `true` (le vault écrase silencieusement une valeur oubliée dans `.env`). Lire la valeur réelle avant de conclure quoi que ce soit sur une migration.

**Après toute migration hors de `.env`, supprimer la ligne de `.env`** : sous `command`, la copie en clair restante gagne la précédence et l'utilisateur se croit protégé à tort.

**Migrer profil par profil.** Une source configurée à la racine ne couvre aucun profil : refaire `secrets onepassword set` dans chaque `config.yaml` concerné, créer un `.op.env` dans chaque home, puis vérifier avec `hydrate_profile_secret_sources` sous chaque profil — `sync` et `status` ne voient pas le chemin filtré.

## Fichiers d'appui

- `references/secret-storage.md` — écriture / vérification / suppression dans `$HERMES_HOME/.env`, méthode officielle et one-liner shell.
- `references/access-diagnosis.md` — diagnostiquer et lever un mur d'accès devant une API de service (Cloudflare Access et assimilés).
- `references/external-secret-sources.md` — sortir un credential de `.env` (source `command`, `op://`, BSM), précédence, non-héritance par les profils, et piège du heredoc réécrit par le rédacteur de secrets.
- `scripts/inventory-env-secrets.sh` — inventaire des NOMS de secrets par `.env` (racine + profils), sans jamais exposer de valeur.