"""NR -- un quota JOURNALIER epuise arrete le banc et le DIT (mesure du 15/10, banc 164).

groq `openai/gpt-oss-120b` a epuise ses 200 000 jetons/jour a la tache 98 ; le runner a continue ~60 taches x 14 s de
`llm_error` certaines, par bras. Un 429 de DEBIT (par minute) se resorbe : il ne doit pas arreter le run."""
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_humaneval_runner as he  # noqa: E402

JOUR = ("[ERR] RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model "
        "`openai/gpt-oss-120b` in organization `org_x` service tier `on_demand` on tokens per day (TPD): Limit 200000")
MINUTE = ("[ERR] RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `m` on "
          "tokens per minute (TPM): Limit 8000")


def test_detection_du_quota_journalier():
    assert he._quota_journalier(JOUR) is True
    assert he._quota_journalier(MINUTE) is False
    assert he._quota_journalier("[ERR] ConnectionError: timeout") is False
    assert he._quota_journalier("") is False


def _banc(monkeypatch, tmp_path, reponse):
    entrees = [{"task_id": "HumanEval/%d" % i, "prompt": "def f%d():\n    pass\n" % i, "test": "",
                "entry_point": "f%d" % i, "canonical_solution": ""} for i in range(3)]
    monkeypatch.setattr(he, "ensure_dataset", lambda: entrees)
    monkeypatch.setattr(he, "call_llm", lambda prompt, provider: reponse)
    monkeypatch.setattr(he, "_autotest_quarantine", lambda: set())
    monkeypatch.setattr(he, "_run_identity", lambda q, e: {})
    monkeypatch.setattr(he, "HE_DIR", tmp_path)
    monkeypatch.setattr(he.time, "sleep", lambda s: None)
    return he.run(provider="groq", max_entries=3)


def test_un_quota_journalier_arrete_le_run_et_compte_les_non_joues(monkeypatch, tmp_path):
    s = _banc(monkeypatch, tmp_path, JOUR)
    assert len(s["results"]) == 1 and s["non_joues"] == 2
    assert "tokens per day" in s["arret_quota"]
    assert s["results"][0]["reason"] == "llm_error"


def test_un_429_par_minute_n_arrete_pas_le_run(monkeypatch, tmp_path):
    s = _banc(monkeypatch, tmp_path, MINUTE)
    assert len(s["results"]) == 3 and s["non_joues"] == 0 and s["arret_quota"] is None
