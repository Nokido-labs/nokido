"""NR -- frein AUTOMATIQUE sur recul de capacite, et lecteur des capacites mesurees.

Mission rsi-frein-auto (2026-10-02). La porte d'evolution savait s'arreter ; rien ne la
fermait quand une capacite MESUREE reculait. Ce NR fige :
  * recul hors bande, MEME cle            -> frein serre, motif CHIFFRE, par 'auto:capacite' ;
  * recul dans la bande                   -> pas de frein ;
  * cle de dimension changee              -> pas de comparaison (ni frein, ni feu vert) ;
  * mesure illisible / bruit non declare  -> ABSTENTION dite (ni frein, ni feu vert) ;
  * forge_capability_benchmark            -> {dimension: {score, bruit, n, age_s}}, INCONNU sinon.
Tout se passe dans un tmp : jamais sandbox/ reel, jamais docs/generations reel.
"""
from __future__ import annotations

import json
import time

import pytest

from nokido_agent.app import forge_capability_benchmark as fcb
from nokido_agent.app import forge_generation as fg
from nokido_agent.app import forge_mutation_judge as juge

pytestmark = pytest.mark.timeout(120)

DIM = "retrieval_dense_ndcg10@5fc574c6.37b152e6"


@pytest.fixture
def gen(tmp_path, monkeypatch):
    d = tmp_path / "generations"
    d.mkdir()
    for nom in ("DOSSIER", "DOSSIER_SEQUENCE", "DOSSIER_ATTENTE"):
        monkeypatch.setattr(fg, nom, d)
    freins = []
    halt = tmp_path / "evolution.halt"

    def _poser(motif, par=""):
        freins.append((motif, par))
        halt.write_text(motif, encoding="utf-8")
        return {"ok": True}
    monkeypatch.setattr(juge, "poser_frein_evolution", _poser, raising=False)
    # Hermetique (2026-10-02, CI GitHub de f85c19b03) : `capturer` sondait le VRAI depot -- glob de
    # tests/nr, git status complet, paquets, sous-modules -- et a consomme les 120 s du timeout sur un
    # poste charge ; avec un gain calcule il ecrivait aussi dans l'op-log REEL. Le frein se juge sans
    # ces sondes : on fige leur reponse, le statut et le frein restent calcules par le vrai code.
    monkeypatch.setattr(fg, "_empreinte_capacites", lambda: {"modules_forge": 1, "tests_nr": 1})
    monkeypatch.setattr(fg, "_paquets", lambda: {})
    monkeypatch.setattr(fg, "_lock", lambda: {})
    monkeypatch.setattr(fg, "_submodules", lambda: {})
    monkeypatch.setattr(fg, "_append_oplog", lambda *a, **k: None)
    _faux_git = {("rev-parse", "HEAD"): "f" * 40, ("rev-parse", "--abbrev-ref", "HEAD"): "alpha",
                 ("log", "-1", "--format=%s"): "sujet NR"}
    monkeypatch.setattr(fg, "_git", lambda *args, cwd=None: _faux_git.get(tuple(args), ""))
    return {"dossier": d, "freins": freins, "halt": halt}


def _stable(dossier, capacites, num=1):
    g = {"generation": "GEN-%05d" % num, "statut": "STABLE", "capacites": capacites,
         "depot": {"sha": "x" * 40}, "cree_le": "2026-10-01T00:00:00+00:00"}
    (dossier / ("GEN-%05d.json" % num)).write_text(json.dumps(g), encoding="utf-8")
    return g


def _cap(score, bruit=0.0588, n=17):
    return {DIM: {"score": score, "bruit": bruit, "n": n}}


# ── le frein ──────────────────────────────────────────────────────────────────────────
def test_recul_hors_bande_serre_le_frein_avec_un_motif_chiffre(gen):
    _stable(gen["dossier"], _cap(0.7647))
    v = fg.frein_si_recul(_cap(0.6500))
    assert v["verdict"] == "RECUL" and v["vs"] == "GEN-00001"
    (motif, par), = gen["freins"]
    assert par == "auto:capacite" == fg.PAR_FREIN_AUTO
    assert DIM in motif and "0.7647" in motif and "0.6500" in motif and "-0.1147" in motif
    assert gen["halt"].exists()


def test_recul_dans_la_bande_ne_freine_pas(gen):
    _stable(gen["dossier"], _cap(0.7647))
    v = fg.frein_si_recul(_cap(0.7200))                  # -0.0447, bande 0.0588
    assert v["verdict"] == "DANS_LA_BANDE" and v["frein"] is None and gen["freins"] == []


