"""NR (29/10) : le meilleur prouve n'est comparable QUE sous le meme juge gele (memes empreintes juge + corpus).

Mesure : corpus du juge d'ancrage enrichi (824dab690, F1 1,0 -> 0,578), puis recette job_1a73a9186e99 : le banc a
garde `meilleur_prouve = 1.0`, la reference mesuree sur l'ANCIEN corpus, et n'a pas remesure. Un candidat a 0,7 sur le
nouveau corpus aurait ete classe REGRESSION. Regle n.1 de la methode takehome : juge gele -> un juge change impose une
nouvelle reference.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _banc():
    nom = "forge_banc_amelioration_nr_ref_juge"
    if nom in sys.modules:
        return sys.modules[nom]
    sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
    spec = importlib.util.spec_from_file_location(nom, ROOT / "tools" / "forge_banc_amelioration.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[nom] = m
    spec.loader.exec_module(m)
    return m


def test_meilleur_prouve_ignore_un_autre_juge(tmp_path):
    m = _banc()
    reg = tmp_path / "registre.jsonl"
    ancien, neuf = {"corpus.jsonl": "aaa"}, {"corpus.jsonl": "bbb"}
    m.consigner_banc(reg, "c", "REFERENCE", 1.0, "max", "banc:reference", reference=ancien)
    assert m.meilleur_prouve(reg, "max", juge_ref=neuf) is None
    m.consigner_banc(reg, "c", "REFERENCE", 0.578, "max", "banc:reference", reference=neuf)
    assert m.meilleur_prouve(reg, "max", juge_ref=neuf)["metrique"] == 0.578
    assert m.meilleur_prouve(reg, "max", juge_ref=ancien)["metrique"] == 1.0


def test_boucle_remesure_la_reference_quand_le_corpus_change(tmp_path):
    m = _banc()
    racine = tmp_path / "depot"
    (racine / "b").mkdir(parents=True)
    corpus = racine / "b" / "corpus.jsonl"
    corpus.write_text("ancien\n", encoding="utf-8")
    banc = {"perimetre": ["x.py"], "juge": {"commande": "x", "metrique": "metrique", "sens": "max",
                                              "empreintes": ["b/corpus.jsonl"]},
            "garde_tests": [], "axes": [], "budget_iterations": 0}
    mesures = iter([1.0, 0.578])
    deps = m.Deps(copier=lambda r, d: d.mkdir(parents=True, exist_ok=True),
                  generer=lambda p: (None, "faux"), appliquer=lambda *a: (False, "x"),
                  garde=lambda b, c: (True, ""), juge=lambda b, c: next(mesures),
                  thymus=lambda *a: {}, pre_flight=lambda t: (True, ""),
                  retirer=lambda r, d: None)
    dossier, copies = tmp_path / "banc", tmp_path / "copies"
    assert m.boucle("c", banc, 0, racine, dossier, deps, copies)["meilleur_prouve"] == 1.0
    corpus.write_text("neuf, enrichi\n", encoding="utf-8")
    assert m.boucle("c", banc, 0, racine, dossier, deps, copies)["meilleur_prouve"] == 0.578
    refs = [l for l in m.lire_registre(dossier / "registre.jsonl") if l["statut"] == "REFERENCE"]
    assert len(refs) == 2
