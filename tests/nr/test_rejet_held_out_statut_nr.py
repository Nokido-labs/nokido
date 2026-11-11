# -*- coding: utf-8 -*-
"""NR (owner 4/11, choix « ensemble mis de cote » apres lecture des sources RSI) : le jeu held-out existe et est branche
(juger_module_avec_gain -> REJETE_HELD_OUT), mais submit_candidate_to_judge ne connaissait pas ce verdict dans sa liste
de statuts : un rejet PROUVE par le jeu jamais vu etait enregistre « INDECIDABLE » -- un NON lu comme INCONNU. Lecon
des sources (revue 2610.27610 : RRSI, R2Flow) : le rejet held-out est le garde-fou central, il doit se lire REJECTED."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.app import forge_autonomous_loops as L  # noqa: E402
from nokido_agent.app import forge_mutation_judge as J  # noqa: E402


def _soumettre(monkeypatch, tmp_path, verdict):
    monkeypatch.setattr(J, "evolution_autorisee", lambda *a, **k: {"autorisee": True, "etat": "ARME", "motif": "test"})
    monkeypatch.setattr(J, "juger_module_avec_gain", lambda rel, nouveau, tests: {"verdict": verdict})
    monkeypatch.setattr(L, "_EVOLUTION_CANDIDATES", tmp_path / "cand")
    enregistre = []
    monkeypatch.setattr(L, "record_evolution_experience", lambda d: enregistre.append(d) or "exp_1")
    out = L.submit_candidate_to_judge("ref", "app/forge_x.py", "x = 1\n", ["tests/nr/test_x_nr.py"])
    return out, enregistre


def test_un_rejet_held_out_est_rejected(monkeypatch, tmp_path):
    out, enr = _soumettre(monkeypatch, tmp_path, "REJETE_HELD_OUT")
    assert out["status"] == "REJECTED" and enr[-1]["status"] == "REJECTED"


def test_les_autres_statuts_inchanges(monkeypatch, tmp_path):
    assert _soumettre(monkeypatch, tmp_path, "AMELIORE")[0]["status"] == "AWAITING_OWNER_COMMIT"
    assert _soumettre(monkeypatch, tmp_path, "SURVIT_SANS_GAIN")[0]["status"] == "REJECTED"
    assert _soumettre(monkeypatch, tmp_path, "VERDICT_INCONNU")[0]["status"] == "INDECIDABLE"
