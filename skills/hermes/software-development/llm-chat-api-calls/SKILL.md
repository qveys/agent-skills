---
name: llm-chat-api-calls
description: "Use when calling an OpenAI-compatible LLM chat API robustly."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [llm, api, chat-completions, reasoning-model, openai-compatible, retry]
    related_skills: [service-api-onboarding, systematic-debugging]
---

# Appels LLM (chat completions) robustes

Brancher un appel à un LLM via une API compatible OpenAI (`/v1/chat/completions`) de façon
fiable, en particulier quand le modèle est un **modèle raisonnant** (ex. `stepfun/step-5-preview`
sur l'infra `nous`). Les pièges ci-dessous ont coûté plusieurs cycles de debug ; les appliquer
dès le premier appel.

## When to Use

- Écrire du code qui appelle un LLM via `/v1/chat/completions` (extraction, scoring, génération).
- Un appel LLM revient `content: null`, `HTTP 400 Model parameter is required`, ou `429`.
- Le pipeline LLM tronque ou mal-forme sa sortie JSON.

## Procédure

1. **Lire la clé au runtime, jamais dans le code/log/commit.** Depuis le fichier d'auth Hermes
   (`$HERMES_HOME/auth.json`, mode 600) : `data["providers"]["nous"]["agent_key"]`. Ne jamais
   logger la valeur.
2. **Payload minimal** : `model`, `messages[{role,content}]`, `max_tokens`, `temperature`.
3. **`model` doit toujours être résolu avant le payload.** Si `model=None` traverse la pile,
   le JSON part avec `"model": null` → `HTTP 400 Model parameter is required`. Retomber sur le
   défaut à chaque couche (`model or DEFAULT_MODEL`), pas seulement à l'entrée.
4. **Retry sur 429 et 5xx** avec backoff exponentiel (ex. `min(2**attempt*5, 40)` s). La capacité
   des modèles `:free` fluctue ; un 429 upstream n'est PAS une erreur de clé.
5. **Fallback de modèle** si le principal reste indisponible après les retries.
6. **`max_tokens` généreux pour un modèle raisonnant** (≥8000). Voir piège n°1.
7. **Parsing JSON tolérant** : enlever les fences ```json, réparer les structures tronquées,
   normaliser les formes de sortie (dict OU string). Voir pièges n°2 et n°3.

## Pièges

1. **Un modèle raisonnant consomme `max_tokens` dans le `reasoning` AVANT de produire `content`.**
   Avec un `max_tokens` trop bas, la réponse revient `content: null` et `finish_reason: length` —
   le raisonnement a épuisé le budget. Symptôme trompeur : on croit le modèle muet. Correctif :
   `max_tokens` ≥ 8000 (monté jusqu'à 32000 en retry), et sur `content` vide, retenter avec un
   budget doublé au lieu de conclure à une panne.
2. **La sortie JSON peut être tronquée à `finish_reason: length`** (chaîne non terminée).
   Réparer en refermant les structures ouvertes (`}`/`]`) avant de jeter l'erreur ; en dernier
   recours, extraire le dernier objet/array JSON complet via regex.
3. **Le modèle peut rendre `"technologies": ["Nom1", "Nom2"]` (liste de strings) au lieu de
   dicts.** Normaliser : un string devient `{"name": string}`. Ne pas exiger un seul schéma.
4. **Un 429 n'est pas une erreur de clé.** Le message `temporarily at capacity upstream` signifie
   saturation du modèle, pas credential invalide. Retenter, ne pas ré-authentifier.
5. **`content` vide avec `finish_reason: length` ≠ panne** — c'est le piège n°1. Toujours lire
   `finish_reason` et `usage.completion_tokens` dans le message d'erreur pour diagnostiquer.

## Vérification

- Tester l'appel avec `curl` direct sur le modèle ET avec `max_tokens` élevé avant d'intégrer.
- Écrire un test unitaire qui vérifie : modèle raisonnant → `content` non vide ; 429 → retry
  réussi ; sortie string → normalisée en dict.

## Voir aussi

- `service-api-onboarding` — murs d'accès, secrets, mais **exclut** les LLM providers.
- `systematic-debugging` — méthodologie quand un appel LLM échoue de façon inattendue.
