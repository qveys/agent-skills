---
name: sync-profile-skills
description: "Aligner une skill du profil sur sa source workspace."
metadata:
  opencode/autoinvoke: false
---

# sync-profile-skills

## Rôle

Dans le runtime Hermes, les skills du vault ne se dupliquent jamais : un **seul symlink de dossier** `<dossier partagé>/vault` pointe vers l'unique source du workspace (`/workspace/brain/.agents/skills`). Tous les profils le chargent par `skills.external_dirs` (dossier partagé, ex. clone du dépôt `agent-skills`). Plus de copie, plus de dérive possible. Pour qu'un profil ne voie pas toutes les skills du vault, on les masque dans sa `config.yaml` (`skills.disabled`), on ne multiplie pas les liens. Seules les skills propres au profil (catégories `apple`, `creative`, `research`…) restent des vrais répertoires.

Déclencheurs : l'utilisateur signale qu'une procédure qu'il a déjà corrigée réapparaît, ou une skill du crew va être suivie pour une tâche à écriture.

Une copie en retard est plus dangereuse qu'une skill absente : l'agent applique une procédure déjà remplacée, sans aucun signal, et l'utilisateur découvre l'écart en la voyant à l'œuvre.

## Le script du workspace

Quand le dépôt brain est accessible, ne pas comparer skill par skill à la main : `scripts/sync-profile-skills.sh` à la racine du workspace fait la passe complète.

- `check` (mode par défaut) — compare récursivement chaque skill (`SKILL.md`, `references/`, `scripts/`, `templates/`), sortie 1 dès qu'un écart : rapporteur, aucune écriture, utilisable en contrôle.
- `sync` — copie le workspace vers le profil pour ce qui a dérivé, puis revérifie ; sortie 1 seulement si une copie a échoué. Inactif quand le lien partagé `vault` est intact : rien n'est copié, une copie locale réelle est seulement signalée `COPIE-LOCALE`.
- Le dossier du profil est détecté (`~/.hermes/profiles/compagnon/skills`, puis `/opt/data/profiles/compagnon/skills`) ; le forcer par `SKILLS_DST` ou par un second argument pour travailler sur une copie jetable.
- Ce qui n'existe que dans le profil est signalé (`RESIDU`, `PROFIL-SEULE`), jamais supprimé ni compté comme une dérive.

Résoudre les chemins réels au lieu de les supposer : racine du workspace par `git rev-parse --show-toplevel`, dossier du profil par détection. Les chemins donnés plus bas sont ceux de l'installation d'origine et varient selon l'environnement.

## Détecter un écart

```bash
./scripts/sync-profile-skills.sh check   # depuis la racine de /workspace/brain
```

Avec les symlinks en place, `check` compare au travers des liens : profil à jour signifie liens intacts. Un lien cassé ou un dossier revenu à l'état de copie réelle est un écart à signaler.

Même empreinte, rien à faire. Empreintes différentes, la copie du profil est à resynchroniser.

Pour comprendre ce qui a bougé avant d'écraser :

```bash
diff /workspace/brain/.agents/skills/<nom>/SKILL.md \
     /home/hermes/.hermes/profiles/compagnon/skills/<nom>/SKILL.md
```

## Resynchroniser

Seulement quand le lien partagé `vault` est absent ou cassé. Lien intact : réparer ou retirer la copie locale au lieu de la resynchroniser.

```bash
cp /workspace/brain/.agents/skills/<nom>/SKILL.md \
   /home/hermes/.hermes/profiles/compagnon/skills/<nom>/SKILL.md
```

Puis vérifier que les deux empreintes sont égales, et dire à l'utilisateur ce que la resynchronisation change dans le comportement, c'est-à-dire les règles nouvelles qu'il va voir appliquées.

Quand un écart est découvert en cours de tâche, corriger aussi l'ouverture déjà sautée : une revue ou un tri dont l'étape d'ouverture manquait se reprend, pas se rattrape approximativement au point où on s'est arrêté dans la version périmée.

## Sources de vérité, dans l'ordre

1. `/workspace/brain/.agents/skills/<nom>/SKILL.md` — la référence.
2. `/workspace/brain/Second-Cerveau/06_OUTILS/Process/<domaine>/process_<nom>.md` — la fiche process associée ; si les deux divergent, la skill prime pour l'exécution et la fiche se corrige.
3. La copie du profil — un dérivé remplaçable par un `cp`.

Les copies des autres worktrees (`/workspace/brain/wt/*/.agents/skills/`) sont des instantanés anciens, jamais des références.

## Copies divergentes dans les autres profils

Un dossier réel (non lien) dont le nom existe dans `.agents/skills` est une copie qui divergera : la remplacer par un lien, pas la resynchroniser par `cp`.

