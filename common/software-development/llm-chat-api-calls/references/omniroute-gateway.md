# OmniRoute : passerelle LLM de l'instance

OmniRoute (dépôt `cheaper-inference/OmniRoute`) est le routeur LLM auto-hébergé de cette
instance : les clés `hermes` des profils Hermes passent par lui vers les providers amont.
Quand une session Hermes voit une panne « provider » (clé rejetée, modèles indisponibles),
vérifier OmniRoute AVANT de soupçonner la clé ou le provider amont.

## Accès

- `https://omniroute.quentinveys.be`, Cloudflare Access devant : chaque requête porte
  `CF-Access-Client-Id` + `CF-Access-Client-Secret` + `Authorization: Bearer <clé>`.
- Clé de service lue du vault 1Password (item `OMNIROUTE_API_KEY`), passée par variable
  shell, jamais affichée ni loggée (règle 1password).
- Endpoints vérifiés : `/api/health`, `/api/pricing` (table de prix complète, par provider
  → modèle → `{input, output, cached, reasoning, cache_creation}` en $/M tokens),
  `/api/pricing/models` (catalogue), `/api/models` (modèles servis et disponibilité),
  `/api/settings/feature-flags` (flags runtime avec `effectiveValue` et `source`).
- Un 404 sur un endpoint annoncé par le dépôt = version déployée en retard, pas
  fonctionnalité absente du produit : vérifier la version déployée avant de conclure.

## Diagnostic d'un blocage de clé

Mécanisme : chaque clé porte un budget USD (jour + semaine). Le compteur additionne l'usage
TARIFÉ (modèle présent dans `/api/pricing`) et l'usage NON TARIFÉ, ce dernier pouvant être
étalonné sur le prix le plus élevé des modèles touchés. Une clé saine peut donc être
rejetée uniquement à cause d'usage non tarifé — « fail closed » — sans dépense réelle au
niveau du budget.

Procédure (lecture seule d'abord) :

1. Lire `/api/settings/feature-flags` et chercher le flag de dérogation
   `USAGE_LIMIT_IGNORE_UNPRICED` : `effectiveValue` (true = usage non tarifé ignoré) et
   `source` (`db` = persisté). Flag actif + jobs repassés au vert = cause traitée.
2. Estimer la dépense réelle sur une fenêtre passée avant de conclure à un « quota
   épuisé » : une journée de jobs Hermes peut coûter une fraction de dollar. Un budget de
   quelques dollars/jour et quelques dizaines/semaine est correctement dimensionné —
   c'est le fail-closed qui bloque, pas la consommation. Un routeur n'est pas une clé
   fournisseur : son message d'erreur décrit le compteur interne, pas un quota amont.
3. Avant de « corriger la tarification », comparer les providers concernés : plusieurs
   entrées de la table peuvent être des miroirs stricts (mêmes modèles, mêmes prix).
   Calculer le delta des deux JSON : delta = 0 → l'hypothèse « lignes de prix
   manquantes » est invalidée ; l'usage non tarifé vient d'ailleurs (usage non attribuable
   à un combo provider/modèle), et la version déployée n'expose alors aucun endpoint pour
   l'énumérer — diagnostiquer par recoupements (flag, dépense passée, table de prix).

## Corrections (auth management requise)

- `PATCH /api/pricing` — body `{provider: {model: {input, output, cached, ...}}}` : la
  fusion est faite par modèle côté serveur (INSERT OR REPLACE dans le store `pricing`),
  sans reset des autres lignes. Vérifier par GET après coup.
- Feature flag : PATCH sur `/api/settings/feature-flags` (clé + valeur), persisté en db.
  Le flag qui ignore l'usage non tarifé traite la cause du blocage ; sa contrepartie
  (dépense non tarifée invisible du budget) se compense par un contrôle externe
  périodique de la dépense (job cron), pas en retirant le flag.
- Un usage réellement non tarifé côté produit se règle à la source par une PR au dépôt
  (nouveaux tarifs ou endpoint d'énumération de l'usage non tarifé) ; la CI du dépôt fait foi.
