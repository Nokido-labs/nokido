#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Range une cle du coffre sous un AUTRE nom, sans repasser par le clair.

Le cas qui a manque le 2026-08-18 : un jeton correct etait au coffre sous la
mauvaise etiquette. Les seuls chemins disponibles etaient de le recoller dans
le `.env` (le remettre en clair pour le ranger — absurde) ou d'editer le store
chiffre a la main. D'ou ce geste, qui ne fait que lire une cle et l'ecrire sous
une autre.

GARDES :
  * la source doit exister, sinon on ecrirait du vide sur une cle valide ;
  * si la destination existe DEJA avec une valeur differente, refus — sauf
    `--ecraser`, qui exige alors `--motif`. Un `vault_set` est un ecrasement
    silencieux : c'est ainsi qu'un PAT a ete perdu, faute d'avoir confronte la
    cible avant d'ecrire ;
  * verification par relecture, et empreintes seules a l'affichage.

Usage :
    run action=trusted_script path=tools/forge_vault_copy_key.py
        script_args="GITHUB_TOKEN GITHUB_MODELS_TOKEN --ecraser --motif 'jeton revoque (401)'"
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/secret : range une cle du coffre sous un autre nom sans clair"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def empreinte(valeur: str) -> str:
    return hashlib.sha256(valeur.encode("utf-8")).hexdigest()[:12] if valeur else "(vide)"


def main() -> int:
    ap = argparse.ArgumentParser(description="Copier une cle du coffre sous un autre nom")
    ap.add_argument("source")
    ap.add_argument("destination")
    ap.add_argument("--ecraser", action="store_true",
                    help="autorise l'ecrasement d'une destination differente")
    ap.add_argument("--motif", default="", help="pourquoi l'ecrasement est sans risque")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    from nokido_agent.app.forge_machine_vault import vault_get, vault_set

    src = vault_get(a.source) or ""
    if not src:
        print(f"ABORT: '{a.source}' absente du coffre — rien a copier")
        return 3
    dst = vault_get(a.destination) or ""

    if dst and dst != src:
        if not a.ecraser:
            print(f"ABORT: '{a.destination}' existe deja avec une valeur DIFFERENTE "
                  f"({empreinte(dst)}) — relire, puis --ecraser --motif '<pourquoi>'")
            return 3
        if not a.motif:
            print("ABORT: --ecraser exige --motif (ce qui rend la perte acceptable)")
            return 3
    if dst == src:
        print(f"[coffre] '{a.destination}' porte deja cette valeur ({empreinte(src)}) — rien a faire")
        return 0

    if a.dry_run:
        print(f"[dry-run] '{a.source}' ({empreinte(src)}) -> '{a.destination}' "
              f"(actuellement {empreinte(dst)})")
        return 0

    if dst:
        print(f"[coffre] ecrasement de '{a.destination}' ({empreinte(dst)}) — motif : {a.motif}")
    vault_set(a.destination, src)
    relu = vault_get(a.destination) or ""
    if relu != src:
        print(f"CRITIQUE: relecture de '{a.destination}' ({empreinte(relu)}) != source")
        return 4
    print(f"[coffre] '{a.destination}' = '{a.source}' ({empreinte(src)}) — verifie par relecture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
