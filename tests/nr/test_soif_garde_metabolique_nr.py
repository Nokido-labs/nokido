# -*- coding: utf-8 -*-
"""NR (owner 3/11, « arbitre de saillance ») : la soif lit l'etat du corps AVANT d'agir.

Mesure du 3/11 : 4 pistes de veille lancees, Docker reveille, RAM a 86,9 %. La regulation existait en AVAL
(forge_chain_executor._ram_en_satiete retient la chaine), mais la soif comptait la piste comme lancee : budget du jour
et refractaire de 24 h consommes pour une piste qui ne pouvait pas partir (REQUESTED != ACHIEVED).
Sous tension : la piste ou l'enquete est DIFFEREE (DIFFERE_METABOLIQUE), rien n'est consomme, elle repart au cycle
suivant une fois la pression retombee. Un seul predicat de satiete pour tout le corps (pas de second seuil).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_epistemic_daemon as D  # noqa: E402

V = D.ev


@pytest.fixture
def lacune(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "LACUNES", tmp_path / "soif_lacunes.json")
    monkeypatch.setattr(V, "pistes_pour_lacune", lambda lac: ["theme de veille"])
    monkeypatch.setattr(V, "theme_autorise", lambda theme: (True, ""))
    V._ecrire_lacunes({"k": {"etat": sorted(V.ACTIVES)[0], "instrument": "coverage_dense", "question": "q",
                             "remesures_sans_effet": V.PISTES_SEUIL_STAGNATION, "historique": []}})
    return "k"


def _tension(monkeypatch, sous_tension):
    monkeypatch.setattr(V, "corps_sous_tension", lambda: (sous_tension, "ram 91 %" if sous_tension else "ram 60 %"))


def _evenements(cle):
    return [h.get("evenement") for h in V.lire_lacunes()[cle].get("historique") or ()]


def test_sous_tension_la_piste_est_differee_sans_rien_consommer(lacune, monkeypatch):
    _tension(monkeypatch, True)
    creees = []
    r = V.lancer_pistes(lacune, lambda theme: creees.append(theme) or "chain_x", maintenant=1e9)
    assert r["lancees"] == 0 and r.get("differe") == "DIFFERE_METABOLIQUE", r
    assert creees == []
    assert "pistes_lancees" not in _evenements(lacune)        # ni budget du jour ni refractaire consommes
    assert "pistes_differees" in _evenements(lacune)          # differer est DIT, pas un silence


def test_la_pression_retombee_la_piste_repart(lacune, monkeypatch):
    _tension(monkeypatch, True)
    V.lancer_pistes(lacune, lambda theme: "chain_x", maintenant=1e9)
    _tension(monkeypatch, False)
    creees = []
    r = V.lancer_pistes(lacune, lambda theme: creees.append(theme) or "chain_y", maintenant=1e9 + 60)
    assert r["lancees"] == 1 and creees == ["theme de veille"], r


def test_differer_a_chaque_cycle_ne_remplit_pas_l_historique(lacune, monkeypatch):
    _tension(monkeypatch, True)
    for i in range(5):
        V.lancer_pistes(lacune, lambda theme: "chain_x", maintenant=1e9 + i * 300)
    assert _evenements(lacune).count("pistes_differees") == 1


def test_le_predicat_est_celui_du_corps(monkeypatch):
    from nokido_agent.app import forge_chain_executor as CE

    monkeypatch.setattr(CE, "_ram_en_satiete", lambda: True)
    assert V.corps_sous_tension()[0] is True
    monkeypatch.setattr(CE, "_ram_en_satiete", lambda: False)
    assert V.corps_sous_tension()[0] is False


def test_l_enquete_de_code_est_differee_sous_tension(monkeypatch, tmp_path):
    etat = tmp_path / "enquete_code.json"
    monkeypatch.setattr(D, "_ENQUETE_CODE_ETAT", etat)
    monkeypatch.setattr(D, "_enquete_code_active", lambda: True)
    monkeypatch.setattr(D, "description_enquete_code", lambda *a: "desc")
    deposees = []
    monkeypatch.setattr(D, "_deposer_enquete_code", lambda desc: deposees.append(desc) or {"task_id": "t1"})
    _tension(monkeypatch, True)
    r = D._enquete_code_interne("cle", "question", ["x"], 0, maintenant=1e9)
    assert r["statut"] == "DIFFEREE" and r["motif"] == "DIFFERE_METABOLIQUE", r
    assert deposees == [] and not etat.exists()              # budget jour et doublon non consommes
    _tension(monkeypatch, False)
    r = D._enquete_code_interne("cle", "question", ["x"], 0, maintenant=1e9 + 60)
    assert r["statut"] == "DEPOSEE" and deposees == ["desc"], r
