#!/usr/bin/env python3
"""Probe a Hermes gateway event hook WITHOUT restarting the gateway.

Runs the same discovery path the gateway uses (`HookRegistry.discover_and_load`) over
`$HERMES_HOME/hooks/` and reports what is loaded and which handlers the event resolves to.
With `--fire <event>` it also emits the event, which runs the handler for real — use that
only for events whose side effect you actually want (a startup notice hook WILL send a
message to the configured home channel).

Run it with the gateway's own interpreter so the handler sees the same environment:

    HERMES_HOME=/path/to/.hermes /opt/hermes/.venv/bin/python probe_gateway_hook.py
    HERMES_HOME=/path/to/.hermes /opt/hermes/.venv/bin/python probe_gateway_hook.py --fire gateway:startup

Exit codes: 0 = probe completed, 2 = environment/usage problem (install root or HERMES_HOME
not found). A handler that raises is logged by the registry and does not fail the probe.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _find_install_root(explicit: str | None) -> Path | None:
    """Locate the Hermes install root (the dir holding `gateway/hooks.py`)."""
    candidates = []
    if explicit:
        candidates.append(explicit)
    env_root = os.environ.get("HERMES_INSTALL_ROOT")
    if env_root:
        candidates.append(env_root)
    candidates.append("/opt/hermes")
    # Last resort: walk up from the running interpreter looking for the package tree.
    exe = Path(sys.executable).resolve()
    candidates.extend(str(p) for p in exe.parents)
    for cand in candidates:
        if cand and (Path(cand) / "gateway" / "hooks.py").is_file():
            return Path(cand)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--install-root", help="Hermes install root (default: auto-detect, e.g. /opt/hermes)")
    ap.add_argument("--hermes-home", help="profile home holding hooks/ (default: $HERMES_HOME)")
    ap.add_argument("--fire", metavar="EVENT", help="also emit this event and run its handlers for real")
    ap.add_argument("--context", default="{}", help="JSON context passed to --fire (default: {})")
    ap.add_argument("--no-fire", action="store_true", help="with --fire, only list resolved handlers")
    args = ap.parse_args()

    root = _find_install_root(args.install_root)
    if root is None:
        print("ERROR: could not locate the Hermes install root; pass --install-root", file=sys.stderr)
        return 2

    if args.hermes_home:
        os.environ["HERMES_HOME"] = args.hermes_home
    home = os.environ.get("HERMES_HOME")
    if not home:
        print("ERROR: HERMES_HOME is not set; pass --hermes-home", file=sys.stderr)
        return 2

    sys.path.insert(0, str(root))
    from gateway.hooks import HookRegistry, _resolve_hooks_dir  # noqa: E402

    hooks_dir = _resolve_hooks_dir()
    print(f"install_root : {root}")
    print(f"HERMES_HOME  : {home}")
    print(f"hooks_dir    : {hooks_dir} (exists={hooks_dir.exists()})")

    registry = HookRegistry()
    registry.discover_and_load()
    loaded = registry.loaded_hooks
    print(f"loaded_hooks : {len(loaded)}")
    for hook in loaded:
        print(f"  - {hook['name']}: {hook['events']}  [{hook['path']}]")

    if not args.fire:
        return 0

    handlers = registry._resolve_handlers(args.fire)
    print(f"handlers for {args.fire!r}: {len(handlers)}")
    if args.no_fire or not handlers:
        return 0

    try:
        context = json.loads(args.context)
    except json.JSONDecodeError as exc:
        print(f"ERROR: --context is not valid JSON: {exc}", file=sys.stderr)
        return 2

    asyncio.run(registry.emit(args.fire, context))
    print("emit returned (handler exceptions are logged above, not raised)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
