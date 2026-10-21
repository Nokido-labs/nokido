"""NR 18/10 -- une archive Takeout mise de cote consigne sa STRUCTURE (jamais son contenu).

1er passage reel du guet (18/10 19:13-19:31) : 2 exports Google Takeout MIS_DE_COTE (« format a lire sur un vrai
export avant tout analyseur »). Le guet tourne sous le compte owner ; le hub n'a pas acces au dossier Telechargements
(mesure). Le guet consigne donc lui-meme la forme reelle : dossiers des 3 premiers niveaux, extensions, membres
Gemini/Bard et leur taille -- pour ecrire l'analyseur sur la forme REELLE, jamais devinee. Une entree MIS_DE_COTE
ancienne sans structure se complete au passage suivant ; les autres verdicts terminaux restent intouches.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_guet_exports as G  # noqa: E402


def _takeout(tmp_path):
    z = tmp_path / "takeout-20261018.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("Takeout/archive_browser.html", "<html>secret owner</html>")
        zf.writestr("Takeout/My Activity/Gemini Apps/MyActivity.json", '[{"title": "conversation privee"}]')
        zf.writestr("Takeout/My Activity/Search/MyActivity.json", "[]")
    return z


def _rien(*a, **k):
    raise AssertionError("un Takeout ne doit pas etre indexe")


def test_takeout_mis_de_cote_porte_sa_structure_sans_contenu(tmp_path):
    etat = {}
    v = G.traiter(_takeout(tmp_path), tmp_path / "out", etat, _rien, _rien)
    assert v["verdict"] == "MIS_DE_COTE"
    s = v["structure"]
    assert s["membres"] == 3 and s["extensions"] == {".html": 1, ".json": 2}
    assert s["dossiers"]["Takeout/My Activity/Gemini Apps"] == 1
    assert ["Takeout/My Activity/Gemini Apps/MyActivity.json", len('[{"title": "conversation privee"}]')] in s["gemini"]
    assert "conversation privee" not in str(v) and "secret owner" not in str(v), "jamais le contenu"


def test_une_ancienne_entree_sans_structure_se_complete(tmp_path):
    z = _takeout(tmp_path)
    etat = {G.empreinte(z): {"zip": z.name, "verdict": "MIS_DE_COTE", "type": "takeout"}}
    v = G.traiter(z, tmp_path / "out", etat, _rien, _rien)
    assert v["verdict"] == "MIS_DE_COTE" and "structure" in v


def test_le_chemin_reel_passage_complete_l_ancienne_entree(tmp_path):
    import json
    import os
    import time

    tele = tmp_path / "Telechargements"
    tele.mkdir()
    z = _takeout(tele)
    vieux = time.time() - 3600
    os.utime(z, (vieux, vieux))
    st = z.stat()
    emp = G.empreinte(z)
    etat_f = tmp_path / "etat.json"
    etat_f.write_text(json.dumps({"_signatures": {"%s|%d|%d" % (z.name, st.st_size, int(st.st_mtime)): emp},
                                  emp: {"zip": z.name, "verdict": "MIS_DE_COTE", "type": "takeout"}}), encoding="utf-8")
    G.passage(tele, tmp_path / "out", etat_f, _rien, _rien)
    assert "structure" in json.loads(etat_f.read_text(encoding="utf-8"))[emp], "passage court-circuitait l'entree"


def test_les_autres_verdicts_terminaux_restent_intouches(tmp_path):
    z = _takeout(tmp_path)
    fige = {"zip": z.name, "verdict": "IGNORE", "type": "INCONNU"}
    etat = {G.empreinte(z): dict(fige)}
    assert G.traiter(z, tmp_path / "out", etat, _rien, _rien) == fige
