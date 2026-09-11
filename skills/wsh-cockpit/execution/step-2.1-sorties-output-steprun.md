# Step 2.1 — `cmd_output`, `step-run`, accusés de réception

Phase 2 · après 1.1 · fiche à plus fort rendement · **Modèle : Sonnet**

## Objectif

Supprimer le chatter renvoyé à l'agent par `output`, `wait-done --print`,
`step-run`, `banner` et `keys` — sans rien changer à ce que voit l'utilisateur
dans le pane.

## Contexte minimal

⚠️ **Les numéros de ligne ci-dessous datent d'avant la PR #15 et ont bougé de
quelques lignes. Localise par contenu, pas par numéro.**

Audit mesuré (lignes renvoyées à l'agent par appel) :

1. **`cmd_output`** (`wsh-live.sh`, fonction `cmd_output`) découpe du `┌─[#N]` au
   `└─[#N] exit N` **inclus**. Chaque résultat transporte donc : le header
   `┌─[#N] <heure>`, la ligne `│$ <commande>` (ré-écho de ce que l'agent vient
   d'écrire), **une règle de 80 à 100 caractères `─`** (~25 tokens à elle seule),
   2 lignes blanches, et le footer. Soit ~6 lignes parasites par appel, payées à
   chaque tour.
2. **`step_run`** réinvoque `$0 banner`, `$0 send` et `$0 wait-done --print` sans
   museler les deux premiers → 3 lignes d'accusé de réception en plus du framing.
3. **Accusés de réception sans information** : la ligne « waiting for send #[N]…
   (timeout Ns)… » de `wait-done` (imprimée **avant** le blocage, donc sans valeur
   pour l'agent), l'`echo "banner <type> -> <sess>"` du bras `banner`, et
   l'`echo "keys -> <sess>: <K>"` du bras `keys` (jamais gaté TTY, contrairement à
   `send`).

Outil déjà présent à réutiliser : `tty_only()` dans `scripts/lib/session.sh`
(`{ [ -t 1 ] && printf '%s\n' "$@" || true; }`) — utilisé à seulement 2 endroits
aujourd'hui.

Décisions actées à respecter (cf. CONVENTIONS.md) : le rendu dans le pane reste
intact ; si le footer `exit` quitte la sortie agent, le code de sortie doit rester
disponible via la ligne `done: #[N] exit N` de `wait-done` et via le rc du script.

## Tâches

- [ ] RED d'abord : dans `selftest-output`, ajouter une assertion sur la **forme**
      de la sortie (pas de ligne de règle `^─+$`, pas de ligne `│$`, pas de blanc
      en tête) qui échoue aujourd'hui.
- [ ] Filtrer le segment imprimé par `cmd_output` : retirer header, `│$ cmd`,
      règles et lignes blanches d'encadrement. Conserver le contenu réel et le code
      de sortie. `--full` continue de tout montrer pour le debug.
- [ ] Museler les sous-appels internes de `step_run` (`banner` et `send` en
      `>/dev/null`) — l'agent connaît déjà l'id, le label et la commande qu'il
      vient de passer.
- [ ] Passer en `tty_only` : la ligne « waiting… » de `wait-done`, l'accusé du
      bras `banner`, l'accusé du bras `keys`.
- [ ] Vérifier qu'aucun selftest n'assertait sur les lignes supprimées — il y a
      ~51 références à `output` dans `selftests.sh`. Adapter les assertions qui
      tombent, **sans affaiblir** ce qu'elles vérifiaient.
- [ ] Mesurer : lignes renvoyées par un `step-run` d'une étape, et par un
      `output`, avant/après. Reporter dans le tableau « Mesures » de STATE.md.

## Critère done

Un `step-run` d'une étape renvoie à l'agent le contenu de la commande + son code
de sortie, et **au plus 1 ligne** d'enrobage. `selftest-output`, `selftest-sep`,
`selftest-live`, `selftest-guard`, `selftest-docs` verts. Le pane, lui, affiche
exactement le même rendu qu'avant (vérifié à l'œil dans un cockpit visible).

## Fin de session

Mettre à jour `STATE.md` (statut 2.1, `NEXT: step-2.2`, mesures) → commit signé →
push → annoncer `/exit`.
