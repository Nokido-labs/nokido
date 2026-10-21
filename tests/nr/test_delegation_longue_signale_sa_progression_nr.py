"""NR -- une delegation longue SIGNALE sa progression : reclaim_expired ne la reprend pas en plein vol (17/10).

Mesure 17/10 : touch_progress(task_id) est DEFINI mais appele par PERSONNE (git grep : seule sa definition) ;
reclaim_expired (boucle, ligne ~2117) rend `pending` toute tache en vol sans progression depuis _LEASE_TIMEOUT_S = 1 800 s.
Une delegation plus longue (CODEX_TIMEOUT_S = 2 400 s ; Vibe jusqu'a VIBE_TIMEOUT_S + 180) serait donc REPRISE en plein
vol -> double execution. Inverse, voulu et garde : une tache vraiment orpheline (executeur relance, mesure 17/10 :
pid ne a 14:40:51 apres une delegation de 14:35:29) reste reprise, puisque plus personne ne bat pour elle.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as E  # noqa: E402


def test_l_attente_du_harness_bat_pour_sa_tache(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_POLL_HARNESS_S", 0.05)
    monkeypatch.setattr(E, "_PROGRES_TOUTES_S", 0.1)
    vus = []
    monkeypatch.setattr(E, "touch_progress", lambda tid, checkpoint="": vus.append(tid))
    job = tmp_path / "vibe_t.json"
    job.write_text("{}", encoding="utf-8")
    job.with_suffix(".started").write_text("1", encoding="utf-8")

    def _finir():
        time.sleep(0.5)
        job.with_suffix(".result.json").write_text('{"ok": true}', encoding="utf-8")
        job.with_suffix(".done").write_text("1", encoding="utf-8")

    threading.Thread(target=_finir, daemon=True).start()
    assert E._attendre_harness(job, 5, attente_file_s=5, task_id="t-long") == {"ok": True}
    assert vus.count("t-long") >= 2, "une attente de 0,5 s avec un battement toutes les 0,1 s doit battre : %s" % vus


def test_sans_tache_l_attente_ne_bat_pour_personne(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_POLL_HARNESS_S", 0.05)
    monkeypatch.setattr(E, "_PROGRES_TOUTES_S", 0.1)
    vus = []
    monkeypatch.setattr(E, "touch_progress", lambda tid, checkpoint="": vus.append(tid))
    job = tmp_path / "vibe_u.json"
    job.write_text("{}", encoding="utf-8")
    job.with_suffix(".started").write_text("1", encoding="utf-8")
    assert E._attendre_harness(job, 0.3, attente_file_s=5) is None
    assert vus == []


def test_les_delegations_passent_leur_tache_a_l_attente():
    """Les deux appelants de _attendre_harness (Vibe, Codex) lui passent task_id : sinon personne ne bat."""
    src = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8", errors="replace")
    appels = [l.strip() for l in src.splitlines() if "_attendre_harness(job" in l and "def " not in l]
    assert len(appels) >= 2, appels
    assert all("task_id=" in a for a in appels), appels
