---
name: native-lib-load-recovery
description: "Use when a prebuilt .so or native addon fails to load."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  opencode/autoinvoke: false
  hermes:
    tags: [native-library, dlopen, elf, ld-library-path, container, troubleshooting]
---

# Réparer une bibliothèque native qui refuse de se charger

## When to Use

Un binaire préconstruit (`.so`, addon Node) échoue au chargement avec `cannot open shared object file`, `invalid ELF header`, ou avec un message dont le nom de fichier est dupliqué (`<lib>.so.so`) ; ou un backend natif d'un outil remonte `NoBinaryFoundError` alors que le fichier est bien présent.

Cette skill répare le **chargement**. Pour un wrapper de script cron qui pointe vers un binaire absent (exit 127), voir `cron-script-recovery`.

## Piège de lecture, avant tout

**Ne pas croire le nom de fichier affiché dans l'erreur.** Un chemin terminé par `.so.so` n'est pas un fichier à retrouver : le chargeur a d'abord tenté le chemin réel, échoué, puis retenté en ajoutant le suffixe plateforme. Le fichier réel existe presque toujours — partir chasser un fichier manquant fait perdre le vrai diagnostic (des dépendances internes cassées).

## Diagnostic, dans l'ordre

```bash
ls -la "<chemin réel>"                    # 1. le fichier existe-t-il ?
ldd "<chemin réel>"                       # 2. quelle dépendance casse, et pourquoi
readelf -d "<chemin réel>" | grep -i needed   # 3. confirmer les DT_NEEDED
head -c 60 "<dépendance suspecte>"         # 4. ELF ou script de liaison ?
```

Signature de la cause typique : le binaire déclare `DT_NEEDED: libc.so` (au lieu de `libc.so.6`) parce qu'il a été lié avec un sysroot particulier, et l'image fournit `/lib/x86_64-linux-gnu/libc.so` comme **script GNU ld** (`/* GNU ld script ...`), que `dlopen` ne sait pas charger. `ldd` affiche alors `error while loading shared libraries: /lib/x86_64-linux-gnu/libc.so: invalid ELF header`.

## Correctif : shim de nom, sans root et réversible

Créer un répertoire contenant le **nom demandé** pointant vers le vrai objet, puis préfixer ce répertoire dans `LD_LIBRARY_PATH` pour les invocations concernées :

```bash
mkdir -p <shimdir>
ln -sf /lib/x86_64-linux-gnu/libc.so.6 <shimdir>/libc.so
LD_LIBRARY_PATH=<shimdir> <commande>
```

Le shim doit vivre dans un répertoire **persistant** rattaché à l'outil concerné (à côté de son installation), jamais dans un dossier temporaire. Fixer la variable au lancement : wrapper dédié, `.env`, ou préfixe de commande documenté.

## Vérification

Charger réellement, puis relancer la commande qui échouait et lire sa sortie :

```bash
python3 -c "import ctypes; ctypes.CDLL('<chemin réel>'); print('dlopen OK')"
# ou le probe fourni : scripts/dlopen_probe.py <chemin réel>
```

Un code de sortie 0 ne prouve rien si le message d'erreur figure encore dans la sortie. Un fichier présent ne prouve pas qu'il se charge.

## Pitfalls

- **`ldd` d'abord.** Il donne en une ligne la dépendance qui casse ; lire les NEEDED un par un fait perdre du temps.
- **Un script GNU ld n'est pas un ELF.** Le correctif est un shim de nom, pas une réinstallation du paquet fautif : réinstaller redonne exactement le même binaire lié de la même façon.
- **Une cause, plusieurs victimes.** Tous les binaires sortis du même build portent le même `DT_NEEDED` : un shim unique répare d'un coup plusieurs backends (stockage vectoriel, moteur d'inférence) qui semblaient deux pannes distinctes.
- **Un backend peut échouer bruyamment avant de se replier.** Un moteur qui sonde le GPU puis retombe sur CPU noie la vraie erreur sous des avertissements ; quand l'outil expose un drapeau (ex. `QMD_FORCE_CPU=1`), le poser explicitement rend le mode voulu clair et supprime le bruit.
- **Un préconstruit par plateforme peut vivre dans un paquet séparé.** Un fichier `<pkg>/bins/_<plateforme>.moved.txt` annonce que le binaire a été déplacé : vérifier la présence du paquet plateforme avant de conclure à un binaire manquant.

## Cas connu

Dans le conteneur agent, `qmd` : shim `/workspace/.qmd/libshim/libc.so` et lancement avec `LD_LIBRARY_PATH=/workspace/.qmd/libshim` et `QMD_FORCE_CPU=1`. Vérifier avec `qmd doctor` (attendre la ligne `✓ sqlite-vec` et un mode device résolu).
