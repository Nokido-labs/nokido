"""NR : basetemp partage entre ci_local concurrents (bug 22/10, 16 892 erreurs FileExists).

Item P1 bug_ci_local_basetemp_partage_entre_runs_concurrents_20261022 : un run hors mode preuve qui trouve le basetemp
tenu par un ci_local VIVANT prend un basetemp propre (meme dossier, suffixe court) ; pid mort prouve = verrou et
basetemps orphelins nettoyes, chemin habituel repris ; le mode preuve (execution_id) n'est pas touche.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import ci_local  # noqa: E402


def _poser(base, pid):
    base.parent.mkdir(parents=True, exist_ok=True)
    (base.parent / (base.name + ".lock")).write_text(json.dumps({"pid": pid, "ctime": 1.0}))


def test_verrou_tenu_par_pid_vivant_donne_basetemp_distinct(tmp_path, monkeypatch):
    monkeypatch.delenv("NOKIDO_EXECUTION_ID", raising=False)
    base = tmp_path / "ci_x" / "bt"
    _poser(base, 999999)
    r = ci_local.basetemp_exclusif(base, pid_vivant=lambda p, c: True)
    assert r != base and r.parent == base.parent and len(r.name) <= len(base.name) + 14


def test_pid_mort_reprise_chemin_habituel_et_nettoyage(tmp_path, monkeypatch):
    monkeypatch.delenv("NOKIDO_EXECUTION_ID", raising=False)
    base = tmp_path / "ci_x" / "bt"
    _poser(base, 999999)
    orphelin = base.parent / "bt_1_0"
    orphelin.mkdir()
    _poser(orphelin, 999998)
    r = ci_local.basetemp_exclusif(base, pid_vivant=lambda p, c: False)
    assert r == base
    assert not orphelin.exists()


def test_mode_preuve_inchange(tmp_path):
    base = tmp_path / "ci_x" / "bt"
    _poser(base, 999999)
    assert ci_local.basetemp_exclusif(base, execution_id="e1", pid_vivant=lambda p, c: True) == base
