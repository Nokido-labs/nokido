"""Câble évolution (P3) : ledger append-only + soumission au judge stubbé.

Hermétique : forge_mutation_judge est remplacé par un stub sys.modules —
aucun verrou pris, aucune mutation réelle, aucun test lancé par le judge.
"""
import json
import sys
import types
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.49)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


def _stub(monkeypatch, nom: str, mod):
    """Pose un stub sur TOUS les noms par lesquels le module peut etre atteint.

    DEFAUT MESURE le 2026-09-10. Ces tests patchaient `sys.modules["forge_mutation_judge"]`
    pendant que `forge_autonomous_loops` importe `nokido_agent.app.forge_mutation_judge` :
    deux entrees DIFFERENTES de `sys.modules`, donc AUCUNE prise. Le VRAI juge
    s'executait, et les quatre oracles de verdict lisaient `AWAITING_OWNER_COMMIT`
    a la place du verdict stubbe. La docstring de ce fichier promettait
    « hermetique, aucun test lance par le judge » — elle ne l'etait plus.

    ⚠️ Le `setattr` n'est pas une ceinture : `from nokido_agent.app import X` lit
    l'ATTRIBUT du paquet quand il existe deja, et l'attribut passe DEVANT
    `sys.modules`. Sans lui, la prise depend de l'ordre des tests.

    Zone MESUREE dans `app/forge_autonomous_loops.py` (L501, L3296), pas deduite.
    """
    monkeypatch.setitem(sys.modules, nom, mod)
    monkeypatch.setitem(sys.modules, f"nokido_agent.app.{nom}", mod)
    paquet = sys.modules.get("nokido_agent.app")
    if paquet is not None and hasattr(paquet, nom):
        monkeypatch.setattr(paquet, nom, mod)


