# Installateur ccusage + statusline mise en cache

Le fichier `install-ccusage-statusline.mjs` installe ou met à jour, sans sudo :

- une copie isolée de `ccusage` sous le profil utilisateur ;
- un producteur périodique hors du chemin de rendu ;
- un cache JSON unique, horodaté et écrit atomiquement ;
- une statusline qui ne lance jamais `ccusage` ;
- un LaunchAgent utilisateur sur macOS ou une tâche planifiée utilisateur sur Windows ;
- `statusLine.command` et `refreshInterval: 120` dans `settings.json`.

Tous les autres champs de `settings.json` sont conservés. L'ancien script de statusline n'est pas supprimé. Chaque fichier remplacé est sauvegardé avec le suffixe `.backup-YYYYMMDD-HHMMSS`, et l'installateur imprime la commande exacte de retour arrière.

## Prérequis

Node.js et npm doivent être disponibles dans le `PATH`. Ce sont déjà des prérequis de l'installation npm de `ccusage`.

## Installation

Sur le Mac principal, périodicité par défaut d'une heure :

```sh
chmod +x ./install-ccusage-statusline.mjs
./install-ccusage-statusline.mjs ~/.claude
```

Sur un Mac où le CPU est fortement contraint, utiliser deux heures :

```sh
./install-ccusage-statusline.mjs --interval 7200 ~/.claude
```

Deux heures réduisent de moitié les reparses coûteux par rapport au défaut d'une heure. Le temps restant du bloc de 5 h continue à décroître localement à chaque rendu à partir de l'heure de fin mise en cache ; il n'impose donc pas de recalcul fréquent.

Sous Windows PowerShell :

```powershell
node .\install-ccusage-statusline.mjs "$env:USERPROFILE\.claude"
```

L'intervalle Windows doit être divisible par 60 secondes. L'installateur utilise Python 3.8+ s'il est disponible pour le chemin de rendu rapide ; sinon il installe une variante Node fonctionnelle et affiche qu'elle doit être chronométrée sur cette machine.

Pour utiliser un `ccusage` déjà installé sans le remplacer :

```sh
./install-ccusage-statusline.mjs --ccusage-bin /chemin/vers/ccusage ~/.claude
```

La résolution automatique vérifie le `PATH`, puis les candidats explicites `/opt/homebrew/bin`, `~/.local/bin`, `/usr/local/bin`, `~/.bun/bin` et la copie gérée par l'installateur. Les équivalents utilisateur Windows (`%APPDATA%\npm`, `~\.local\bin`, `~\.bun\bin`) sont également vérifiés.

Le LaunchAgent reçoit aussi explicitement ce PATH user-space. C'est nécessaire même lorsque `ccusage` est configuré avec un chemin absolu, car le shim npm de `ccusage` lance Node avec `/usr/bin/env node` et le PATH natif de launchd se limite normalement aux répertoires système.

## Planification macOS

L'installateur charge normalement le LaunchAgent. Les commandes imprimées sont de la forme :

```sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.qveys.ccusage-status-cache.plist
launchctl kickstart -k gui/$(id -u)/com.qveys.ccusage-status-cache
launchctl bootout gui/$(id -u)/com.qveys.ccusage-status-cache
```

`--no-schedule` écrit quand même le plist, mais ne le charge pas. Cela permet de le contrôler avec `plutil -lint` avant chargement.

## Planification Windows

```powershell
schtasks /Run /TN "qveys-ccusage-status-cache"
schtasks /Delete /TN "qveys-ccusage-status-cache" /F
```

Si une tâche du même nom existait, son XML est sauvegardé avant remplacement et la commande `schtasks /Create ... /XML ... /F` de restauration est imprimée.

## Cache et fraîcheur

L'ancien fichier `daily-tokens` n'est ni lu ni écrit. Le producteur lance seulement les rapports `daily` du jour et `blocks --active`, puis écrit `metrics.json` avec :

- `produced_at` et `produced_at_epoch` ;
- l'intervalle producteur et le seuil de péremption ;
- les tokens et le coût du jour ;
- le coût, la fin et le burn rate du bloc actif.

L'écriture passe par un fichier `.tmp-<pid>` puis un renommage atomique. Aucun verrou persistant n'est utilisé. Avec une période d'une ou deux heures très supérieure à la durée attendue d'un calcul, un chevauchement normal n'est pas attendu ; le nom temporaire par PID et le renommage atomique rendent néanmoins un chevauchement accidentel inoffensif pour l'intégrité du cache. Il n'existe donc plus de répertoire-lock pouvant rester orphelin.

Le seuil par défaut vaut `2 × intervalle + 300 secondes`, soit 2 h 05 pour un producteur horaire et 4 h 05 pour un producteur toutes les deux heures. La statusline compare à la fois l'horodatage interne et le `mtime` du fichier. Au-delà du seuil, elle masque toutes les métriques mises en cache et affiche `⚠️  usage cache stale (...)`. Une valeur ancienne ne peut donc plus être présentée comme actuelle.