def test_dimension_changee_pas_de_comparaison(gen):
    _stable(gen["dossier"], _cap(0.9000))
    autre = {"retrieval_dense_ndcg10@aaaaaaaa.bbbbbbbb": {"score": 0.10, "bruit": 0.05}}
    v = fg.frein_si_recul(autre)
    assert v["verdict"] == "AUCUNE_DIMENSION_COMMUNE" and v["frein"] is None
    assert len(v["non_comparees"]) == 2 and gen["freins"] == []


@pytest.mark.parametrize("illisible", [None, "NaN", "n/a", float("inf")])
def test_mesure_illisible_abstention_ni_frein_ni_feu_vert(gen, illisible):
    _stable(gen["dossier"], dict(_cap(0.7647), autre={"score": 0.5, "bruit": 0.1}))
    v = fg.frein_si_recul(dict(_cap(illisible), autre={"score": 0.5, "bruit": 0.1}))
    # une dimension dans la bande ne suffit PAS a rendre « dans la bande » : l'autre est muette
    assert v["verdict"] == "ABSTENTION" and v["frein"] is None and gen["freins"] == []
    assert v["abstentions"][0]["dimension"] == DIM


def test_bruit_non_declare_abstention(gen):
    _stable(gen["dossier"], {DIM: {"score": 0.9}})
    v = fg.frein_si_recul({DIM: {"score": 0.1}})
    assert v["verdict"] == "ABSTENTION" and "bruit" in v["abstentions"][0]["motif"]
    assert gen["freins"] == []


def test_sans_reference_rien_a_comparer(gen):
    assert fg.frein_si_recul(_cap(0.1))["verdict"] == "SANS_REFERENCE" and gen["freins"] == []


def test_frein_absent_se_dit_sans_casser(gen, monkeypatch):
    _stable(gen["dossier"], _cap(0.7647))
    monkeypatch.delattr(juge, "poser_frein_evolution", raising=False)
    v = fg.frein_si_recul(_cap(0.5))
    assert v["verdict"] == "RECUL" and v["frein"]["pose"] is False and "absent" in v["frein"]["pourquoi"]


def test_la_capture_d_une_generation_freine_et_le_consigne(gen):
    _stable(gen["dossier"], _cap(0.7647))
    g = fg.capturer(tests={"nr": "PASS"}, capacites=_cap(0.6), agent="NR", note="recul seme")
    assert g["frein_auto"]["verdict"] == "RECUL" and len(gen["freins"]) == 1
    ecrit = json.loads((gen["dossier"] / ("%s.json" % g["generation"])).read_text(encoding="utf-8"))
    assert ecrit["frein_auto"]["verdict"] == "RECUL"      # la trace vit AVEC la generation


def test_la_capture_sans_capacites_ne_juge_rien(gen):
    _stable(gen["dossier"], _cap(0.7647))
    g = fg.capturer(tests={"nr": "PASS"}, agent="NR")
    assert "frein_auto" not in g and gen["freins"] == []


# ── le lecteur des capacites mesurees ────────────────────────────────────────────────
def test_source_absente_tout_est_inconnu(monkeypatch):
    monkeypatch.delattr(fg, "capacites_mesurees", raising=False)
    r = fcb.capacites()
    assert r["source"] == fcb.INCONNU and r["capacites"] == {} and "absent" in r["raison"]
    assert fcb.capacite(DIM)["etat"] == fcb.INCONNU


def test_source_qui_leve_est_inconnue(monkeypatch):
    def _boum():
        raise OSError("sandbox/capacites illisible")
    monkeypatch.setattr(fg, "capacites_mesurees", _boum, raising=False)
    r = fcb.capacites()
    assert r["source"] == fcb.INCONNU and "OSError" in r["raison"]


@pytest.mark.parametrize("forme", ["dict", "liste", "enveloppe"])
def test_lecture_score_bruit_n_age(monkeypatch, forme):
    t = time.time()
    e = {"score": 0.7647, "bruit": 0.0588, "n": 17, "measured_at": t - 100}
    brut = {"dict": {DIM: e}, "liste": [dict(e, dimension=DIM)],
            "enveloppe": {"capacites": {DIM: e}}}[forme]
    monkeypatch.setattr(fg, "capacites_mesurees", lambda: brut, raising=False)
    c = fcb.capacite(DIM, maintenant=t)
    assert c == {"etat": fcb.CONNU, "score": 0.7647, "bruit": 0.0588, "n": 17, "age_s": 100.0}


def test_dimension_absente_ou_illisible_est_inconnue(monkeypatch):
    monkeypatch.setattr(fg, "capacites_mesurees",
                        lambda: {DIM: {"score": None}, "x": 0.5}, raising=False)
    assert fcb.capacite(DIM)["etat"] == fcb.INCONNU                     # illisible
    assert fcb.capacite("jamais_mesuree")["etat"] == fcb.INCONNU        # absente
    x = fcb.capacite("x")
    assert x["etat"] == fcb.CONNU and x["score"] == 0.5 and x["bruit"] is None
