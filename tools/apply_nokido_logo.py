#!/usr/bin/env python3
"""Applique le pack logo Nokido biomimetique dans web_hub/static.

Le sandbox client ne peut pas ecraser les SVG owned-admin (PermissionError) ;
LaForgeTrusted le peut. Copie favicon/logotype/marques + retire le residu
laforge-mark.svg (mort, non reference). Lancer via run action=trusted_script.
"""
import pathlib
import shutil

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = next(REPO.glob("Logo Nokido*")) / "pack-nokido"
DST = REPO / "app" / "web_hub" / "static"


def main():
    copied = []
    for f in SRC.glob("*.svg"):
        shutil.copy2(f, DST / f.name)
        copied.append(f.name)
    print("copied:", copied)
    old = DST / "laforge-ds" / "assets" / "laforge-mark.svg"
    if old.exists():
        old.unlink()
        print("removed residu laforge-mark.svg")
    else:
        print("laforge-mark.svg absent")


if __name__ == "__main__":
    main()
