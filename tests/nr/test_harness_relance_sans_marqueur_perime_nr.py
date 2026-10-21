"""NR -- une tache RE-deleguee au harness s'execute vraiment, elle ne relit pas le resultat de l'essai precedent.

Mesure 19/10 (job_8d8c674e, MISTRAL) : le premier essai Vibe ecrit `vibe_<tache>.done` + `.result.json` a 21:46 ;
l'executeur est relance avant de le consommer ; a la reprise du bail (22:16:33.113) la meme tache re-ecrit
`vibe_<tache>.json` sous le MEME nom, `_attendre_harness` trouve le `.done` perime et rend en 0,5 s l'ancien resultat
(« KO, AUCUN EFFET ») -- et le worker, voyant le marqueur, ne lance meme pas le job. Vibe n'a jamais retourne.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as E  # noqa: E402


def _essai_precedent(tmp_path):
    job = tmp_path / "vibe_job_x.json"
    job.write_text("{}", encoding="utf-8")
    job.with_suffix(".started").write_text("1", encoding="utf-8")
    job.with_suffix(".result.json").write_text(json.dumps({"ok": True, "output": "ANCIEN"}), encoding="utf-8")
    job.with_suffix(".done").write_text("1", encoding="utf-8")
    return job


def test_purger_retire_les_marqueurs_de_l_essai_precedent(tmp_path):
    job = _essai_precedent(tmp_path)
    E._purger_marqueurs_harness(job)
    for suffixe in (".done", ".started", ".result.json"):
        assert not job.with_suffix(suffixe).exists(), suffixe


def test_purger_sans_marqueur_ne_leve_pas(tmp_path):
    E._purger_marqueurs_harness(tmp_path / "vibe_job_neuf.json")


def test_apres_purge_l_attente_ne_rend_plus_l_ancien_resultat(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_POLL_HARNESS_S", 0.01)
    job = _essai_precedent(tmp_path)
    E._purger_marqueurs_harness(job)
    res = E._attendre_harness(job, delai_s=0.1, attente_file_s=0.1)
    assert not (isinstance(res, dict) and res.get("output") == "ANCIEN")


def test_les_deux_delegations_purgent_avant_d_ecrire_le_job():
    for fonction in (E._delegate_to_vibe, E._delegate_to_codex):
        source = inspect.getsource(fonction)
        assert "_purger_marqueurs_harness(job)" in source, fonction.__name__
        assert source.index("_purger_marqueurs_harness(job)") < source.index("job.write_text("), fonction.__name__
