"""NR -- l'executeur ne delegue plus a Vibe / claude -p par le harness quand le harness worker est mort.

Mesure 27/10 (logs/supervisor/NokidoTaskExecutorMistral.log) : NokidoHarnessWorker mort a 03 h 04 (pouls fige), relance
impossible par le superviseur (WTSQueryUserToken : session owner illisible la nuit) ; chaque delegation VIBE attendait
~28 min un harness muet, puis le conseiller relancait UNE fois (28 min de plus) -> 8 taches, ~8 h perdues, 0 livraison.
Trois etats : vivant (pouls frais), MORT (pouls perime), ILLISIBLE (absent ou corrompu) -- jamais confondus.
"""
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as te  # noqa: E402


def _pouls(tmp_path, monkeypatch, age_s=None, contenu=None):
    monkeypatch.delenv("LAFORGE_HARNESS_POULS_IGNORE", raising=False)  # ce test eprouve la VRAIE fonction
    hb = tmp_path / "harness_worker.heartbeat"
    if contenu is not None:
        hb.write_text(contenu, encoding="utf-8")
    elif age_s is not None:
        ts = (datetime.datetime.now() - datetime.timedelta(seconds=age_s)).isoformat(timespec="seconds")
        hb.write_text(json.dumps({"ts": ts, "pid": 1}), encoding="utf-8")
    monkeypatch.setattr(te, "_HARNESS_HEARTBEAT", hb)


def test_pouls_frais_vivant(tmp_path, monkeypatch):
    _pouls(tmp_path, monkeypatch, age_s=5)
    assert te._harness_vivant()[0] is True


def test_pouls_perime_mort(tmp_path, monkeypatch):
    _pouls(tmp_path, monkeypatch, age_s=6 * 3600)
    etat, motif = te._harness_vivant()
    assert etat is False and "perime" in motif


def test_pouls_absent_ou_corrompu_illisible(tmp_path, monkeypatch):
    _pouls(tmp_path, monkeypatch)
    assert te._harness_vivant()[0] is None
    _pouls(tmp_path, monkeypatch, contenu="{pas du json")
    assert te._harness_vivant()[0] is None
