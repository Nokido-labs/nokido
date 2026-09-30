#!/usr/bin/env python3
"""forge_netcfg_docset_normalize.py — normalise les references normatives des
docsets vendor de netcfg-agent (docs/vendor_knowledge/<vendor>/NN_sujet.md).

Constat mesure 2026-07-31 sur les 50 fiches (5 constructeurs x 10 sujets) :
  - references heterogenes d'un constructeur a l'autre pour le MEME sujet
    (802.1ax / 802.1AX-2008 / 802.3ad ; SNMP tantot RFC 3411-3418, tantot la
    seule RFC 1213) ;
  - une reference OBSOLETE : la RFC 2460 (IPv6), remplacee par la RFC 8200 ;
  - 21 fiches sans aucune ligne de norme, sous des intitules differents
    (**Standards**, **Norme**, **Architecture**).

Ce module AJOUTE une ligne `- **References normatives**` homogene par sujet et
corrige les renvois obsoletes. Il ne SUPPRIME aucune ligne existante : une
mention vendor-specifique (ex. « IEEE 802.1ak (MVRP) supporte par Comware »)
est une information vraie qu'une normalisation ne doit pas ecraser.

Chaque norme citee ici a ete verifiee dans le miroir RFC local et son statut lu
dans rfc-index.txt (aucune obsolete). Les normes IEEE sont annoncees comme
telles : 802.1Q/802.1D/802.1AX ne sont PAS des RFC, confusion frequente.

Idempotent : relancer ne change rien. Dry-run par defaut, --apply pour ecrire.
L'ecriture exige le compte LaForgeTrusted (le sandbox est bloque par
WORKSPACE_GUARD hors de sa zone) :

    run action=trusted_script path=tools/forge_netcfg_docset_normalize.py
        script_args="--apply"

Apres coup, re-ingerer via tools/forge_vendor_kb_ingest.py, sinon le RAG
continue de servir l'ancienne version des fiches.
"""
from __future__ import annotations

__FORGE_COLOR__ = "digestif/normalisation-docset-vendor"

import argparse
import json
import os
import re
import sys
from pathlib import Path

MARQUEUR = "- **Références normatives**"
SECTION = "## Références vendor"

# Sujet (suffixe du nom de fichier) -> reference normative homogene.
NORMES: dict[str, str] = {
    "01_vlan_basic": (
        "IEEE 802.1Q (Bridges and Bridged Networks) — segmentation VLAN. "
        "Norme IEEE, pas une RFC."
    ),
    "02_vlan_trunk": (
        "IEEE 802.1Q — marquage (tagging) VLAN sur lien trunk et VLAN natif (PVID)."
    ),
    "03_interface_access": (
        "IEEE 802.1Q (PVID du port d'accès) ; IEEE 802.1X pour l'authentification du port."
    ),
    # Ne PAS citer de numéro obsolète dans la ligne insérée : la règle OBSOLETES
    # ci-dessous s'appliquerait à notre propre texte au passage suivant et
    # écrirait « remplace la RFC 8200, obsolète » (mesuré 2026-07-31 : 5 fiches
    # re-modifiées à chaque relance, donc passe NON idempotente).
    "04_interface_routed": (
        "RFC 791 (IPv4), RFC 1812 (prérequis des routeurs IPv4), RFC 8200 (IPv6)."
    ),
    "05_stp_config": (
        "IEEE 802.1D (STP), 802.1w (RSTP) et 802.1s (MSTP), "
        "aujourd'hui intégrés à IEEE 802.1Q."
    ),
    "06_acl_basic": (
        "Aucune norme ne définit la syntaxe des ACL (elle est propre au constructeur). "
        "Filtrage anti-usurpation : RFC 2827 (BCP 38) et RFC 3704 (réseaux multi-attachés)."
    ),
    "07_qos": (
        "RFC 2474 (champ DS / DSCP), RFC 2475 (architecture DiffServ), "
        "RFC 4594 (classes de service). Marquage de couche 2 : IEEE 802.1p, intégré à 802.1Q."
    ),
    "08_snmp": (
        "RFC 3411 à 3418 (cadre SNMPv3 : architecture, USM, VACM, MIB) ; RFC 1213 (MIB-II)."
    ),
    "09_aaa_ssh": (
        "RFC 4251 à 4254 (SSH v2) ; RFC 2865 et 2866 (RADIUS) ; RFC 8907 (TACACS+)."
    ),
    "10_link_agg": (
        "IEEE 802.1AX (agrégation de liens et LACP, anciennement IEEE 802.3ad)."
    ),
}

