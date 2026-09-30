#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pose une valeur de CONFIGURATION au coffre — jamais un secret.

`get_secret` lit dans l'ordre : cache, coffre, WCM, `.env`, environnement. Le
coffre PRIME donc sur le fichier : c'est le moyen propre de corriger une valeur
de config sans editer un `.env` que le garde de secrets protege (a juste titre —
le fichier contient d'autres cles).

POURQUOI UN REFUS EXPLICITE DES SECRETS : une valeur passee en argument de ligne
de commande se lit dans la table des processus. Poser un jeton ainsi le
divulguerait a tout compte capable de lister les process. Les secrets ont leur
chemin a eux (`forge_migrate_env_secret`, qui lit le `.env` sans jamais afficher
la valeur). Ici on ne veut que des noms de modeles, des URLs, des drapeaux.

Usage :
    run action=trusted_script path=tools/forge_vault_set_config.py
        script_args="GEMINI_MODEL gemini-pro-latest"
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Motifs de jetons connus + heuristique de longueur : on prefere refuser une
# config inhabituelle plutot que laisser passer un secret dans une cmdline.
_MOTIFS_SECRET = (
    r"^gh[pousr]_[A-Za-z0-9_]{20,}",
    r"^github_pat_[A-Za-z0-9_]{20,}",
    r"^sk-[A-Za-z0-9_\-]{20,}",
    r"^AIza[0-9A-Za-z_\-]{30,}",
    r"^xai-[A-Za-z0-9]{20,}",
    r"^gsk_[A-Za-z0-9]{20,}",
    r"^[A-Fa-f0-9]{40,}$",
)
_NOMS_SENSIBLES = ("token", "key", "secret", "password", "passwd", "credential")
_LONGUEUR_SUSPECTE = 40


def ressemble_a_un_secret(cle: str, valeur: str) -> str:
    """Motif de refus, ou chaine vide si la valeur est une config acceptable."""
    for motif in _MOTIFS_SECRET:
        if re.match(motif, valeur):
            return f"la valeur a la forme d'un jeton ({motif})"
    bas = cle.lower()
    if any(mot in bas for mot in _NOMS_SENSIBLES) and not bas.endswith(("_model", "_url", "_mode")):
        return f"le nom '{cle}' designe un secret"
    if len(valeur) >= _LONGUEUR_SUSPECTE and " " not in valeur:
        return f"valeur de {len(valeur)} caracteres sans espace — trop proche d'un jeton"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Poser une config au coffre")
    ap.add_argument("cle")
    ap.add_argument("valeur")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    refus = ressemble_a_un_secret(a.cle, a.valeur)
    if refus:
        print(f"REFUS: {refus}. Un secret ne passe pas par une ligne de commande — "
              f"utiliser tools/forge_migrate_env_secret.py")
        return 3

    from nokido_agent.app.forge_machine_vault import vault_get, vault_set

    avant = vault_get(a.cle)
    if avant == a.valeur:
        print(f"[coffre] '{a.cle}' vaut deja '{a.valeur}' — rien a faire")
        return 0
    if a.dry_run:
        print(f"[dry-run] '{a.cle}' : {avant!r} -> {a.valeur!r}")
        return 0

    vault_set(a.cle, a.valeur)
    relu = vault_get(a.cle)
    if relu != a.valeur:
        print(f"CRITIQUE: relecture rend {relu!r}, pas {a.valeur!r}")
        return 4
    print(f"[coffre] '{a.cle}' : {avant!r} -> {relu!r} (verifie par relecture ; "
          f"le coffre PRIME sur le .env, dont la ligne devient inerte)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
