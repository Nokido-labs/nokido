"""NR -- un juge de CODE muet ne rend jamais un score moyen (decision owner 16/10 ; UNKNOWN != 0,5).

app/forge_scorecard.py est un module JUGE protege par la separation des pouvoirs (refus a Claude, 16/10) : RED ecrit
par Claude, code par un autre agent. RED observe le 16/10 : _llm_judge -> (0.5, 'judge error (...) - neutral
fallback') ; evaluate_code -> TypeError '<' entre None et float des que _llm_judge rend None.
"""
from nokido_agent.app import forge_scorecard as S


def test_un_juge_de_code_injoignable_ne_rend_pas_un_score_moyen(tmp_path, monkeypatch):
    import urllib.request

    f = tmp_path / "x.py"
    f.write_text("x = 1\n", encoding="utf-8")

    def _injoignable(*a, **k):
        raise OSError("ollama injoignable")

    monkeypatch.setattr(urllib.request, "urlopen", _injoignable)
    score, raison = S._llm_judge(str(f), "tache", "laforge-qwen", 1, "http://127.0.0.1:9")
    assert score is None, (score, raison)


def test_evaluate_code_et_patch_disent_non_note_quand_le_juge_se_tait(tmp_path, monkeypatch):
    f = tmp_path / "x.py"
    f.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(S, "_run_quality_gate", lambda p: (1.0, "ok"))
    monkeypatch.setattr(S, "_llm_judge", lambda *a, **k: (None, "juge injoignable"))
    grades = (S.evaluate_code(str(f), "tache").grade, S.evaluate_patch(str(f), "tache").grade)
    assert grades == (S.QualityGrade.UNRATED, S.QualityGrade.UNRATED)
