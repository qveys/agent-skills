---
name: preflight-autonome
description: >-
  Preflight avant de laisser un agent travailler en autonomie sur n'importe quel
  projet : lister les items d'une TODO, déterminer l'accès requis par item (dépôt
  git, API HTTP, base de données, CLI cloud, Docker/k8s, ssh/VPN, sudo, runner CI,
  secrets/.env, service local, GUI), le tester par une sonde lecture seule, classer
  PRÊT / CONTOURNABLE / RÉELLEMENT HUMAIN et produire un tableau AVANT de lancer la
  boucle. À utiliser dès que l'utilisateur dit « sois autonome », « laisse
  tourner », « je pars », « continue sans moi », « fais toute la TODO », parle
  d'une TODO longue, d'une session laissée ouverte, ou lance /loop ou /goal, même
  s'il ne demande pas explicitement de vérifier les accès. Pas pour une tâche
  courte et interactive où l'utilisateur répond en direct.
---

# Preflight autonome

Un agent laissé seul perd des heures sur un blocage découvert tard (accès refusé,
secret vide, service éteint) et conclut « impossible » sans diagnostic. Le
preflight déplace cette découverte AVANT la boucle, avec des preuves.

## 1. Inventaire
Pour chaque item de la TODO (fichier ou conversation), noter l'accès qu'il exige.
Deux items sur la même ressource partagent une sonde.

## 2. Type d'accès et sonde lecture seule
Une sonde = une commande, timeout court, aucun effet de bord (pas d'écriture, pas de
déploiement, pas de migration). Choisir la plus légère qui prouve l'accès :

| Type d'accès | Sonde typique |
|---|---|
| Remote git | `--git-remote` (`git ls-remote`) |
| API HTTP + token | `--http URL`, puis `--cmd` avec un appel authentifié en lecture (`GET /me`) |
| Base de données | `--cmd 'db::psql "$DATABASE_URL" -c "select 1"'` (ou mysql, redis-cli ping…) |
| CLI cloud | `--cli aws` puis `--cmd "id::aws sts get-caller-identity"` (gcloud, az…) |
| Docker / k8s | `--cmd "k8s::kubectl auth can-i get pods"`, `docker info` |
| ssh / VPN | `--ssh HOTE` ; ssh à travers un VPN/mesh : ex. un client avec ssh intégré (option dédiée, voir l'aide du script), sinon `--cmd` |
| Droits sudo | `--cmd 'sudo::sudo -n true'` |
| Runner / CI | `--cmd "ci::gh run list -L1"` ou l'API du fournisseur |
| Secrets / .env | `--env FICHIER CLE` (SET / EMPTY / ABSENT, jamais la valeur) |
| Service local | `--http http://localhost:PORT/health`, `--cmd` avec `pg_isready` |
| GUI / outil interactif | pas de sonde auto : vérifier que l'outil existe, sans cliquer |

```bash
scripts/preflight.sh --git-remote --http https://api.example.com/health \
  --env .env DATABASE_URL --cmd 'db::psql "$DATABASE_URL" -c "select 1"'
```
Options répétables, aucune sonde sans option. Sortie : `PASS|FAIL|WARN<TAB>libellé<TAB>détail`,
code retour = nombre de FAIL (plafonné à 63), 64 = erreur d'usage.
`--cmd 'libellé::commande'` (`::` obligatoire) passe par `bash -c` : entrée de confiance, et sa
sortie peut contenir des secrets (seuls les identifiants d'URL sont masqués). Utiliser des
quotes simples : la variable est alors développée par le script, pas visible dans `ps`.
Les sondes intégrées n'affichent jamais un secret ; `--cmd` affiche sa sortie : ne pas l'utiliser pour une commande qui imprime un secret, et ne jamais en consigner dans le journal.

Si le projet a un harnais d'accès ou des règles de repo (shims, wrapper de signature,
conventions de commit, proxy), les relire et les imposer dans chaque brief de
sous-agent : il hérite des fichiers de règles, pas de la conversation. Voir
`references/profils.md` (exemple de profil à adapter).

## 3. Classement
- **PRÊT** : sonde PASS.
- **CONTOURNABLE** : FAIL mais alternative existante (autre chemin réseau, autre
  identité, lecture seule suffisante, mock local) ; écrire l'alternative testée.
- **RÉELLEMENT HUMAIN** : geste physique, secret absent, validation 2FA,
  décision irréversible ; noter la cause exacte et les contournements essayés.

Ne conclure « impossible » qu'après plusieurs essais distincts (autre chemin, message
d'erreur complet, config, version), jamais sur un seul échec.

## 4. Règles d'autonomie
- Un blocage humain ne stoppe pas la boucle : passer à l'item suivant, lister ces
  blocages à la fin.
- Décision à prendre : choisir l'option réversible recommandée, consigner, signaler après.
- Aucune action irréversible (suppression, push forcé, migration destructive,
  dépense, envoi externe) sans accord explicite.

## 5. Condition d'arrêt vérifiable
Définir « fini » avant de lancer : si `/goal` existe, proposer à l'utilisateur
(l'agent ne peut pas le taper lui-même) un objectif mesurable (TODO vide, tests verts)
plus une borne (« ou stop après N tours »). Sinon l'écrire dans le fichier de suivi.
Ne pas s'arrêter sur « rien de nouveau » tant que la condition n'est pas remplie.

## 6. Journal de preuves
Pour chaque item : OK/ÉCHEC + sortie brute (secrets masqués) dans le fichier de suivi.

## Sortie attendue
Tableau, avant de lancer la boucle :

| item | accès | sonde | résultat | classe | action |
|---|---|---|---|---|---|