## Rafraîchissement à la demande

Un planificateur seul ne suffit pas : sur macOS, un job déclaré `ProcessType=Background` est traité par launchd comme *discretionary* et se retrouve différé sur batterie ou en Low Power Mode. Observé le 2026-08-03 : cache figé 4 h 45 pour un seuil de 2 h 05, quatre échéances horaires manquées malgré des fenêtres d'éveil de 17 minutes, `runs` bloqué et `last exit code = 0` — donc sans la moindre panne du producteur. Le plist généré ne déclare plus `ProcessType` ; `launchctl print` doit afficher `spawn type = daemon (3)`. `Nice` et `LowPriorityIO` sont conservés : ils ne changent pas ce classement.

En complément, dès que le cache dépasse `interval_seconds` — donc **avant** de pouvoir devenir périmé — la statusline demande une exécution du producteur. Elle n'invoque toujours pas `ccusage` elle-même : elle relance le planificateur, qui refuse déjà de démarrer une seconde instance et porte l'environnement enregistré. Aucun verrou maison n'est donc nécessaire.

La commande est écrite par l'installateur dans la configuration, sous forme de tableau d'arguments :

| Plateforme | `producer_kick_argv` |
| --- | --- |
| macOS | `["/bin/launchctl","kickstart","-p","gui/<uid>/com.qveys.ccusage-status-cache"]` |
| Windows | `["schtasks.exe","/Run","/TN","qveys-ccusage-status-cache"]` |

Avec `--no-schedule`, la clé est absente et aucune relance n'est tentée. `refresh_throttle_seconds` (par défaut `intervalle / 4`, minimum 300 s) borne les tentatives via une sentinelle `.refresh-requested` déposée à côté du cache, ce qui évite de relancer un producteur bloqué à chaque rendu. Un `↻` suffixe l'avertissement quand une relance vient d'être demandée. Les deux variantes de statusline, Python et Node, implémentent ce comportement à l'identique.

## Mesures du paquet généré sur macOS

Fixture isolée, sans chargement de LaunchAgent et sans modification de `~/.claude` :

```text
20 rendus, 120 échantillons de ps : ccusage_matches=0
all_rc_zero=true
temps sans échantillonneur : 32.478 ms, 31.621 ms, 31.389 ms
```

Cas dégradés :

```text
stdin vide       rc=0, ligne exploitable
JSON invalide    rc=0, ligne exploitable
{}               rc=0, ligne exploitable
champs manquants rc=0, ligne exploitable
cache absent     rc=0, avertissement "usage cache unavailable"
cache tronqué    rc=0, avertissement "usage cache invalid"
cache vieilli    rc=0, avertissement "usage cache stale", chiffres masqués
```

Le producteur de test a remplacé successivement le cache avec un nouveau `produced_at` et `daily.tokens = 27500000`. Deux passages successifs de l'installateur ont laissé les scripts, la configuration, `settings.json` et le plist à l'état `already current`. Le plist généré passe `plutil -lint`.

Ces mesures prouvent le paquet généré sur macOS. Elles ne constituent pas une mesure de performance Windows : l'installateur effectue un autotest fonctionnel sur Windows, mais le temps du fallback Node doit être mesuré sur l'hôte professionnel si Python 3.8+ n'y est pas disponible.

## Test d'installation réelle du 2026-08-02

L'installateur a ensuite été exécuté sur le Mac courant, avec un producteur horaire. Résultats :

```text
ccusage installé en user-space : 20.0.19
LaunchAgent : chargé, StartInterval=3600, Nice=10, LowPriorityIO=true
déclenchement manuel : runs=1, last exit code=0
cache renouvelé : produced_at=2026-08-02T17:06:59Z, daily.tokens=95766471
20 rendus / 129 échantillons ps : ccusage_matches=0, tous rc=0
maximum pendant l'échantillonnage : 36.351 ms
mesures isolées : 33.769 ms, 34.198 ms, 34.130 ms
```

Le premier déclenchement du LaunchAgent a révélé puis permis de corriger un défaut : bien que le shim `ccusage` fût configuré par chemin absolu, son shebang `/usr/bin/env node` échouait avec le PATH système minimal de launchd. Le plist généré fournit maintenant explicitement les chemins Homebrew et user-space. Le déclenchement suivant a terminé avec `last exit code=0` et a remplacé le cache avec un nouvel horodatage.

Les tests sur stdin vide, JSON invalide, `{}`, champs manquants, cache absent et cache tronqué ont tous rendu une ligne exploitable avec `rc=0`. Une copie du cache vieillie par `touch -t 202001010000` a affiché seulement `usage cache stale (...)`, sans coût ni tokens périmés.
