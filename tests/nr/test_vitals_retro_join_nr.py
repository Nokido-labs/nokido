"""Non-regression : la retro-jointure des canaux evenementiels.

CE QUE CES TESTS PROTEGENT
==========================
La jointure reconstitue des canaux sur un historique deja ecrit. Le risque n'est
pas qu'elle plante -- c'est qu'elle REMPLISSE a tort : recopier la valeur d'un
voisin trop lointain, ou compter comme mesure ce qui n'a pas ete lu. Un banc
nourri par une jointure complaisante rendrait un verdict sur des donnees
inventees, et rien dans son rapport ne le dirait.

Tests PURS : aucun service, aucun reseau, aucune base reelle -- les chemins de la
boite noire et de la base sont injectes (c'est pour cela qu'ils le sont).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

rj = pytest.importorskip("forge_vitals_retro_join")


def _blackbox(tmp_path: Path, lignes: list[dict]) -> Path:
    p = tmp_path / "hub_blackbox.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lignes) + "\n", encoding="utf-8")
    return p


def _hub(threads=30, handles=1500, fds=15, rss=0.8, cpu=2.0) -> dict:
    return {"threads": threads, "handles": handles, "fds": fds,
            "rss_gb": rss, "cpu_pct": cpu}


def test_un_voisin_dans_la_tolerance_remplit_les_canaux(tmp_path):
    bb = _blackbox(tmp_path, [{"ts": 1000.0, "hub": _hub(handles=1234)}])
    hist = [{"ts": 1005.0, "ram_pct": 50.0}]
    enrichi, rapport = enrichir_sans_db(hist, bb)
    assert enrichi[0]["hhd"] == 1234
    assert enrichi[0]["hth"] == 30
    assert rapport["couverture_pct"]["hhd"] == 100.0
    assert rapport["sans_voisin_blackbox"] == 0


def test_un_voisin_hors_tolerance_ne_remplit_RIEN(tmp_path):
    """Le defaut qu'on refuse : recopier une valeur vieille de dix minutes.

    Absent n'est pas zero. Si un jour ce test tombe parce que le canal vaut 0.0
    au lieu d'etre absent, la jointure a commence a inventer."""
    bb = _blackbox(tmp_path, [{"ts": 1000.0, "hub": _hub()}])
    hist = [{"ts": 1000.0 + 10 * 60, "ram_pct": 50.0}]
    enrichi, rapport = enrichir_sans_db(hist, bb)
    for canal in ("hth", "hhd", "hfd", "hrs", "hcp"):
        assert canal not in enrichi[0], "canal rempli hors tolerance : %s" % canal
    assert rapport["sans_voisin_blackbox"] == 1
    assert rapport["couverture_pct"]["hhd"] == 0.0


def test_le_plus_proche_voisin_est_choisi_pas_le_precedent(tmp_path):
    bb = _blackbox(tmp_path, [{"ts": 1000.0, "hub": _hub(handles=111)},
                              {"ts": 1020.0, "hub": _hub(handles=222)}])
    hist = [{"ts": 1018.0, "ram_pct": 50.0}]
    enrichi, _ = enrichir_sans_db(hist, bb)
    assert enrichi[0]["hhd"] == 222


def test_les_lignes_sans_bloc_hub_sont_COMPTEES_pas_ignorees(tmp_path):
    """Une ligne ecartee en silence fait surestimer la profondeur disponible."""
    bb = _blackbox(tmp_path, [{"ts": 900.0},                      # pas de bloc hub
                              {"ts": 950.0, "hub": {}},           # bloc vide
                              {"ts": 1000.0, "hub": _hub()}])
    hist = [{"ts": 1000.0, "ram_pct": 50.0}]
    _, rapport = enrichir_sans_db(hist, bb)
    assert rapport["lignes_blackbox"] == 1
    assert rapport["lignes_blackbox_ecartees"] == 2


def test_un_echantillon_sans_horodatage_traverse_sans_etre_enrichi(tmp_path):
    bb = _blackbox(tmp_path, [{"ts": 1000.0, "hub": _hub()}])
    hist = [{"ram_pct": 50.0}]
    enrichi, _ = enrichir_sans_db(hist, bb)
    assert enrichi[0] == {"ram_pct": 50.0}


def test_la_couverture_est_publiee_pour_chaque_canal(tmp_path):
    """Sans couverture publiee, un canal rempli a 15 % se lit comme une mesure."""
    bb = _blackbox(tmp_path, [{"ts": 1000.0, "hub": _hub()}])
    hist = [{"ts": 1000.0}, {"ts": 99999.0}]
    _, rapport = enrichir_sans_db(hist, bb)
    attendus = {"hth", "hhd", "hfd", "hrs", "hcp", "ln", "lp95", "lmax", "lerr", "lbi", "lbo"}
    assert set(rapport["couverture_pct"]) == attendus
    assert rapport["couverture_pct"]["hth"] == 50.0


def enrichir_sans_db(hist, chemin_bb):
    """Jointure sans la base de metriques : le fichier pointe n'existe pas, donc
    `charger_metriques` rend une liste vide -- exactement ce qu'on veut isoler."""
    return rj.enrichir(hist, chemin_blackbox=chemin_bb,
                       chemin_db=chemin_bb.parent / "_aucune_base.db")