def _loops(monkeypatch, tmp_path):
    import forge_autonomous_loops as loops
    monkeypatch.setattr(loops, "_EVOLUTION_DIR", tmp_path)
    monkeypatch.setattr(loops, "_EVOLUTION_LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(loops, "_EVOLUTION_CANDIDATES", tmp_path / "candidates")
    # legacy pointé vers un chemin inexistant : la migration ne doit pas polluer le test
    monkeypatch.setattr(loops, "_EVOLUTION_LEDGER_LEGACY", tmp_path / "_absent_legacy.jsonl")
    return loops


def test_record_append_only_et_genealogie(monkeypatch, tmp_path):
    loops = _loops(monkeypatch, tmp_path)
    e1 = loops.record_evolution_experience(
        {"kind": "regression_hypothesis", "status": "PENDING_CANDIDATE"})
    loops.record_evolution_experience(
        {"kind": "regression_hypothesis", "status": "PENDING_CANDIDATE", "n": 2})
    lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # append, jamais d'écrasement
    rec = json.loads(lines[0])
    assert rec["exp_id"] == e1 and len(e1) == 16
    assert rec["parent_commit"]  # présent même dégradé ("inconnu (...)")
    assert rec["ts"]


def test_submit_archive_integral_et_statue(monkeypatch, tmp_path):
    loops = _loops(monkeypatch, tmp_path)
    candidat = "def f():\n    return 42\n" * 200  # long : trahit toute troncature
    # CONTRAT FERME (raccordement du 2026-09-08, decision owner) : la boucle emprunte
    # `juger_module_avec_gain`, pas `juger_module` — SURVIT prouve la non-regression et
    # ne dit RIEN du gain, or on ne promeut que ce qui est PROUVE meilleur. Le stub
    # expose donc le chemin ferme, et le verdict promu est AMELIORE.
    # Ce que ce test protege reste INCHANGE : archivage INTEGRAL du candidat (aucune
    # troncature) et journalisation du couple verdict/status dans le ledger.
    stub = types.SimpleNamespace(
        evolution_autorisee=lambda: {"autorisee": True, "etat": "ARMEE", "motif": ""},  # chemin ARME
        juger_module_avec_gain=lambda rel, nouveau, tests=None: {
            "verdict": "AMELIORE", "etapes": ["stub"]},
        perimetre_mesure=lambda rel, racine=None, max_tests=8: [])
    _stub(monkeypatch, "forge_mutation_judge", stub)
    out = loops.submit_candidate_to_judge("exp0", "app/x.py", candidat, tests=["tests/t.py"])
    assert out["status"] == "AWAITING_OWNER_COMMIT"
    archived = list((tmp_path / "candidates").glob("*.py"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == candidat  # INTÉGRAL
    last = json.loads(
        (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert last["verdict"] == "AMELIORE" and last["status"] == "AWAITING_OWNER_COMMIT"
    assert last["ref_exp"] == "exp0" and last["target"] == "app/x.py"


def test_submit_survit_sans_gain_n_est_PAS_promu(monkeypatch, tmp_path):
    """SURVIT n'est pas AMELIORE : passer les tests sans gain mesure ne promeut RIEN.

    C'est le coeur du raccordement : avant, une mutation qui passait les tests ET
    degradait obtenait SURVIT et partait en AWAITING_OWNER_COMMIT.
    """
    loops = _loops(monkeypatch, tmp_path)
    stub = types.SimpleNamespace(
        evolution_autorisee=lambda: {"autorisee": True, "etat": "ARMEE", "motif": ""},  # chemin ARME
        juger_module_avec_gain=lambda rel, nouveau, tests=None: {"verdict": "SURVIT_SANS_GAIN"},
        perimetre_mesure=lambda rel, racine=None, max_tests=8: [])
    _stub(monkeypatch, "forge_mutation_judge", stub)
    out = loops.submit_candidate_to_judge("exp0", "app/x.py", "x = 1\n", tests=["tests/t.py"])
    assert out["status"] == "REJECTED"


def test_submit_gain_indecidable_designe_le_perimetre_manquant(monkeypatch, tmp_path):
    """Etat TERMINAL de la decision courante : ni promotion, ni echec — un manque NOMME."""
    loops = _loops(monkeypatch, tmp_path)
    stub = types.SimpleNamespace(
        evolution_autorisee=lambda: {"autorisee": True, "etat": "ARMEE", "motif": ""},  # chemin ARME
        juger_module_avec_gain=lambda rel, nouveau, tests=None: {"verdict": "GAIN_INDECIDABLE"},
        perimetre_mesure=lambda rel, racine=None, max_tests=8: [])
    _stub(monkeypatch, "forge_mutation_judge", stub)
    out = loops.submit_candidate_to_judge("exp0", "app/x.py", "x = 1\n")
    assert out["status"] == "PERIMETRE_MANQUANT"


def test_submit_verdict_inconnu_est_indecidable(monkeypatch, tmp_path):
    loops = _loops(monkeypatch, tmp_path)
    stub = types.SimpleNamespace(
        evolution_autorisee=lambda: {"autorisee": True, "etat": "ARMEE", "motif": ""},  # chemin ARME
        juger_module_avec_gain=lambda rel, nouveau, tests=None: {"panne": True},
        perimetre_mesure=lambda rel, racine=None, max_tests=8: [])
    _stub(monkeypatch, "forge_mutation_judge", stub)
    out = loops.submit_candidate_to_judge("exp0", "app/x.py", "def f():\n    pass\n")
    assert out["status"] == "INDECIDABLE"  # verdict absent != verdict favorable


def test_proposer_ouvre_une_experience(monkeypatch, tmp_path):
    loops = _loops(monkeypatch, tmp_path)
    stub_db = types.SimpleNamespace(write_retry=lambda corps: True)
    _stub(monkeypatch, "forge_db_path", stub_db)
    ok = loops._proposer("tick_sec", "60", "120", "raison mesurée", 0.9)
    assert ok is True
    last = json.loads(
        (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert last["kind"] == "parameter_proposal" and last["param"] == "tick_sec"
    assert last["status"] == "PENDING_CANDIDATE" and last["organ"] == "regulation"
