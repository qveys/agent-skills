# Pièges de la CLI `op`

## Un service account exige `--vault`

`op item get` et `op item list` échouent sur « a vault query must be provided when this
command is called by a service account » sans `--vault`. Un compte utilisateur, lui, n'en a
pas besoin — le code qui marche en session interactive casse sous service account.

```bash
op item list --vault <Vault> --format json
op item get "<Item>" --vault <Vault> --format json
```

`op read` sur une référence `op://` complète n'a pas besoin de `--vault` : la référence
porte déjà le coffre.

## `op` écrit un avis sur stderr : ne jamais fusionner avec `2>&1`

Quand la configuration n'est pas au chemin standard, `op` émet « Using configuration at
non-standard location "/tmp/.op" » **sur stderr**. Un `2>&1` fait remonter cette ligne en tête
du flux et `json.load` échoue sur « Expecting value: line 1 column 1 » — alors que le JSON est
parfaitement valide juste après.

```bash
# correct
op item get "<Item>" --vault <Vault> --format json 2>/dev/null > item.json

# casse tout parseur JSON en aval
op item get "<Item>" --vault <Vault> --format json 2>&1 | python3 -m json.tool
```

Même écueil avec `op whoami` : le diagnostic utile est dans la sortie, l'avis dans stderr.
Rediriger stderr vers `/dev/null` dès qu'un parseur suit, jamais l'inverse.

## Un service account est souvent en lecture seule

`op item create` peut échouer sur « (101) You do not have permission to perform this action ».
Tester la permission d'écriture **avant** de planifier une création d'item : sinon on prévient
l'utilisateur qu'une clé est migrée alors que l'item n'existe pas.

Conséquence pratique : l'utilisateur crée les items depuis son compte, l'agent se contente de
mapper des références existantes. Ne pas tenter de contourner une permission refusée.

## Catégorie d'item : le libellé exact

`--category` attend le **libellé affiché**, pas la constante :

```bash
--category "API Credential"     # correct
--category API_CREDENTIAL       # refusé : "is not a recognized item category"
```

La constante apparaît dans `op item list --format json` (`category`), ce qui trompe : le
affichage JSON et la saisie CLI n'utilisent pas le même vocabulaire.

## Champ : découvrir le nom avant de référencer

Ne pas supposer que le champ secret s'appelle `password`. Lister les champs avec un script
qui n'affiche que les noms et la présence d'une valeur :

```bash
op item get "<Item>" --vault <Vault> --format json | python3 -c "
import json,sys
d=json.load(sys.stdin)
for f in d.get('fields',[]):
    lbl=f.get('label') or f.get('id')
    print(f\"  {lbl!r:30} id={f.get('id'):14} valeur={bool(f.get('value'))}\")
"
```

Le champ d'une référence `op://` est le **`id`** du champ, pas forcément son libellé. Un
libellé localisé (« identifiant ») masque un `id` stable (`credential`) : référencer l'`id`.

Ce n'est pas une préférence de style : un libellé portant une apostrophe rend la référence
**invalide**. `op read "op://V/I/Nom d'utilisateur"` échoue sur « invalid character in secret
reference: ''' », et URL-encoder l'espace en `%20` ne sauve rien — l'apostrophe reste. Référencer
systématiquement l'`id`.

Vérifier qu'une référence se résout sans l'afficher — n'imprimer que la longueur :

```bash
op read "op://<Vault>/<Item>/<field>" | wc -c
```

## Renommer un item casse les références par nom

Une référence `op://Vault/Item/field` indexée par **nom** devient invalide si l'item est
renommé : `op read` échoue sur « isn't an item in the "<Vault>" vault », et les mappings déjà
écrits dans `config.yaml` cessent silencieusement de résoudre.

Après tout renommage côté vault, re-tester chaque référence existante et remapper celles qui
échouent (`hermes secrets <src> remove VAR` puis `set VAR` avec la nouvelle référence).

## Ne jamais deviner un titre d'item

`op item get "<Item>"` échoue sur « isn't an item in the \"<Vault>\" vault » dès que le titre
diffère d'un caractère — et les titres portés par l'utilisateur ne sont pas fiables : on a vu
« Cloudlfare » là où le nom correct est « Cloudflare », avec l'item réel intitulé
`VPS-DOKPLOY Cloudlfare Service Auth` alors que la demande parlait de `VPS-DOKPLOY`.

Toujours `op item list --vault <V>` d'abord, puis viser l'**UUID** dans la référence `op://` :
l'UUID est insensible aux coquilles et aux renommages, le nom ne l'est jamais.

## Écrire une valeur dans un item sans l'exposer

```bash
TOK=$(grep '^VAR=' "$ENV" | head -1 | cut -d= -f2- | tr -d '"\'\r')
op item create --vault <Vault> --category "API Credential" --title VAR -- "credential=$TOK"
unset TOK
```

Le `--` avant l'affectation est requis : sans lui, `op` tente de parser `credential=…` comme
JSON sur son entrée standard et échoue sur « invalid JSON in piped input ».

Toujours `unset` la variable juste après, et ne jamais faire transiter la valeur par un
fichier de scratch non nettoyé.
