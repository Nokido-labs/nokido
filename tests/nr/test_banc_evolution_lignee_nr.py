"""NR -- banc d'EVOLUTION avec retour arriere (owner 30/10 : « ecris le banc d'evolution avec retour arriere possible »).

Mesure du 30/10 : chaque copie partait de HEAD (0,609) alors que le meilleur prouve (0,630) attendait l'owner -- les
candidats devaient redecouvrir le gain pour seulement l'egaler (18 essais, 1 AMELIORE). Desormais :
(1) un AMELIORE devient un NOEUD de lignee (contenu complet du perimetre + empreinte de la base HEAD + parent) et le
tour suivant part de lui ; son patch est CUMULATIF par rapport a HEAD (integrable seul par l'owner) ;
(2) `retour(n)` ecarte les n derniers noeuds sans rien effacer (lignes RETIRE ajoutees) ;
(3) si HEAD a bouge sous un noeud, retour arriere AUTOMATIQUE vers un noeud compatible ou HEAD, et c'est DIT.
Faux generateur, faux juge, tmp_path : aucun reseau, aucun LLM, aucune ecriture dans l'arbre partage.
"""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import forge_banc_amelioration as B  # noqa: E402

BANC = {"perimetre": ["tools/mod.py"], "fonctions": ["V"],
        "juge": {"commande": "python juge.py", "metrique": "f1", "sens": "max"},
        "garde_tests": ["tests/test_mod.py"], "axes": [{"nom": "a", "description": "d"}], "budget_iterations": 3,
        "evolution": True}


def _patch(de, vers):
    return "FICHIER: tools/mod.py\n<<<<<<< SEARCH\nV = %s\n=======\nV = %s\n>>>>>>> REPLACE" % (de, vers)


def _arbre(tmp_path):
    r = tmp_path / "partage"
    if not r.exists():
        (r / "tools").mkdir(parents=True)
        (r / "tests").mkdir()
        (r / "tools" / "mod.py").write_text("V = 1\n", encoding="utf-8")
        (r / "tests" / "test_mod.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    return r


def _deps(texte, metrique):
    def appliquer(fp, s, rep):
        o = fp.read_text(encoding="utf-8")
        if s not in o:
            return False, "search introuvable"
        fp.write_text(o.replace(s, rep, 1), encoding="utf-8")
        return True, o

    return B.Deps(copier=lambda racine, dest: shutil.copytree(racine, dest),
                  generer=lambda prompt: (texte, "faux_gratuit"), appliquer=appliquer,
                  garde=lambda banc, copie: (True, "faux garde"), juge=lambda banc, copie: metrique,
                  thymus=lambda ref, rel, new, tests: {"verdict": "SURVIT", "status": "OK"},
                  pre_flight=lambda t: (True, None))


def _tour(tmp_path, i, texte, metrique, meilleur):
    r = _arbre(tmp_path)
    d = tmp_path / "bancs" / "cible"
    return d, B.iteration("cible", BANC, i, r, d, _deps(texte, metrique), tmp_path / "copies", meilleur)


def test_ameliore_devient_noeud_et_le_tour_suivant_part_de_lui(tmp_path):
    d, r0 = _tour(tmp_path, 0, _patch(1, 2), 0.6, 0.5)
    assert r0["verdict"] == "AMELIORE"
    actifs = B.noeuds_actifs(d)
    assert len(actifs) == 1 and actifs[0]["parent"] is None
    d, r1 = _tour(tmp_path, 1, _patch(2, 3), 0.7, 0.6)  # SEARCH « V = 2 » n'existe QUE dans le noeud
    assert r1["verdict"] == "AMELIORE" and r1["base_noeud"] == actifs[0]["id"]
    n2 = B.noeuds_actifs(d)[-1]
    assert n2["parent"] == actifs[0]["id"]
    patch = Path(r1["patch"]).read_text(encoding="utf-8")
    assert "-V = 1" in patch and "+V = 3" in patch  # cumulatif par rapport a HEAD
    assert (_arbre(tmp_path) / "tools" / "mod.py").read_text(encoding="utf-8") == "V = 1\n"  # arbre partage intact


def test_retour_arriere_ecarte_sans_effacer(tmp_path):
    d, _ = _tour(tmp_path, 0, _patch(1, 2), 0.6, 0.5)
    d, _ = _tour(tmp_path, 1, _patch(2, 3), 0.7, 0.6)
    premier, second = B.noeuds_actifs(d)
    assert B.retour(d, 1) == [second["id"]]
    assert [n["id"] for n in B.noeuds_actifs(d)] == [premier["id"]]
    lignes = [json.loads(l) for l in (d / B.LIGNEE).read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(l.get("id") == second["id"] for l in lignes) and any(l.get("retire") == second["id"] for l in lignes)
    noeud, motifs = B.base_evolution(d, BANC, _arbre(tmp_path))
    assert noeud["id"] == premier["id"] and motifs == []


def test_le_journal_de_la_boucle_dit_d_ou_part_le_candidat(tmp_path):
    d, r0 = _tour(tmp_path, 0, _patch(1, 2), 0.6, 0.5)
    noeud = B.noeuds_actifs(d)[0]["id"]
    deps = _deps(_patch(2, 3), 0.7)
    deps.juge = lambda banc, copie: 0.7
    bilan = B.boucle("cible", dict(BANC, budget_iterations=1), 1, _arbre(tmp_path), d, deps, tmp_path / "copies")
    assert bilan["journal"][0]["base_noeud"] == noeud


def test_sans_drapeau_evolution_le_banc_part_de_head(tmp_path):
    sans = {k: v for k, v in BANC.items() if k != "evolution"}
    r = _arbre(tmp_path)
    d = tmp_path / "bancs" / "cible"
    r0 = B.iteration("cible", sans, 0, r, d, _deps(_patch(1, 2), 0.6), tmp_path / "copies", 0.5)
    assert r0["verdict"] == "AMELIORE" and B.noeuds_actifs(d) == []
    r1 = B.iteration("cible", sans, 1, r, d, _deps(_patch(1, 2), 0.6), tmp_path / "copies", 0.6)
    assert r1["verdict"] == "EGAL"  # le meme patch s'applique encore : la copie est partie de HEAD


def test_head_a_bouge_retour_automatique_dit(tmp_path):
    d, _ = _tour(tmp_path, 0, _patch(1, 2), 0.6, 0.5)
    (_arbre(tmp_path) / "tools" / "mod.py").write_text("V = 9\n", encoding="utf-8")  # HEAD bouge sous le noeud
    noeud, motifs = B.base_evolution(d, BANC, _arbre(tmp_path))
    assert noeud is None and motifs and "base" in motifs[0]
    d, r = _tour(tmp_path, 1, _patch(9, 10), 0.7, 0.6)
    assert r["verdict"] == "AMELIORE" and r.get("base_noeud") is None and "base" in r.get("evolution", "")
