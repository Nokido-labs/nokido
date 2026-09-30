"""Le faucheur d'orphelins doit se RETENIR — mesure du 2026-08-29.

`forge_regulation_efficacy` a rendu `kill/ram` : **POMPE**, 3,7 tirs/h pour un
budget de 2,0, trois recidives. Le budget existait pourtant
(`forge_regulation_loops.SEVERITY_BUDGET_PER_HOUR`) mais n'avait AUCUN consommateur
cote effecteur : il servait a constater apres coup, jamais a empecher.

Le faucheur, lui, avait recu une CADENCE (forge_homeostasis_orchestrator l'appelle
a chaque tick) sans recevoir de FREIN. Il moissonnait des qu'il voyait des
candidats. Ces tests verrouillent le frein, et surtout sa partie non negociable :
l'absolue ne se franchit pas, meme a urgence maximale — sans quoi la tetanie.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_orphan_reaper as reaper  # noqa: E402


def _candidats(monkeypatch, n=2):
    monkeypatch.setattr(reaper, "survey", lambda: {
        "ok": True,
        "candidates": [{"pid": 999000 + i, "why": "test", "rss_gb": 0.1}
                       for i in range(n)]})


def test_urgence_bornee_par_les_consignes_ram():
    """0 sous la consigne basse, 1 au-dela de la haute, lineaire entre les deux."""
    assert reaper._urgence_ram(reaper._RAM_BAS - 10) == 0.0
    assert reaper._urgence_ram(reaper._RAM_HAUT + 10) == 1.0
    milieu = reaper._urgence_ram((reaper._RAM_BAS + reaper._RAM_HAUT) / 2)
    assert 0.4 < milieu < 0.6


def test_un_tir_recent_est_REFUSE(monkeypatch, tmp_path):
    """Le coeur du correctif : venir de tirer interdit de retirer."""
    _candidats(monkeypatch)
    monkeypatch.setattr(reaper, "_REAP_ETAT", tmp_path / "etat.json")
    monkeypatch.setattr(reaper, "_dernier_tir", lambda: __import__("time").time() - 5)
    vus = []
    monkeypatch.setattr(reaper, "_audit", lambda a, r, **k: vus.append(a))

    res = reaper.run_cycle(kill=True)
    assert res["reaped"] == [], "le faucheur a tue malgre la refractaire"
    assert res.get("refractaire"), "refus non motive"
    assert "kill_skipped" in vus, "une abstention doit se journaliser comme telle"


def test_l_absolue_ne_se_franchit_PAS_meme_a_urgence_maximale(monkeypatch, tmp_path):
    """La refractaire ABSOLUE couvre le contrecoup du remede : elle est
    infranchissable, urgence maximale comprise. Sinon, tetanie."""
    _candidats(monkeypatch)
    monkeypatch.setattr(reaper, "_REAP_ETAT", tmp_path / "etat.json")
    monkeypatch.setattr(reaper, "_dernier_tir", lambda: __import__("time").time() - 5)
    monkeypatch.setattr(reaper, "_urgence_ram", lambda pct: 1.0)
    monkeypatch.setattr(reaper, "_audit", lambda *a, **k: None)

    res = reaper.run_cycle(kill=True)
    assert res["reaped"] == [], "urgence maximale a franchi l'absolue"


def test_abstention_journalisee_distinctement_d_un_tir(monkeypatch, tmp_path):
    """« Une abstention n'est pas un acte » : la compter comme un tir ferait crier
    au pompage un corps qui se retient exactement comme il faut."""
    _candidats(monkeypatch)
    monkeypatch.setattr(reaper, "_REAP_ETAT", tmp_path / "etat.json")
    monkeypatch.setattr(reaper, "_dernier_tir", lambda: __import__("time").time() - 1)
    actions = []
    monkeypatch.setattr(reaper, "_audit", lambda a, r, **k: actions.append(a))

    reaper.run_cycle(kill=True)
    assert actions and all(a != "kill" for a in actions)
    assert actions[0].endswith("_skipped")


def test_sans_candidat_aucun_verdict_n_est_rendu(monkeypatch):
    """Rien a faucher : on ne consomme pas la refractaire pour rien."""
    monkeypatch.setattr(reaper, "survey", lambda: {"ok": True, "candidates": []})
    res = reaper.run_cycle(kill=True)
    assert res.get("refractaire") is None


def test_la_refractaire_est_persistee_pas_en_memoire():
    """Un cooldown garde en memoire disparait au respawn du regulateur -- et c'est
    PRECISEMENT pendant une crise qu'il respawne."""
    assert str(reaper._REAP_ETAT).endswith(".json")
    assert reaper._REAP_ABSOLUE_S >= 1800, (
        "budget critical = 2 tirs/h : l'absolue ne peut pas descendre sous 1800 s")
