"""NR -- RED6 free tier : le routeur ecarte un fournisseur en 429 PERSISTANT, pas sur un 429 isole.

Enquete AGY 19/10 (job_194ae927, M:lit INTEGREE) : `chaine_active` ecartait deja les morts DEFINITIFS (402/404/410,
TTL 7 j) via `injoignables_prouves`, mais un 429 n'avait aucune notion de persistance -- `consigner` ecrasait l'entree
sans compter. Cette nuit, OpenRouter/zai en 429 ont bloque trois executeurs 25 min chacun. Un 429 isole reste
jouable (fenetre de quota courte) ; persistant = au moins `_SEUIL_429` echecs consecutifs, mesure de moins de
`ttl_429_h` heures. Un succes remet le compteur a zero.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

import forge_free_tier_census as C  # noqa: E402
import forge_llm_router as R  # noqa: E402


def _r(joignable, motif="HTTP 429"):
    return {"fournisseur": "zai", "modele": "glm", "joignable": joignable, "motif": motif}


def test_les_echecs_consecutifs_se_comptent_et_un_succes_remet_a_zero():
    reg = C.consigner([_r(False)], {})
    assert reg["verdicts"]["zai:glm"]["echecs_consecutifs"] == 1
    reg = C.consigner([_r(False)], reg)
    reg = C.consigner([_r(False)], reg)
    assert reg["verdicts"]["zai:glm"]["echecs_consecutifs"] == 3
    reg = C.consigner([_r(True, "ok")], reg)
    assert reg["verdicts"]["zai:glm"]["echecs_consecutifs"] == 0


def _registre(tmp_path, **entrees):
    p = tmp_path / "census.json"
    p.write_text(json.dumps({"verdicts": entrees}), encoding="utf-8")
    return p


def _quand(il_y_a_h):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - il_y_a_h * 3600))


def test_un_429_persistant_et_recent_est_ecarte(tmp_path):
    p = _registre(tmp_path, **{
        "zai:glm": {"joignable": False, "motif": "HTTP 429", "echecs_consecutifs": 3, "mesure_le": _quand(1)},
        "or:isole": {"joignable": False, "motif": "HTTP 429", "echecs_consecutifs": 1, "mesure_le": _quand(1)},
        "or:vieux": {"joignable": False, "motif": "HTTP 429", "echecs_consecutifs": 5, "mesure_le": _quand(8)},
        "x:mort": {"joignable": False, "motif": "HTTP 402", "mesure_le": _quand(30)},
    })
    assert R.injoignables_prouves(p) == {"zai:glm", "x:mort"}


def test_un_429_sans_compteur_n_est_jamais_ecarte(tmp_path):
    """Liste blanche : un ancien registre sans compteur ne fabrique pas une persistance."""
    p = _registre(tmp_path, **{"zai:glm": {"joignable": False, "motif": "HTTP 429", "mesure_le": _quand(1)}})
    assert R.injoignables_prouves(p) == set()
