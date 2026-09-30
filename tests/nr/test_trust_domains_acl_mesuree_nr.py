"""NR — l'instrument M0.1 doit MESURER les permissions, pas les DECLARER.

Defaut paye le 2026-09-13 : `forge_trust_domains` rendait 25 « autorites partagees »
et 10 « chemins auto-modifiants » entierement codes en dur — zero `icacls`, zero
`Get-Acl`, zero `win32security`, zero `os.stat`. Consequence mesuree : l'owner a
retire `Tout le monde:(F)` de la base d'autorite, abaisse `CodexSandboxUsers` a
`(RX)` et purge deux SID etrangers du depot, et le verdict est reste **rigoureusement
identique** (8 RESOLVED / 10 OPEN / 1 BLOCKED). Un instrument qui ne peut pas bouger
ne peut ni confirmer ni infirmer : il n'est pas une preuve, c'est une opinion datee.

Ce NR verrouille trois proprietes, dans l'ordre ou elles ont manque :

1. la mesure EXISTE et lit la DACL reelle ;
2. elle a TROIS etats — un chemin illisible ne rend jamais « aucun ecrivain »
   (cf. `UNKNOWN != NO` : un capteur qui rend la meme valeur pour « pas la » et
   « acces refuse » fabrique des faux negatifs indetectables) ;
3. `verdict_m01()` porte la QUALITE de chaque autorite de forme `fichier`
   (`VERIFIE` / `INFIRME` / `ILLISIBLE`), jamais une affirmation nue.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# PAS d'importorskip : ce module fait partie du livrable. Un skip rendrait la CI
# verte sans que rien ne soit verifie (faux vert mesure le 2026-09-08).
import forge_trust_domains as ftd  # noqa: E402


def test_la_mesure_acl_existe():
    """Sans elle, tout le reste du chantier M0.1 est declaratif."""
    assert hasattr(ftd, "mesurer_acl"), (
        "forge_trust_domains n'expose aucune mesure de permissions : "
        "ses autorites partagees sont declarees, donc le verdict est fige"
    )


def test_la_mesure_lit_la_dacl_reelle(tmp_path):
    """Un fichier que le compte courant vient d'ecrire a forcement un ecrivain."""
    cible = tmp_path / "temoin.txt"
    cible.write_text("temoin", encoding="utf-8")

    vu = ftd.mesurer_acl(str(cible))

    assert vu["etat"] == "LU", f"DACL non lue sur un fichier qu'on vient d'ecrire : {vu}"
    assert vu["ecrivains"], (
        "aucun ecrivain sur un fichier cree par le compte courant — "
        "la mesure ne lit pas la DACL, elle rend une liste vide"
    )
    for e in vu["ecrivains"]:
        assert {"sid", "trustee", "droits", "herite"} <= set(e), f"entree incomplete : {e}"


def test_illisible_n_est_jamais_aucun_ecrivain(tmp_path):
    """LE point du NR : distinguer « rien trouve » de « je n'ai pas pu regarder »."""
    absent = tmp_path / "sous_dossier_inexistant" / "rien.txt"

    vu = ftd.mesurer_acl(str(absent))

    assert vu["etat"] == "ILLISIBLE", (
        f"un chemin illisible doit se DIRE illisible, pas rendre un etat sain : {vu}"
    )
    assert vu.get("motif"), "un etat ILLISIBLE sans motif ne s'instruit pas"
    assert vu.get("ecrivains") in (None, []), "un illisible ne prétend pas connaitre les ecrivains"
    assert vu["etat"] != "LU"


def test_le_verdict_porte_la_qualite_des_autorites_fichier():
    """Une autorite de forme `fichier` doit etre adossee a une mesure, ou se taire."""
    v = ftd.verdict_m01()
    fichiers = [a for a in v["autorites_partagees"] if a.get("forme") == "fichier"]
    assert fichiers, "aucune autorite de forme `fichier` — la carte a change, revoir ce NR"

    qualites = {"VERIFIE", "INFIRME", "ILLISIBLE"}
    sans_qualite = [a for a in fichiers if a.get("qualite") not in qualites]
    assert not sans_qualite, (
        f"{len(sans_qualite)} autorite(s) de forme `fichier` affirmees sans mesure : "
        f"{[a.get('valeur') for a in sans_qualite][:5]}"
    )


def test_la_mesure_ne_lit_pas_son_propre_vocabulaire():
    """Un instrument ne se prend jamais lui-meme pour une mesure (paye 5x en 3 jours)."""
    src = Path(ftd.__file__).read_text(encoding="utf-8", errors="replace")
    assert "win32security" in src or "GetFileSecurity" in src, (
        "aucune lecture de securite Windows dans la source : la mesure est simulee"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
