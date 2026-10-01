"""NR : l'examen exteroceptif de la soif part A LA DEMANDE (owner 2026-09-30).

Mesure qui l'impose (30/09) : 22/22 cycles `BLOQUE_PAR_DEPENDANCE`, en ALTERNANCE
reranker / dense. La soif ne reclamait qu'UN pilier par cycle ; le keeper l'allumait,
puis l'eteignait « INUTILE » 15 min plus tard -- au moment ou le cycle suivant
reclamait l'autre. 1,4 a 3,2 Go reveilles toutes les 15 min pour ZERO examen.

Decision owner : l'examen (~4,6 Go de piliers) part sur SEUIL de besoin, a la MAIN
(`--examiner`) ou a ECHEANCE ; il reclame ses piliers ENSEMBLE ; sous pression RAM il
est DIFFERE sans rien allumer, donc sans rien que l'autoregulation doive couper.
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _demon():
    spec = importlib.util.spec_from_file_location(
        "demon_soif_examen", RACINE / "tools" / "forge_epistemic_daemon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def d(monkeypatch, tmp_path):
    """Le demon reel ; son sandbox/ (marque, demande) sous tmp_path, jamais le vrai."""
    mod = _demon()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "_journal", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_beat", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_interoceptive_split", lambda *a, **k: {"soif": [], "soin": []})
    monkeypatch.setattr(mod, "_intentional_split", lambda *a, **k: [])
    from nokido_agent.app import forge_active_inference as fai
    monkeypatch.setattr(fai, "observe_signal", lambda *a, **k: {})   # JAMAIS la vraie base
    return mod


def _base(*questions):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE query_log (query_text TEXT, timestamp REAL)")
    for i, q in enumerate(questions):
        conn.execute("INSERT INTO query_log VALUES (?, ?)", (q, i))
    return conn


def _toucher(p: Path, age_s: float = 0.0) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


def test_la_decision_suit_seuil_demande_et_echeance(d):
    assert d._decision_examen(0) == "aucun examen enregistre"
    _toucher(d._marque_dernier_examen())
    assert d._decision_examen(d.SEUIL_EXAMEN - 1) is None, "sous le seuil, on attend"
    assert d._decision_examen(d.SEUIL_EXAMEN).startswith("seuil")
    dem = _toucher(d._demande_manuelle())
    assert d._decision_examen(0) == "demande manuelle"
    _toucher(dem, d.DEMANDE_TTL_S + 60)
    assert d._decision_examen(0) is None, "une demande perimee ne declenche plus"
    _toucher(d._marque_dernier_examen(), d.EXAMEN_MAX_AGE_S + 60)
    assert d._decision_examen(0).startswith("echeance")


def test_sans_declencheur_aucun_pilier_n_est_reveille(d, monkeypatch):
    _toucher(d._marque_dernier_examen())
    appels = []
    monkeypatch.setattr(d, "_reveiller_piliers", lambda *a, **k: appels.append("reveil") or (True, ""))
    monkeypatch.setattr(d.ev, "coverage_dense", lambda q: appels.append(q) or {"ok": True})
    r = d.run_once(_base("une question assez longue"))
    assert appels == [], "un cycle sans declencheur a reveille ou examine : %r" % appels
    assert r["examen"].startswith("EN_ATTENTE")
    assert r["examinees"] == 0 and r["abstentions"] == {}


def test_les_piliers_de_l_examen_sont_reclames_ENSEMBLE(d, monkeypatch):
    """Le coeur du defaut du 30/09 : un pilier reclame a la fois = anti-phase."""
    from nokido_agent.app import forge_embed_router as fer
    poses = []
    monkeypatch.setattr(fer, "declare_wanted", lambda f, **k: poses.append(f) or True)

    class _Pret:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request as ur
    monkeypatch.setattr(ur, "urlopen", lambda *a, **k: _Pret())
    prets, detail = d._reveiller_piliers(attente_s=0)
    assert prets is True, detail
    assert sorted(poses) == ["embed.wanted", "rerank.wanted"], poses


def test_des_piliers_muets_se_nomment_et_rendent_False(d, monkeypatch):
    from nokido_agent.app import forge_embed_router as fer
    monkeypatch.setattr(fer, "declare_wanted", lambda f, **k: True)

    def _refus(*a, **k):
        raise OSError("connexion refusee")

    import urllib.request as ur
    monkeypatch.setattr(ur, "urlopen", _refus)
    prets, detail = d._reveiller_piliers(attente_s=0)
    assert prets is False
    assert "8099" in detail and "8100" in detail, detail


def test_sous_la_regulation_l_examen_est_DIFFERE_sans_rien_examiner(d, monkeypatch):
    vus = []
    monkeypatch.setattr(d, "_decision_examen", lambda besoin: "essai")
    monkeypatch.setattr(d, "_reveiller_piliers", lambda *a, **k: (False, "piliers muets apres 0 s"))
    monkeypatch.setattr(d.ev, "coverage_dense", lambda q: vus.append(q) or {"ok": True})
    r = d.run_once(_base("une question assez longue"))
    assert vus == []
    assert r["examen"].startswith("DIFFERE_PAR_REGULATION")
    # un report ne se lit ni comme un blocage ni comme un deblocage
    assert d._transition_blocage("reranker :8100", r) == ("reranker :8100", None)
    assert d._transition_blocage(None, r) == (None, None)


def test_un_examen_FAIT_marque_l_echeance_et_consomme_la_demande(d, monkeypatch):
    dem = _toucher(d._demande_manuelle())
    monkeypatch.setattr(d, "_reveiller_piliers", lambda *a, **k: (True, "prets"))
    monkeypatch.setattr(d.ev, "coverage_dense",
                        lambda q: {"ok": True, "gap": False, "verdict": "couvert", "score": 1.0})
    r = d.run_once(_base("une question assez longue"))
    assert r["examen"] == "FAIT (demande manuelle)"
    assert r["examinees"] == 1
    assert d._marque_dernier_examen().exists(), "l'echeance ne repart pas"
    assert not dem.exists(), "demande non consommee : elle redeclencherait a chaque cycle"


def test_le_drapeau_examiner_pose_la_demande_et_rend_la_main(d, monkeypatch):
    """Chemin REEL : le drapeau CLI traverse main(), sans lancer le demon."""
    monkeypatch.setattr(sys, "argv", ["forge_epistemic_daemon.py", "--examiner"])
    monkeypatch.setattr(d, "run", lambda *a, **k: pytest.fail("--examiner a lance le demon"))
    assert d.main() == 0
    assert d._demande_manuelle().exists()
    assert d._decision_examen(0) == "demande manuelle"
