---
name: vault-skill-sync
description: "Use when a vault skill diverges from its workspace copy."
version: 1.1.0
author: hermes-curator
license: MIT
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [vault, skills, git, hermes-profil]
    related_skills: [obsidian]
---

# vault-skill-sync

Les skills du vault (`daily-review`, `done`, `weekly-review`, `inbox-triage`, `manage-skill`…) sont éditées dans le workspace mais exécutées depuis la copie du profil Hermes. Les deux divergent, et c'est la copie du profil qui pilote le comportement réel.

## When to Use

- Une skill du vault se comporte autrement que ce que son contenu annonce.
- Une skill vient d'être modifiée dans `.agents/` et doit être recopiée dans le profil.
- Une tâche écrit dans le vault ou le workspace et doit être close proprement.

## Source de vérité

- Référence (vault/workspace brain de cette instance) : `/workspace/brain/.agents/skills/<nom>/SKILL.md`
- Copie active : `/opt/data/profiles/<profil>/skills/<nom>/SKILL.md` (profil `default` : `/opt/data/skills/<nom>/SKILL.md`)

## Procédure

1. Avant de suivre une skill dont le comportement surprend, comparer les deux copies :
   `md5sum /workspace/brain/.agents/skills/<nom>/SKILL.md /opt/data/profiles/<profil>/skills/<nom>/SKILL.md`
2. Si elles diffèrent, recopier celle du workspace vers le profil, puis recharger le contenu dans le contexte avec `skill_view(name)`. Le texte injecté au démarrage de session reste l'ancien même après la copie : la relecture est obligatoire pour agir sur la bonne version.
3. Après toute modification faite dans `.agents/`, recopier dans le profil dans la même tâche. Sinon la session suivante repart sur l'ancienne version et rejoue l'erreur corrigée.
4. Corriger en même temps la fiche process du vault (`06_OUTILS/Process/…`) et son champ `updated`, sinon skill et process se contredisent.

## Clore les écritures

Toute tâche qui écrit dans le vault ou dans le workspace se termine par un commit et un push, dans les deux dépôts : jamais d'écriture laissée non commitée. Règle permanente, obligatoire.

- Ajouter les fichiers explicitement, jamais un dossier ni `git add .`.
- Un push rejeté se rattrape par `git pull --rebase origin main` puis un nouveau push, jamais par `--force`.
- Vérifier ensuite que les deux dépôts sont propres et à jour, et le dire dans la confirmation.

## Pièges

- La copie du profil peut être en retard de plusieurs semaines sans aucun signal : ne pas supposer que la version chargée est la bonne.
- Ne pas renommer ni déplacer un post-it d'état déjà écrit : la garde d'écriture refuse d'écraser un fichier jamais relu. Créer le nouveau nom puis retirer l'ancien explicitement.
- Les skills du vault sont détenues par l'utilisateur : la curation autonome ne peut pas les modifier. Une correction se fait depuis la session au premier plan, ou après `hermes curator adopt <nom>`.