# Renvois obsoletes -> remplacant, statut lu dans rfc-index.txt.
OBSOLETES: list[tuple[str, str]] = [
    (r"RFC\s*2460", "RFC 8200"),
]


def _vendor_knowledge_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    # LaForge/ et netcfg-agent/ sont freres sous la racine du superrepo.
    repo = Path(__file__).resolve().parent.parent
    return repo.parent / "netcfg-agent" / "docs" / "vendor_knowledge"


def _sujet(nom_fichier: str) -> str | None:
    base = nom_fichier[:-3] if nom_fichier.endswith(".md") else nom_fichier
    return base if base in NORMES else None


def normalise_texte(texte: str, sujet: str) -> tuple[str, list[str]]:
    """Rend (texte_corrige, liste des changements). Ne supprime aucune ligne."""
    changements: list[str] = []

    # Les renvois obsolètes sont corrigés dans le texte VENDOR uniquement : la
    # ligne que ce module gère est réécrite plus bas, l'inclure ici ferait
    # dépendre le résultat du nombre de passages.
    lignes_src = texte.splitlines()
    for motif, remplacant in OBSOLETES:
        touche = False
        for i, ligne_src in enumerate(lignes_src):
            if ligne_src.strip().startswith(MARQUEUR):
                continue
            if re.search(motif, ligne_src):
                lignes_src[i] = re.sub(motif, remplacant, ligne_src)
                touche = True
        if touche:
            changements.append(f"obsolete {motif} -> {remplacant}")
    texte = "\n".join(lignes_src) + ("\n" if texte.endswith("\n") else "")

    ligne = f"{MARQUEUR} : {NORMES[sujet]}"
    lignes = list(lignes_src)

    # Reperer le bloc « Références vendor » (fin = separateur ou fin de fichier).
    try:
        debut = next(i for i, l in enumerate(lignes) if l.strip().startswith(SECTION))
    except StopIteration:
        return texte, changements  # pas de section : on n'invente pas de structure

    fin = len(lignes)
    for i in range(debut + 1, len(lignes)):
        if lignes[i].strip().startswith("---"):
            fin = i
            break

    existante = next(
        (i for i in range(debut, fin) if lignes[i].strip().startswith(MARQUEUR)), None
    )
    if existante is not None:
        if lignes[existante].strip() != ligne:
            lignes[existante] = ligne
            changements.append("référence normative mise à jour")
    else:
        derniere_puce = max(
            (i for i in range(debut, fin) if lignes[i].strip().startswith("- ")),
            default=debut,
        )
        lignes.insert(derniere_puce + 1, ligne)
        changements.append("référence normative ajoutée")

    return "\n".join(lignes) + ("\n" if texte.endswith("\n") else ""), changements


def run(racine: Path, apply: bool) -> dict:
    if not racine.is_dir():
        # Distinguer « rien trouve » de « je n'ai pas pu regarder ».
        return {"erreur": f"répertoire illisible ou absent : {racine}", "fiches": 0}

    rapport: dict = {"racine": str(racine), "apply": apply, "fiches": 0,
                     "modifiees": 0, "inchangees": 0, "ignorees": [], "detail": {}}

    for vendor in sorted(p for p in racine.iterdir() if p.is_dir()):
        for fiche in sorted(vendor.glob("*.md")):
            sujet = _sujet(fiche.name)
            if sujet is None:
                rapport["ignorees"].append(f"{vendor.name}/{fiche.name} (sujet inconnu)")
                continue
            rapport["fiches"] += 1
            texte = fiche.read_text(encoding="utf-8")
            corrige, changements = normalise_texte(texte, sujet)
            cle = f"{vendor.name}/{fiche.name}"
            if not changements:
                rapport["inchangees"] += 1
                continue
            rapport["modifiees"] += 1
            rapport["detail"][cle] = changements
            if apply:
                fiche.write_text(corrige, encoding="utf-8")

    return rapport


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None, help="Chemin de docs/vendor_knowledge.")
    ap.add_argument("--apply", action="store_true",
                    help="Écrit les fiches (défaut : dry-run, aucune écriture).")
    args = ap.parse_args(argv)

    rapport = run(_vendor_knowledge_dir(args.root), apply=args.apply)
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 1 if rapport.get("erreur") else 0


if __name__ == "__main__":
    sys.exit(main())
