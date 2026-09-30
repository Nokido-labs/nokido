# -*- coding: utf-8 -*-
"""NR - l'audit de regulation instruit ses zones mortes au lieu de les proclamer (2026-09-06).

Contrats :
  1. un nom de script AVEC ESPACE est capte quand il est cite entre guillemets
     ("Nokido Tray.bat" dans install_shortcuts.ps1) -- trois lanceurs sortaient
     ZONE_MORTE pour un regex qui ne savait pas lire un espace ;
  2. un script invoque par le SYSTEME (tache planifiee, service nssm) est INVOQUE, pas
     ZONE_MORTE ; et quand l'observateur systeme ne peut pas lire, il le DIT (etat
     ILLISIBLE avec sa raison) au lieu de rendre un zero ;
  3. une zone morte INSTRUITE (mesuree, datee) porte son verdict et sa raison, et le
     verdict ZONE_MORTE residuel nomme ce qui n'a PAS ete lu (lanceurs owner) ;
  4. rien ici n'est un permis de suppression : les statuts d'instruction sont des
     mesures (INSTALLATEUR, OUTIL, ASSET, GELE, NON_CABLE, INDETERMINE).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

A = pytest.importorskip("forge_body_regulation_audit")


def test_un_nom_a_espace_est_capte_entre_guillemets():
    txt = 'Copy-Item "Nokido Tray.bat" ; run forge_x.py ; "app/forge_y.py"'
    nus = set(A.REF_PAT.findall(txt))
    cites = set(A.REF_PAT_CITE.findall(txt))
    assert "forge_x.py" in nus and "Nokido Tray.bat" not in nus
    assert "Nokido Tray.bat" in cites
    assert "Nokido Tray.bat" not in A.REF_PAT_CITE.findall("Nokido Tray.bat sans guillemets")


def test_invoque_par_le_systeme_prime_sur_zone_morte():
    st, why = A.verdict("forge_ssot_maintainer.py", {}, {}, {}, "lib", {}, {},
                        {"forge_ssot_maintainer.py": ["schtasks"]})
    assert st == "INVOQUE" and "schtasks" in why


def test_un_observateur_systeme_illisible_le_dit(monkeypatch):
    def _boom(*a, **k):
        raise OSError("acces refuse")
    monkeypatch.setattr(subprocess, "run", _boom)
    refs, etats = A.scan_systeme()
    assert refs == {}
    assert etats and all(e["etat"] == "ILLISIBLE" and "OSError" in e["raison"] for e in etats.values())


def test_une_zone_morte_instruite_porte_verdict_et_date():
    st, why = A.verdict("supervisor.backup.ts", {}, {}, {}, "lib", {}, {}, {})
    assert st == "GELE" and A.INSTRUITS_LE in why
    # Une MENTION dans la doctrine (RULES_SHARED, memoire) n'est pas une invocation :
    # l'instruction datee prime, le compte reste dit. Mesure 2026-09-06 : les 29
    # sortaient INVOQUE « cite par 1 fichier » -- l'audit lui-meme, puis la doctrine.
    st, why = A.verdict("supervisor.backup.ts", {}, {}, {}, "lib", {"supervisor.backup.ts": 2}, {}, {})
    assert st == "GELE" and "cite par 2" in why
    # ...mais un import ou une invocation SYSTEME la retirent d'eux-memes.
    assert A.verdict("forge_cert_binding.py", {}, {}, {"forge_cert_binding.py": 1}, "lib", {}, {}, {})[0] == "CABLE"
    assert A.verdict("forge_cert_binding.py", {}, {}, {}, "lib", {}, {}, {"forge_cert_binding.py": ["schtasks"]})[0] == "INVOQUE"
    st, why = A.verdict("forge_cert_binding.py", {}, {}, {}, "lib", {}, {}, {})
    assert st == "NON_CABLE"
    st, why = A.verdict("register_autopoiesis_cp.ps1", {}, {}, {}, "lib", {}, {}, {})
    assert st == "INDETERMINE" and "ILLISIBLE" in why
    assert all(s in ("INSTALLATEUR", "OUTIL", "ASSET", "GELE", "NON_CABLE", "INDETERMINE")
               for s, _ in A.INSTRUITS.values())


def test_la_zone_morte_residuelle_nomme_ce_qui_n_a_pas_ete_lu():
    st, why = A.verdict("forge_inconnu_du_jour.py", {}, {}, {}, "lib", {}, {}, {})
    assert st == "ZONE_MORTE" and "owner" in why and "taches planifiees" in why
