# -*- coding: utf-8 -*-
"""Non-regression — l'anti-stacking s'arme SANS que l'appelant y pense.

Mesure 2026-08-29 : `run_job` acceptait `lane` en optionnel. Le controle d'embolie
s'appliquait, mais l'anti-stacking ne s'armait que si l'appelant nommait une lane.
Cinq jobs lourds ont ete empiles le meme jour, sans lane ni `rss_cap_mb` : RAM
saturee, hub tombe. **Un garde optionnel n'est pas un garde.**

Ce fichier verrouille les deux moities du contrat, car chacune se casse seule :

1. le garde est REELLEMENT dans la cible (un patch qui n'est pas applique protege
   autant qu'un garde branche sur un signal que personne n'emet) ;
2. la lane deduite ne SERIALISE PAS plus que necessaire — elle porte le nom du
   fichier lance, donc deux fichiers differents restent paralleles. Sans ce test,
   un « durcissement » futur en file unique passerait pour un progres alors qu'il
   briderait swarm et fan-out (« ne jamais serialiser par prudence »).
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

M = pytest.importorskip("forge_patch_lane_auto")


def lane_deduite(args: dict) -> str:
    """Rejoue le TEXTE REELLEMENT INJECTE, pas une reecriture de sa logique.

    Tester une copie du raisonnement laisserait passer une divergence entre ce que
    le test croit injecter et ce que le patch injecte."""
    espace: dict = {"args": args}
    exec(compile(textwrap.dedent(M.AJOUT), "<ajout>", "exec"), espace)  # noqa: S102
    return espace["_lane"]


# ------------------------------------------------- le garde est bien en place

def test_le_garde_est_present_dans_la_cible():
    """LE test : sans cette ligne dans app/forge_mcp_registry.py, rien ne protege."""
    src = M.CIBLE.read_text(encoding="utf-8")
    assert "LANE DEDUITE (2026-08-29)" in src, (
        "patch non applique : le garde d'admission n'existe que sur le papier")


def test_la_cible_compile_apres_patch():
    src = M.CIBLE.read_text(encoding="utf-8")
    compile(src, str(M.CIBLE), "exec")


def test_rejouer_le_patch_est_sans_effet():
    """Idempotent : une relance ne doit pas empiler deux fois le meme garde."""
    r = M.applique(dry_run=True)
    assert r["ok"] and r.get("deja_applique") and not r["modifie"]


# ------------------------------------------- ce que la lane deduite doit valoir

def test_une_lane_fournie_n_est_jamais_ecrasee():
    assert lane_deduite({"lane": "gpu8091", "script": "C:/tmp/x.py"}) == "gpu8091"


def test_lane_derivee_du_nom_du_fichier():
    assert lane_deduite({"script": "C:/tmp/campagne_ui.py"}) == "auto:campagne_ui.py"


def test_meme_fichier_autre_compte_autre_lane():
    # 2026-09-27 : meme script online puis offline refuse (« lane occupee ») -- deux travaux distincts.
    assert lane_deduite({"script": "C:/tmp/m.py", "online": True}) == "auto:m.py@online"
    assert lane_deduite({"script": "C:/tmp/m.py", "online": False}) == "auto:m.py"
    assert lane_deduite({"script": "C:/tmp/m.py", "online": True}) != lane_deduite({"script": "C:/tmp/m.py"})


def test_meme_fichier_meme_compte_s_exclut_toujours():
    # l'anti-stacking du MEME travail reste arme : meme fichier, meme compte -> meme lane.
    assert (lane_deduite({"script": "C:/tmp/m.py", "online": True})
            == lane_deduite({"script": r"C:\tmp\m.py", "online": True}))


def test_les_antislashs_windows_sont_normalises():
    assert lane_deduite({"script": r"C:\tmp\campagne_ui.py"}) == "auto:campagne_ui.py"


def test_le_champ_path_sert_de_repli():
    assert lane_deduite({"path": "tools/forge_x.py"}) == "auto:forge_x.py"


def test_sans_aucun_chemin_la_lane_reste_nommee():
    """Jamais de lane vide : une lane vide desarmerait l'anti-stacking en silence."""
    assert lane_deduite({}) == "auto:job"


def test_deux_fichiers_differents_restent_PARALLELISABLES():
    """La doctrine autorise le parallelisme : on borne l'empilement du MEME travail,
    pas la concurrence. Une file unique casserait swarm et fan-out."""
    a = lane_deduite({"script": "C:/tmp/a.py"})
    b = lane_deduite({"script": "C:/tmp/b.py"})
    assert a != b, "des travaux differents ne doivent PAS se serialiser"


def test_deux_lancements_du_meme_travail_s_excluent():
    a = lane_deduite({"script": "C:/tmp/scan.py"})
    b = lane_deduite({"script": r"D:\autre\scan.py"})
    assert a == b, "le meme fichier lance deux fois doit tomber dans la meme lane"


# ------------------------------------------------ ce qui doit REFUSER de patcher

def test_ancre_absente_refuse_de_patcher(tmp_path, monkeypatch):
    """Un patch qui ne retrouve pas son ancre ecrirait a l'aveugle : il doit refuser."""
    faux = tmp_path / "sans_ancre.py"
    faux.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(M, "CIBLE", faux)
    r = M.applique(dry_run=False)
    assert not r["ok"] and "ancre" in r["raison"]
    assert faux.read_text(encoding="utf-8") == "x = 1\n", "rien ne doit etre ecrit"


def test_cible_illisible_ne_conclut_pas(tmp_path, monkeypatch):
    """Illisible n'est pas « deja applique » : trois etats, jamais deux."""
    monkeypatch.setattr(M, "CIBLE", tmp_path / "jamais_ecrit.py")
    r = M.applique(dry_run=True)
    assert not r["ok"] and "illisible" in r["raison"]
