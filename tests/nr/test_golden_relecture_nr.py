# -*- coding: utf-8 -*-
"""NR -- page LOCALE de relecture owner du jeu de reference RAG (decision owner 19/10 : « je relis, page a cocher »,
« locale, portail :7400 » : rien ne sort de la machine).

Le protocole (docs/PROTOCOLE_MESURE_METHODES_DEV.md) exige la relecture owner des 54 questions de
docs/rapports/golden_dataset_retrieval_20261019.json avant toute mesure du rappel@10 (item bb
roadmap_p1_methode_dev_par_couches_20261016). Contrat (app/web_hub/golden_relecture.py + 2 routes de wired_routes) :
  1. `charger()` rend les 54 questions du jeu ; jeu illisible -> None (jamais [] : vide != illisible) ;
  2. `page_html(questions, relecture)` montre chaque question (id, question, reponse attendue, sources, piege) avec
     trois choix VALIDE / REJETEE / A_REVOIR et une note, et reprend les verdicts deja enregistres ;
  3. `enregistrer(choix, ids_connus, chemin)` n'ecrit QUE des ids du jeu et des verdicts du vocabulaire, fusionne
     avec l'existant (rien n'est efface), borne la note, et DIT ce qu'il refuse ;
  4. `lire_relecture(chemin)` : absent -> {} ; illisible -> None ;
  5. routes GET /golden/relecture et POST /api/golden/relecture dans wired_routes (pas dans app.py, CRITICAL).
"""
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.web_hub import golden_relecture as gr  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def test_le_jeu_reel_porte_54_questions():
    q = gr.charger()
    assert q is not None and len(q) == 54
    assert all(x.get("id") and x.get("question") for x in q)


def test_jeu_illisible_n_est_pas_vide(tmp_path):
    p = tmp_path / "jeu.json"
    p.write_text("{pas du json", encoding="utf-8")
    assert gr.charger(p) is None
    assert gr.charger(tmp_path / "absent.json") is None


def test_la_page_montre_chaque_question_et_reprend_les_verdicts():
    q = gr.charger()
    html = gr.page_html(q, {q[0]["id"]: {"verdict": "REJETEE", "note": "source fausse"}})
    for x in q:
        assert x["id"] in html
    assert html.count('value="VALIDE"') == 54 and html.count('value="REJETEE"') == 54
    assert "source fausse" in html and "/api/golden/relecture" in html


def test_enregistrer_filtre_fusionne_et_dit_ce_qu_il_refuse(tmp_path):
    chemin = tmp_path / "relecture.json"
    ids = {"retrieval_001", "retrieval_002"}
    r = gr.enregistrer({"retrieval_001": {"verdict": "VALIDE", "note": "ok"},
                        "inconnu_9": {"verdict": "VALIDE"},
                        "retrieval_002": {"verdict": "PEUT_ETRE"}}, ids, chemin)
    assert r["enregistres"] == 1 and set(r["refuses"]) == {"inconnu_9", "retrieval_002"}
    r = gr.enregistrer({"retrieval_002": {"verdict": "A_REVOIR", "note": "x" * 5000}}, ids, chemin)
    d = gr.lire_relecture(chemin)
    assert d["retrieval_001"]["verdict"] == "VALIDE"            # fusion : rien n'est efface
    assert d["retrieval_002"]["verdict"] == "A_REVOIR" and len(d["retrieval_002"]["note"]) <= 500


def test_relecture_absente_vaut_vide_illisible_vaut_none(tmp_path):
    assert gr.lire_relecture(tmp_path / "absent.json") == {}
    p = tmp_path / "abime.json"
    p.write_text("[[[", encoding="utf-8")
    assert gr.lire_relecture(p) is None


def test_les_routes_sont_dans_wired_routes():
    src = (RACINE / "app" / "web_hub" / "wired_routes.py").read_text(encoding="utf-8")
    assert '@router.get("/golden/relecture")' in src and '@router.post("/api/golden/relecture")' in src
