"""Modèle de handler « avis de boot » — copier dans $HERMES_HOME/hooks/<nom>/handler.py

Rappel : la cible ne doit JAMAIS être le nom de plateforme nu quand le canal principal a un
`thread_id` — `hermes send` ne retient que le chat et livrerait hors topic. La cible est donc
résolue ici par la config du gateway, comme le fait l'avis d'arrêt natif.

À poser à côté de ce HOOK.yaml (dans le même dossier, sous le nom HOOK.yaml) :

    name: <nom-du-hook>
    description: <une ligne>
    events:
      - gateway:startup

Le handler s'exécute sur la boucle d'événements du gateway : rester async, ne jamais bloquer
avec subprocess.run, borner l'attente. Rien ici ne doit pouvoir faire échouer un boot.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# Canal principal à prévenir (la cible est dérivée de la config du gateway).
PLATFORM = "telegram"
MESSAGE = "..."

# Anti-doublon (respawn rapide) et borne dure de l'envoi.
DEDUP_SECONDS = 20.0
SEND_TIMEOUT_SECONDS = 20.0

_HERE = Path(__file__).resolve().parent
_STAMP = _HERE / ".last_notice"
_LOG = _HERE / "notify.log"


def _log(line: str) -> None:
    try:
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception:
        pass


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or _HERE.parents[1])


def _hermes_bin() -> str:
    """Lanceur voisin de l'interpréteur courant ; `hermes` n'est pas toujours dans le PATH."""
    candidate = Path(sys.executable).parent / "hermes"
    return str(candidate) if candidate.exists() else "hermes"


def _recently_sent() -> bool:
    try:
        return (time.time() - float(_STAMP.read_text(encoding="utf-8").strip())) < DEDUP_SECONDS
    except Exception:
        return False


def _stamp() -> None:
    try:
        _STAMP.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass


def _builtin_notice_pending() -> bool:
    """Vrai quand l'avis natif couvre déjà ce boot : ne pas parler deux fois.

    Les marqueurs sont encore sur disque au moment où `gateway:startup` est émis (l'avis natif
    part une étape plus tard), donc ce test est exact et non heuristique.
    """
    home = _hermes_home()
    return (home / ".restart_notify.json").exists() or (home / ".restart_pending.json").exists()


def _home_target() -> str:
    """`<plateforme>[:<chat>[:<thread>]]` pour le canal principal configuré.

    API du gateway d'abord (même résolution que le reste du process, donc mêmes surcharges),
    puis variables d'environnement, puis nom de plateforme nu en dernier recours.
    """
    chat = thread = ""
    try:
        from gateway.config import Platform, load_gateway_config
        home = load_gateway_config().get_home_channel(Platform(PLATFORM))
        if home:
            chat = str(getattr(home, "chat_id", "") or "").strip()
            thread = str(getattr(home, "thread_id", "") or "").strip()
    except Exception as exc:
        _log(f"home-channel resolve failed ({exc!r}); falling back to env")
    prefix = PLATFORM.upper()
    chat = chat or (os.environ.get(f"{prefix}_HOME_CHANNEL") or "").strip()
    thread = thread or (os.environ.get(f"{prefix}_HOME_CHANNEL_THREAD_ID") or "").strip()
    if not chat:
        return PLATFORM
    return f"{PLATFORM}:{chat}" + (f":{thread}" if thread else "")


async def _send() -> None:
    if _recently_sent():
        _log("skipped: notice already sent within the dedup window")
        return
    if _builtin_notice_pending():
        _log("skipped: the stock restart/online notice covers this boot")
        return

    env = dict(os.environ)
    env.setdefault("HERMES_HOME", str(_hermes_home()))
    target = _home_target()

    try:
        proc = await asyncio.create_subprocess_exec(
            _hermes_bin(), "send", "--to", target, "--quiet", MESSAGE,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:  # lanceur absent, exec en échec...
        _log(f"spawn failed: {exc!r}")
        return

    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=SEND_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        _log(f"send timed out after {SEND_TIMEOUT_SECONDS:.0f}s")
        try:
            proc.kill()
        except Exception:
            pass
        return

    if proc.returncode == 0:
        _stamp()
        _log(f"sent to {target}")
    else:
        detail = (err or b"").decode("utf-8", "replace").strip()[:300]
        _log(f"send failed rc={proc.returncode} target={target} err={detail}")


async def handle(event_type: str, context: dict) -> None:
    """Un tir par boot. Ne lève jamais."""
    if event_type != "gateway:startup":
        return
    try:
        await _send()
    except Exception as exc:
        _log(f"handler error: {exc!r}")
