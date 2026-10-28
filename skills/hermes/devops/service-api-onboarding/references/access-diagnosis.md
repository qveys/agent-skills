# Diagnostiquer un mur d'accès devant une API de service

Sonder en headers AVANT de conclure quoi que ce soit sur l'API elle-même : un status seul ne dit pas si le réseau, le SSO ou le credential est en cause.

```bash
curl -s -o /dev/null -w 'code=%{http_code}\n' --max-time 15 https://host/path
curl -sI --max-time 15 https://host/path          # en-têtes : c'est là qu'est le diagnostic
```

## Motifs de mur

| Signal observé | Ce que c'est | Portée du remède |
|---|---|---|
| `302` vers `*.cloudflareaccess.com/cdn-cgi/access/login` + `www-authenticate: Cloudflare-Access resource_metadata=...` | Politique Cloudflare Zero Trust Access posée sur tout le domaine | Réseau, pas credential |
| `401`/`403` rendu par l'origine elle-même (pas de redirection SSO) | L'origine est joignable ; c'est le header d'auth qui manque ou est invalide | Credential |

Le premier motif est **prouvé** sur le domaine du VPS (`<domaine>`) : tout le domaine, y compris `/swagger` et `/api/*`, est derrière Cloudflare Access. Compléter ce tableau au fur et à mesure d'autres murs rencontrés, avec le signal exact qui les identifie.

## Cloudflare Access — trois remèdes, du moins au plus exposé

1. **Service Token** (recommandé). Zero Trust → Service Auth → créer un token ; passer `CF-Access-Client-Id` et `CF-Access-Client-Secret` en en-têtes sur chaque appel. Coûte deux secrets de plus dans `.env`, mais ne touche à aucune politique existante.
2. **Politique Bypass sur le chemin exact** (`/api/*`, `/swagger`). La clé API du service devient le seul gardien : acceptable seulement si elle est forte, scopée à l'organisation et rate-limitée.
3. **Appeler depuis l'origine** (SSH, `docker exec`, localhost) : aucun Cloudflare dans le chemin, aucun secret supplémentaire — mais suppose un accès shell à l'hôte.

## La sonde qui fait foi : l'appel COMPOSÉ

Un `302` renvoyé à un appel porteur de la seule clé métier ne dit rien de la validité de cette
clé — le SSO l'a interceptée avant l'origine. La seule sonde concluante porte les deux familles
d'en-têtes simultanément :

```bash
curl -s -o /dev/null -w 'code=%{http_code}\n' --max-time 20 \
  -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" \
  -H "x-api-key: $SERVICE_API_KEY" \
  https://host/api/trpc/project.all
```

Lecture du résultat :

| Code | Conclusion |
|---|---|
| `200` | Réseau, SSO et credential validés d'un coup |
| `401`/`403` | Seul cas où la clé métier est réellement en cause |
| `302` vers `cloudflareaccess.com` | Le Service Token n'est pas reconnu (politique, token révoqué) — la clé métier reste non testée |

## Schéma d'auth : le lire, ne pas le deviner

Chercher dans la doc du service la section sécurité/autorisation avant d'écrire la première requête. Exemple vérifié — Dokploy attend la clé dans l'en-tête `x-api-key`, clés scopées à l'organisation, avec `rateLimitEnabled` / `rateLimitTimeWindow` / expiration configurables à la création :

```bash
curl -H "x-api-key: $SERVICE_API_KEY" https://host/api/trpc/project.all
```

Un endpoint de liste en lecture seule est la meilleure sonde de vérification : il confirme d'un coup le réseau, le SSO et le credential.
