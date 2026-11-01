"""NR -- BANC D'AMELIORATION (owner 29/10) : la methode takehome generalisee.

Faux generateur, faux juge, tmp_path : aucun reseau, aucun LLM. Le banc n'accepte un candidat que s'il est
EXACT (garde verte) ET strictement meilleur que le meilleur prouve ; il ne commite jamais et n'ecrit jamais
dans l'arbre partage."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import forge_banc_amelioration as B  # noqa: E402
import forge_bench_takehome as T  # noqa: E402

BANC = {"perimetre": ["tools/mod.py"], "fonctions": ["f"],
        "juge": {"commande": "python juge.py", "metrique": "f1", "sens": "max"},
        "garde_tests": ["tests/test_mod.py"], "axes": [{"nom": "a", "description": "d"}], "budget_iterations": 3}
PATCH = "FICHIER: tools/mod.py\n<<<<<<< SEARCH\nV = 1\n=======\nV = 2\n>>>>>>> REPLACE"


def _arbre(tmp_path):
    r = tmp_path / "partage"
    if r.exists():
        return r
    (r / "tools").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / "tools" / "mod.py").write_text("V = 1\n", encoding="utf-8")
    (r / "tests" / "test_mod.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    return r


def _empreinte(r):
    return {str(p.relative_to(r)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob("*")) if p.is_file()}


def _deps(texte=PATCH, metriques=(0.5,), garde_ok=True, thymus_appels=None):
    mets = list(metriques)
    appels = thymus_appels if thymus_appels is not None else []

    def appliquer(fp, s, rep):
        o = fp.read_text(encoding="utf-8")
        if s not in o:
            return False, "search introuvable"
        fp.write_text(o.replace(s, rep, 1), encoding="utf-8")
        return True, o

    return B.Deps(
        copier=lambda racine, dest: shutil.copytree(racine, dest),
        generer=lambda prompt: (texte, "faux_gratuit"),
        appliquer=appliquer,
        garde=lambda banc, copie: (garde_ok, "faux garde"),
        juge=lambda banc, copie: mets.pop(0) if mets else None,
        thymus=lambda ref, rel, new, tests: appels.append((rel, new, tests)) or {"verdict": "SURVIT", "status": "OK"},
        pre_flight=lambda t: (True, None))


def _lancer(tmp_path, deps, banc=BANC, meilleur=None):
    r = _arbre(tmp_path)
    d = tmp_path / "bancs" / "cible"
    return r, d, B.iteration("cible", banc, 0, r, d, deps, tmp_path / "copies", meilleur)


def test_banc_sans_juge_refuse_au_chargement(tmp_path):
    cfg = tmp_path / "b.json"
    sans = {k: v for k, v in BANC.items() if k != "juge"}
    faux_sens = {**BANC, "juge": {"commande": "x", "metrique": "m", "sens": "moyen"}}
    cfg.write_text(json.dumps({"bons": BANC, "sans_juge": sans, "sens_faux": faux_sens}), encoding="utf-8")
    ok, refus = B.charger_bancs(cfg)
    assert list(ok) == ["bons"]
    assert "juge" in refus["sans_juge"] and "sens" in refus["sens_faux"]


def test_patch_hors_perimetre_refuse(tmp_path):
    p = "FICHIER: tools/autre.py\n<<<<<<< SEARCH\nV = 1\n=======\nV = 2\n>>>>>>> REPLACE"
    _, _, r = _lancer(tmp_path, _deps(texte=p))
    assert r["verdict"] == "HORS_PERIMETRE" and "perimetre" in r["motif"]


def test_patch_touchant_un_test_refuse(tmp_path):
    p = "FICHIER: tests/test_mod.py\n<<<<<<< SEARCH\nassert True\n=======\nassert False\n>>>>>>> REPLACE"
    _, _, r = _lancer(tmp_path, _deps(texte=p))
    assert r["verdict"] == "HORS_PERIMETRE" and "test" in r["motif"]


def test_non_applicable(tmp_path):
    p = "FICHIER: tools/mod.py\n<<<<<<< SEARCH\nZZZ\n=======\nV = 2\n>>>>>>> REPLACE"
    _, _, r = _lancer(tmp_path, _deps(texte=p))
    assert r["verdict"] == "NON_APPLICABLE"


def test_garde_rouge(tmp_path):
    _, _, r = _lancer(tmp_path, _deps(garde_ok=False, metriques=(0.9,)), meilleur=0.5)
    assert r["verdict"] == "GARDE_ROUGE"


def test_metrique_egale_est_egal(tmp_path):
    _, _, r = _lancer(tmp_path, _deps(metriques=(0.5,)), meilleur=0.5)
    assert r["verdict"] == "EGAL"


def test_metrique_pire_est_regression(tmp_path):
    _, _, r = _lancer(tmp_path, _deps(metriques=(0.4,)), meilleur=0.5)
    assert r["verdict"] == "REGRESSION"


def test_sens_min_inverse_la_comparaison(tmp_path):
    banc = {**BANC, "juge": {**BANC["juge"], "sens": "min"}}
    _, _, r = _lancer(tmp_path, _deps(metriques=(0.4,)), banc=banc, meilleur=0.5)
    assert r["verdict"] == "AMELIORE"


def test_meilleure_est_amelioree_thymus_puis_awaiting_owner(tmp_path):
    appels = []
    racine, d, r = _lancer(tmp_path, _deps(metriques=(0.8,), thymus_appels=appels), meilleur=0.5)
    assert r["verdict"] == "AMELIORE" and r["statut"] == "AWAITING_OWNER"
    assert len(appels) == 1 and appels[0][0] == "tools/mod.py" and "V = 2" in appels[0][1]
    assert appels[0][2] == ["tests/test_mod.py"]
    assert list((d / "candidats").glob("*.patch")), "patch conserve"
    assert (racine / "tools" / "mod.py").read_text(encoding="utf-8") == "V = 1\n"


def test_non_amelioration_ne_saisit_pas_le_thymus(tmp_path):
    appels = []
    _lancer(tmp_path, _deps(metriques=(0.5,), thymus_appels=appels), meilleur=0.5)
    assert appels == []


def test_registre_chaine_verifiable_et_falsification_detectee(tmp_path):
    racine = _arbre(tmp_path)
    d = tmp_path / "bancs" / "cible"
    bilan = B.boucle("cible", BANC, 2, racine, d, _deps(metriques=(0.5, 0.8, 0.8)), tmp_path / "copies")
    reg = d / "registre.jsonl"
    lignes = [json.loads(l) for l in reg.read_text(encoding="utf-8").splitlines()]
    assert lignes[0]["statut"] == "REFERENCE" and lignes[0]["metrique"] == 0.5
    assert bilan["verdicts"].get("AMELIORE") == 1 and bilan["verdicts"].get("EGAL") == 1
    assert T.verifier_registre(reg)["ok"]
    falsifie = reg.read_text(encoding="utf-8").replace('"metrique": 0.5', '"metrique": 0.1', 1)
    assert falsifie != reg.read_text(encoding="utf-8")
    reg.write_text(falsifie, encoding="utf-8")
    assert not T.verifier_registre(reg)["ok"]


def test_reference_inscrite_une_seule_fois(tmp_path):
    racine = _arbre(tmp_path)
    d = tmp_path / "bancs" / "cible"
    B.boucle("cible", BANC, 1, racine, d, _deps(metriques=(0.5, 0.5)), tmp_path / "copies")
    B.boucle("cible", BANC, 1, racine, d, _deps(metriques=(0.5,)), tmp_path / "copies")
    st = [json.loads(l)["statut"] for l in (d / "registre.jsonl").read_text(encoding="utf-8").splitlines()]
    assert st.count("REFERENCE") == 1


def test_arbre_partage_jamais_ecrit(tmp_path):
    racine = _arbre(tmp_path)
    avant = _empreinte(racine)
    B.boucle("cible", BANC, 2, racine, tmp_path / "bancs" / "cible", _deps(metriques=(0.5, 0.9, 0.9)),
             tmp_path / "copies")
    assert _empreinte(racine) == avant


def test_rapport_taux_de_pertinence(tmp_path):
    racine = _arbre(tmp_path)
    d = tmp_path / "bancs" / "cible"
    B.boucle("cible", BANC, 2, racine, d, _deps(metriques=(0.5, 0.9, 0.5)), tmp_path / "copies")
    rap = B.rapport(tmp_path / "bancs")["cible"]
    assert rap["meilleur_prouve"] == 0.9 and rap["essais"] == 2 and rap["ameliores"] == 1
    assert rap["taux_pertinence"] == 0.5 and len(rap["awaiting_owner"]) == 1


def test_generateur_payant_refuse():
    assert B.generateurs_gratuits({"TAKEHOME_PROVIDERS": "groq:x,claude_cli"})[0] is False
    assert B.generateurs_gratuits({"TAKEHOME_PROVIDERS": "groq:x,gemini"})[0] is True


def test_pre_flight_refuse_bloque_l_envoi(tmp_path):
    d = _deps()
    d.pre_flight = lambda t: (False, "DLP")
    _, _, r = _lancer(tmp_path, d, meilleur=0.5)
    assert r["verdict"] == "PRE_FLIGHT_REFUSE"


def test_instrument_soif_banc_amelioration(tmp_path, monkeypatch):
    import forge_epistemic_veille as V
    racine = _arbre(tmp_path)
    d = tmp_path / "bancs" / "cible"
    B.boucle("cible", BANC, 1, racine, d, _deps(metriques=(0.5, 0.5)), tmp_path / "copies")
    monkeypatch.setattr(V, "_BANCS", tmp_path / "bancs", raising=False)
    lac = {"instrument": "banc_amelioration:cible", "critere": {"seuil": 0.9, "sens": "max"}}
    m = V.mesurer_selon_instrument(lac)
    assert m["ok"] and m["gap"] is True and m["score"] == 0.5
    lac["critere"]["seuil"] = 0.4
    assert V.mesurer_selon_instrument(lac)["gap"] is False
    # impossibilite MESUREE : N essais sans gain, dits
    lac["critere"] = {"seuil": 0.9, "sens": "max", "n_impossible": 1}
    m = V.mesurer_selon_instrument(lac)
    assert m["gap"] is False and m["score"] == "IMPOSSIBLE_MESURE"
