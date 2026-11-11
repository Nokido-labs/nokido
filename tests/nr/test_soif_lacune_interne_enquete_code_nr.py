# -*- coding: utf-8 -*-
"""NR (owner 3/11 « traite ce qui reste » (3)) : les 19 lacunes de couverture OUVERTES ont des questions INTERNES
(textes de roadmap). Elles ont ete ouvertes du 6 au 18/10, AVANT l'armement de l'enquete de code (26/10) : le demon
ne depose l'enquete qu'a la PREMIERE detection (`elif not _recent`), donc jamais pour elles ; et une veille web sur
ces textes = bruit (4 veilles annulees le 3/11). Contrat : une lacune de couverture INTERNE (`_manque_interne`, le
critere existant) qui STAGNE prend l'enquete de code existante, une seule fois ; une demande explicite de savoir
exterieur garde les pistes de veille ; une lacune qui ne stagne pas attend.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

import forge_epistemic_daemon as D  # noqa: E402


@pytest.fixture
def espions(monkeypatch, tmp_path):
    appels = {"enquete": [], "pistes": []}
    monkeypatch.setattr(D, "_ENQUETE_CODE_ETAT", tmp_path / "enquete_code.json")
    monkeypatch.setattr(D, "_enquete_code_interne",
                        lambda cle, q, internes, deja, maintenant=None: appels["enquete"].append(cle)
                        or {"statut": "DEPOSEE", "task_id": "t1"})
    monkeypatch.setattr(D.ev, "lancer_pistes",
                        lambda cle, creer=None, maintenant=None: appels["pistes"].append(cle) or {"lancees": 0})
    return appels


def _lac(q, stagne=True):
    return {"etat": "OUVERTE", "instrument": "coverage_dense|floor=-5.0|ceil=1.0", "question": q,
            "remesures_sans_effet": D.ev.PISTES_SEUIL_STAGNATION if stagne else 0}


Q_INTERNE = "Nokido P1 : [OUVERT 2026-10-21] ATLAS DES DONNEES (proposition owner 21/10, etudiee contre l'existant)"
Q_EXTERNE = "etat de l'art des index hybrides BM25 et vecteurs denses"


def test_lacune_interne_stagnante_prend_l_enquete_de_code(espions):
    r = D._traiter_lacune_stagnante("a", _lac(Q_INTERNE), 1e9, 0)
    assert r["voie"] == "enquete_code" and espions["enquete"] == ["a"] and espions["pistes"] == [], r


def test_demande_exterieure_garde_les_pistes(espions):
    r = D._traiter_lacune_stagnante("b", _lac(Q_EXTERNE), 1e9, 0)
    assert r["voie"] == "pistes" and espions["pistes"] == ["b"] and espions["enquete"] == [], r


def test_une_seule_enquete_par_lacune(espions, tmp_path):
    (tmp_path / "enquete_code.json").write_text(json.dumps({"cles": {"a": {"task_id": "t0"}}, "jours": {}}),
                                                encoding="utf-8")
    r = D._traiter_lacune_stagnante("a", _lac(Q_INTERNE), 1e9, 0)
    assert r.get("statut") == "DEJA_DEPOSEE" and espions["enquete"] == [], r


def test_lacune_qui_ne_stagne_pas_attend(espions):
    r = D._traiter_lacune_stagnante("c", _lac(Q_INTERNE, stagne=False), 1e9, 0)
    assert r["voie"] == "attente" and espions["enquete"] == [] and espions["pistes"] == [], r


def test_la_boucle_de_remesure_passe_par_la_decision():
    src = (ROOT / "tools" / "forge_epistemic_daemon.py").read_text(encoding="utf-8")
    i = src.find("def _remesurer_lacunes")
    assert "_traiter_lacune_stagnante(" in src[i:src.find("\ndef ", i + 5)]
