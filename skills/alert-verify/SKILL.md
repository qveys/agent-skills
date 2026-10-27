---
name: alert-verify
description: Use when verifying a Grafana/Telegram alert is real.
version: 1.0.0
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [grafana, prometheus, alerting, my-supervision, verification]
---

# Vérifier une notification d'alerte (my-supervision)

## When to Use

L'utilisateur colle une notification Telegram/Grafana (ou un chiffre de dashboard) et demande si elle est vraie, bien calculée, ou du bruit. Aussi pour qualifier une alerte avant de proposer un changement de seuil.

Répond à 3 questions : **A** la notification est-elle réelle, **B** est-elle bien calculée, **C** reflète-t-elle la machine (hors périmètre : nécessite un accès hôte, que l'utilisateur n'accorde pas par défaut — proposer la commande exacte à lancer sur l'hôte plutôt que demander un shell).

## Accès (lecture seule, prouvé 403 sur toute écriture)

- Compte de service Grafana `sa-1-hermes` (Viewer). Secrets dans 1Password, vault `Hermes` :
  - `Grafana Hermes Token` → champ `credential`
  - `Hermes Cloudflare Service Token` → `username` = Client-Id, `credential` = Client-Secret
- Le service account 1Password exige `--vault Hermes` sur `op item get`.
- Helper : `scripts/gq` (sélectionne `scripts/gq.<profil>.env` selon `HERMES_HOME`, sans repli vers un autre profil) → `scripts/gq.sh`. Les `.env` ne contiennent que des références `op://`.
- Profils : `default` → compte `sa-1-hermes` ; `vigie` → `Grafana Vigie Token` (activer en renommant `gq.vigie.env.pending` → `gq.vigie.env` quand l'item existe).
- Un profil = un compte de service + son propre `gq.<profil>.env` (audit Grafana distinct, révocation indépendante) ; ne pas réutiliser le jeton d'un autre profil.
- Toute nouvelle prise d'accès : prouver le moindre privilège devant l'utilisateur (lecture `200`, tentatives d'écriture folders/dashboards/alert-rules → `403`) avant de s'en servir. Ne jamais appeler un endpoint qui écrit ou envoie (ex. test de contact point).

Prérequis : `GRAFANA_URL` (URL de base de Grafana, sans slash final) exporté ou défini dans le fichier `gq.<profil>.env` avec les références `op://`.

```bash
S=<clone agent-skills>/skills/alert-verify/scripts   # dépôt agent-skills cloné sur le serveur Hermes
G="$S/gq"   # choisit gq.<profil>.env selon HERMES_HOME
$G GET /api/user                      # identité
$G GET '/api/prometheus/grafana/api/v1/alerts'   # états + activeAt
P=/api/datasources/proxy/uid/synology-prometheus/api/v1
$G GET "$P/query_range?query=<urlencoded>&start=<unix>&end=<unix>&step=300"
```
Dernière ligne de sortie = `HTTP <code>` (retirer avec `sed '$d'`). Ne jamais `op read` / afficher un secret.

## Procédure

1. Trouver la règle : `grep -rn "<titre>" stack/grafana/provisioning/alerting/` (titre = alertname).
2. Gabarit : `stack/grafana/provisioning/alerting/contactpoints.yml` (`nas.telegram.firing`) — emoji = severity, `🕒` = StartsAt local.
3. Logique : `sh stack/tests/test-alert-logic.sh` (promtool, cas dans `stack/tests/alert-logic-cases.yml`).
4. Valeurs réelles : rejouer l'expr de la règle **et ses sous-termes** (ex. numérateur, filtre de volume) en query_range autour de StartsAt (heures CEST = UTC+2).
5. Croiser avec `activeAt` de `/api/prometheus/grafana/api/v1/alerts` et lire les audits `docs/alerting/`.
6. Verdict en tableau : réel / calcul juste / actionnable, chaque ligne PROUVÉ ou SUPPOSÉ.

## Pièges

- Un « nouveau » message peut être une ré-émission après un creux bref sous le seuil (ex. pic de trafic qui fait baisser un ratio) : regarder la série, pas seulement l'instant.
- Les règles sans annotation `description` n'envoient aucune valeur : la vérification exige Prometheus.
- Ne jamais conclure « bruit » ni « vrai problème réseau » sur l'instant : remonter 14 j (query_range step 1h) et corréler le début avec les tags/merges (`git log --tags --simplify-by-decoration --format='%ci %d %s'`). Un audit antérieur peut s'être trompé ; les données du jour priment.
- Un même saut simultané sur plusieurs hôtes au même collecteur = cause déployée par nous, pas le réseau.
- TCP retransmits : ventiler en `TcpExt_TCPTimeouts` / `TCPSynRetrans` / fast retrans, `node_sockstat_TCP_orphan`, ICMP out vs in. TCPTimeouts ≈ RetransSegs + orphelins > 0 + ICMP out = in ⇒ un REJECT local (iptables `-m owner` sans `--syn`) rejette les FIN de sockets orphelines, qui n'ont plus de propriétaire.
- Échec d'un canal de notification (Telegram, Ntfy/webhook) : `grafana_alerting_notifications_failed_total{integration=...}` vs `_total` (un `_total` qui monte sans échec = livraison rétablie), et les logs Grafana dans Loki (`Notify for alerts failed`). `connection refused` = rien n'écoute côté cible (service/daemon tombé), pas un problème de jeton ou de payload. Un canal de secours sans alerte sur ses propres échecs peut rester en panne des jours : le vérifier.
- Profil `vigie` : qualifie les alertes en silence (jamais de notification, Grafana est le seul canal vers l'utilisateur) et écrit un verdict JSONL par alerte dans `/opt/data/profiles/vigie/workspace/alert-verdicts/<AAAA-MM>.jsonl` ; lire ce fichier d'abord quand l'utilisateur transmet une notification.
- Diagnostic lourd (14 j, ventilation, Loki) : déléguer à un sous-agent en lecture seule avec le helper ci-dessus et exiger un rapport PROUVÉ/SUPPOSÉ + commandes hôte pour trancher.
