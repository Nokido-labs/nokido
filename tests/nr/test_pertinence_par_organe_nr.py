"""NR : la pertinence d'un organe producteur se MESURE, et le bruit coupe son propre robinet (owner 26/10).

Owner : « l'ideal c'est de produire de la matiere pertinente, pas du bruit inutilisable ou a reprendre ». Chaque
candidat que l'owner tranche est consigne (decider_integration : INTEGREE tel quel, PARTIELLE = repris, REJETEE) ;
taux = integres tels quels / tranches. Sous SEUIL au-dela de N_MIN decisions : OBSERVATION -- le self-patcher
passe en simulation (aucun candidat ecrit).
"""
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "app"), str(_R / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_motivation as m  # noqa: E402


def _registre(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "RESULTATS", tmp_path / "reg.jsonl")
    monkeypatch.setenv("NOKIDO_MOTIVATION_SANS_CORPS", "1")


def _trancher(verdicts, repondeur="SELF_PATCHER"):
    for i, v in enumerate(verdicts):
        m.decider_integration("job_%08x_x" % i, repondeur, v, sha="s%d" % i)


def test_peu_de_decisions_insuffisant(monkeypatch, tmp_path):
    _registre(monkeypatch, tmp_path)
    _trancher(["REJETEE", "REJETEE"])
    assert m.taux_pertinence("SELF_PATCHER")["statut"] == "INSUFFISANT"


def test_bruit_majoritaire_passe_en_observation(monkeypatch, tmp_path):
    _registre(monkeypatch, tmp_path)
    _trancher(["INTEGREE", "PARTIELLE", "REJETEE", "REJETEE", "PARTIELLE", "REJETEE"])
    p = m.taux_pertinence("SELF_PATCHER")
    assert (p["n"], p["integrees"], p["reprises"], p["rejetees"]) == (6, 1, 2, 3)
    assert p["statut"] == "OBSERVATION" and p["taux"] < 0.5


def test_matiere_pertinente_reste_active(monkeypatch, tmp_path):
    _registre(monkeypatch, tmp_path)
    _trancher(["INTEGREE"] * 4 + ["PARTIELLE", "REJETEE"])
    assert m.taux_pertinence("SELF_PATCHER")["statut"] == "ACTIF"


def test_les_autres_organes_ne_comptent_pas(monkeypatch, tmp_path):
    _registre(monkeypatch, tmp_path)
    _trancher(["REJETEE"] * 6, repondeur="CLAUDE_HEADLESS")
    assert m.taux_pertinence("SELF_PATCHER")["n"] == 0


def test_le_self_patcher_en_observation_n_ecrit_aucun_candidat(monkeypatch, tmp_path):
    import forge_self_patcher as sp

    props = tmp_path / "props"
    props.mkdir()
    (props / "evolution_proposal_cible_x_1.md").write_text("- **x** : 1 < 2\n", encoding="utf-8")
    monkeypatch.setattr(sp, "PROPOSALS_DIR", props)
    monkeypatch.setattr(sp, "APPLIED_DIR", props / "patch_applied")
    monkeypatch.setattr(sp, "_rag_lookup", lambda pattern: "")
    monkeypatch.setattr(sp, "_llm_generate_patch", lambda *a, **k: None)
    monkeypatch.setattr(sp, "_pertinence", lambda: {"statut": "OBSERVATION", "taux": 0.2, "n": 6})
    stats = sp.run_once(dry_run=False)
    assert stats.get("mode") == "OBSERVATION"
    assert list((props / "patch_applied").glob("*.md")) == []  # simulation : rien consomme
