#!/usr/bin/env python3
"""Probe déterministe : le fichier se charge-t-il réellement via dlopen ?

Usage : python3 dlopen_probe.py <chemin.so> [<chemin.so> ...]
Sortie : une ligne par fichier, OK/ECHEC, code de sortie 1 si au moins un échec.
Lire la sortie : dlopen peut réussir alors qu'un symbole manque par ailleurs.
"""
import ctypes
import sys


def probe(path: str) -> bool:
    try:
        ctypes.CDLL(path)
    except OSError as exc:
        print(f"ECHEC {path} :: {exc}")
        return False
    print(f"OK    {path}")
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip())
        return 2
    return 0 if all(probe(p) for p in argv[1:]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
