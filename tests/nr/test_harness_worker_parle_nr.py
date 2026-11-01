"""NR du 27/10 : le harness worker PARLE dans son journal.

Mesure : instance du 27/10 10 h 01 figee (vivante, muette) pendant 73 min ; journal logboot vide de
toute ligne du worker -- `--watch` n'emettait rien, ses exceptions partaient en logging.debug sans
handler, et faulthandler n'est arme que sur un crash natif, pas sur un blocage. Cause illisible.
Contrat : chaque job s'ouvre et se ferme par une ligne (agent, duree, ok), un echec s'ecrit en WARNING
avec sa trace, et un chien de garde faulthandler est arme pour la duree du job (timeout + marge).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

N = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(N / "tools"))
import forge_harness_worker as W  # noqa: E402


class _Journal:
    def __init__(self):
        self.lignes = []

    def info(self, msg, *a, **k):
        self.lignes.append(("INFO", msg % a))

    def warning(self, msg, *a, **k):
        self.lignes.append(("WARNING", msg % a))


def _poser_job(tmp_path, monkeypatch, process_job):
    jobs = tmp_path / "harness_jobs"
    jobs.mkdir()
    (jobs / "j1.json").write_text(json.dumps({"agent": "vibe", "timeout": 600}), encoding="utf-8")
    monkeypatch.setattr(W, "JOBS", jobs)
    monkeypatch.setattr(W, "process_job", process_job)
    monkeypatch.setattr(W, "_heartbeat", lambda **k: None)
    j = _Journal()
    monkeypatch.setattr(W, "_log", lambda: j)
    chiens = []
    monkeypatch.setattr(W, "_armer_chien", lambda s: chiens.append(s))
    return jobs, j, chiens


def test_un_job_s_ouvre_et_se_ferme_dans_le_journal(tmp_path, monkeypatch):
    jobs, j, chiens = _poser_job(tmp_path, monkeypatch, lambda job: {"ok": True})
    assert W._run_pending() == 1
    textes = " | ".join(t for _, t in j.lignes)
    assert "j1" in textes and "vibe" in textes and "demarre" in textes and "fini" in textes
    # chien de garde arme pour la duree du job : timeout + marge, jamais le delai de repos
    assert chiens and chiens[0] >= 600 + 60


def test_un_job_qui_leve_s_ecrit_en_warning(tmp_path, monkeypatch):
    def boum(job):
        raise RuntimeError("agent introuvable")
    jobs, j, chiens = _poser_job(tmp_path, monkeypatch, boum)
    W._run_pending()
    assert any(n == "WARNING" and "j1" in t for n, t in j.lignes)
    assert (jobs / "j1.result.json").is_file()


def test_le_chien_de_garde_reel_s_arme_et_se_desarme(tmp_path, monkeypatch):
    import faulthandler
    # 31/10 (CI) : le chien ecrivait le VRAI logs/harness_worker_faulthandler.log -- refuse au compte du bac
    # (PermissionError) et pollue l'arbre partage. Le fichier est redirige ; le mecanisme reel reste celui teste.
    monkeypatch.setattr(W, "_CHEMIN_CHIEN", tmp_path / "harness_worker_faulthandler.log")
    monkeypatch.setattr(W, "_FICHIER_CHIEN", None)
    W._armer_chien(3600)
    faulthandler.cancel_dump_traceback_later()  # ne rien laisser arme derriere le test
