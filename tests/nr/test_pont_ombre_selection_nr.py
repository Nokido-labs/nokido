"""NR 18/10 -- elargissement RSI n°2 (decision owner) : pont « ombre » A_TRAITER -> juge, etape 1 = le SELECTEUR.

Temoin C0 : 106 dossiers A_TRAITER, 0 parvenu au juge. Le pont choisit, une fois par nuit, LE dossier A_TRAITER le plus
recurrent (nombre d'entrees de triage qui le designent) et ne repropose JAMAIS un dossier deja soumis (entree
`ombre_soumis` ou `candidate_verdict` portant ce dossier) -- un candidat refuse n'est pas reessaye. Egalite -> le
dossier vu le plus tot. Rien d'eligible -> None.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_autonomous_loops as al  # noqa: E402


def _tri(dossier, verdict="A_TRAITER", ts="2026-10-15T10:00:00"):
    # traitement jugeable : depuis la liste blanche du pont (owner 18/10), seul MUTATION_CODE_JUGEE passe
    return {"kind": "triage", "dossier": dossier, "ts": ts, "organ": "regulation",
            "treatment": "MUTATION_CODE_JUGEE", "reexamen": {"verdict": verdict}}


def test_le_dossier_le_plus_recurrent_est_choisi():
    reg = [_tri("d1"), _tri("d2"), _tri("d2"), _tri("d3", "RESOLU"), _tri("d3", "RESOLU"), _tri("d3", "RESOLU")]
    s = al.selectionner_dossier_ombre(reg)
    assert s and s["dossier"] == "d2" and s["recurrence"] == 2, s


def test_un_dossier_deja_soumis_n_est_jamais_repropose():
    reg = [_tri("d1"), _tri("d2"), _tri("d2"), {"kind": "ombre_soumis", "dossier": "d2"}]
    assert al.selectionner_dossier_ombre(reg)["dossier"] == "d1"
    reg.append({"kind": "candidate_verdict", "dossier": "d1", "verdict": "SURVIT_SANS_GAIN"})
    assert al.selectionner_dossier_ombre(reg) is None


def test_seul_le_dernier_reexamen_compte():
    """Mesure du 18/10 : 510f1aa5307f avait 28 entrees A_TRAITER mais son DERNIER reexamen disait INDETERMINE."""
    reg = [_tri("d1", ts="2026-10-01T00:00:00"), _tri("d1", ts="2026-10-02T00:00:00"),
           _tri("d1", "INDETERMINE", ts="2026-10-03T00:00:00"), _tri("d2", ts="2026-10-01T00:00:00")]
    s = al.selectionner_dossier_ombre(reg)
    assert s and s["dossier"] == "d2", "d1 n'est plus A_TRAITER a son dernier reexamen : %s" % s


def test_egalite_premier_vu_et_rien_d_eligible():
    reg = [_tri("tard", ts="2026-10-16T00:00:00"), _tri("tot", ts="2026-10-14T00:00:00")]
    assert al.selectionner_dossier_ombre(reg)["dossier"] == "tot"
    assert al.selectionner_dossier_ombre([_tri("x", "RESOLU")]) is None