1. Inventorier : pour chaque profil et pour le profil `default` (`/opt/data/skills`), lister les dossiers réels homonymes d'une skill du vault, hachés par `md5sum` face à la source.
2. Avant de remplacer, asserter que le dossier ne contient que `SKILL.md` et que son empreinte est la copie ancienne connue (identique d'un profil à l'autre) : rien d'annexe ni d'unique à perdre. Sinon, regarder le `diff` d'abord.
3. Archiver l'ancienne copie en `.tar.gz` dans le scratch, `rmtree`, puis `os.symlink(source, chemin)` ; revérifier que l'empreinte lue à travers le lien égale celle de la source.
4. Un seul lien pour tout le dossier : `<dossier partagé>/vault -> /workspace/brain/.agents/skills` (le chargeur suit les liens : `os.walk(followlinks=True)`). Ne pas créer un lien par skill. Puis retirer des profils (dont la config liste le dossier partagé dans `skills.external_dirs`) leurs liens individuels redondants. Un doublon local + externe est masqué proprement (priorité : local avant dossiers externes), donc l'ordre des étapes ne casse rien.
5. Limiter ce que voit chaque profil avec `skills.disabled` dans sa `config.yaml` (liste de noms de skills). Règle de départ : un profil garde les skills du vault qu'il avait avant, les autres sont masquées. Sauvegarder la config avant de la modifier, valider le YAML (`ruamel.yaml`, le venv Hermes n'a pas `yaml`), puis relire la liste par `agent.skill_utils.get_disabled_skill_names` avec `HERMES_HOME` du profil.
6. Contrôle continu : le contrôle `check_skills_drift` de Vigie signale copies locales et liens cassés par profil.

## Règles

- Détecter les liens cassés avec `find <skills> -maxdepth 2 -xtype l`, pas avec `os.walk` : un lien pendant y est classé comme fichier et n'apparaît pas dans `dirs`. Un lien dont la cible n'existe pas dans le conteneur courant (autre point de montage du vault) rend la skill invisible sans aucune erreur ; pointer vers le chemin qui résout réellement (`readlink -f`).
- Toute correction de contenu se fait d'abord dans la source du workspace, puis se propage par `cp`. Une correction écrite seulement dans la copie du profil disparaît à la resynchronisation suivante ; si écrire dans la source n'est pas possible dans la session, le dire à l'utilisateur au lieu de laisser croire que c'est réglé.
- Comparer les empreintes au début d'une tâche gouvernée par une skill du crew, pas à la fin : une fois les questions posées et les notes écrites, la resynchronisation n'efface pas ce qui a déjà été produit de travers.
- Une skill que le runtime dit manquante alors que son entrée existe dans le dossier du profil est un symlink à cible morte, pas une skill absente : la racine du workspace a bougé. Diagnostiquer par test d'existence du lien, repointer sur la racine courante, relancer `check`, et seulement ensuite reprendre la tâche : lire le `SKILL.md` à la main depuis la source sort la session du contrôle du sync et fait patcher une copie que personne ne resynchronise.
- Avec le lien partagé intact, le script ne recopie plus rien : une skill absente du dossier du profil est servie par le lien, et une copie locale réelle est signalée `COPIE-LOCALE` (à retirer, jamais à resynchroniser par `cp`, ce qui recréerait la duplication). Le mode `sync` n'a plus d'effet sur elles.
- Une skill propre à un profil et dupliquée dans un autre profil (sans source dans le vault) diverge de la même façon : la déplacer dans le dépôt partagé (`skills/` du dépôt `agent-skills`) plutôt que la copier.
- Le contrôle de dérive de Vigie et le script ne regardent que le premier niveau de `<profil>/skills/` : une copie rangée dans une catégorie locale (`<profil>/skills/<catégorie>/<skill>`) y échappe et masque la skill partagée du même nom. L'inventorier à la main avec `find <profil>/skills -mindepth 2 -maxdepth 3 -name SKILL.md` avant de déclarer le profil propre.
- Ne jamais supprimer une skill du profil pour « nettoyer » : sans elle, la classe de tâche perd son mode d'emploi. Une copie locale d'une skill qui a un équivalent partagé se remplace par ce partage, elle ne se supprime pas à l'aveugle.
- Contrôler tout le dossier de la skill (`references/`, `scripts/`, `templates/`), pas seulement son `SKILL.md` : la comparaison récursive est le seul moyen de voir une référence ou un script resté en arrière.
- Classifier avant de corriger : un fichier présent seulement dans la copie du profil est un résidu, pas un écart. Le signaler et le laisser en place ; le compter comme une dérive rend le `check` bruyant et pousse à supprimer du travail propre au profil.
- Un fichier de la source absent du profil est un cas à part de l'écart : le signaler distinctement (« manque au profil »), car un simple `cp` du fichier suffit là où une dérive de contenu demande qu'on regarde le `diff` avant d'écraser.
- Vérifier après la copie, pas avant : recompter les écarts une fois le `sync` passé, car le compte d'avant ne dit rien de ce qui a échoué en route.
- Tester un script de synchronisation sur une copie jetable de l'arborescence avant de le lancer sur le profil vivant : la copie écrase sans confirmation, et un bug de boucle ne se voit qu'en exécution.
- Sous `set -euo pipefail`, un `grep` ou `grep -v` qui ne conserve aucune ligne sort en code 1 et tue la boucle avant l'action correctrice : terminer ces pipelines par `|| true`.

## Quand déléguer

- Modifier le fond d'une skill du crew : passer par la skill de gestion des skills du profil, ou demander à l'utilisateur.
- Douter qu'une skill soit la bonne pour la demande : lister les skills et vérifier les déclencheurs avant d'agir.
