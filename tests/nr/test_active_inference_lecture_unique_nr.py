# -*- coding: utf-8 -*-
"""NR (audit pair 19/10, analyse B, verifie par Mistral job_883c47e4 puis sur piece) : une observation ne relit plus
deux fois le meme etat.

Mesure : observe_signal (L116) appelait predict_signal (L83) puis signal_z (L104), qui RAPPELAIT predict_signal --
deux connexions SQLite et deux preparations de schema pour lire le meme etat, avant la troisieme (ecriture). signal_z
accepte desormais la prediction deja lue ; le resultat numerique est IDENTIQUE (meme mean/std, meme seuil de maturite).
"""
from nokido_agent.app import forge_active_inference as A


def _pred(n=12, mean=2.0, std=0.5):
    return {"n": n, "mean": mean, "std": std, "mature": n >= A.SIGNAL_MIN_OBS}


def test_signal_z_avec_prediction_fournie_ne_relit_pas(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("predict_signal ne doit pas etre rappele")
    monkeypatch.setattr(A, "predict_signal", interdit)
    z = A.signal_z("s", "c", 3.0, pred=_pred())
    assert z == (3.0 - 2.0) / max(0.5, A.SIGNAL_STD_FLOOR)
    assert A.signal_z("s", "c", 3.0, pred=_pred(n=0)) is None   # immature : None, jamais zero


def test_observe_signal_ne_lit_l_etat_qu_une_fois(monkeypatch):
    appels = []
    monkeypatch.setattr(A, "predict_signal", lambda s, c: appels.append(1) or _pred())
    import nokido_agent.app.forge_db_path as D
    monkeypatch.setattr(D, "write_retry", lambda op: None)
    r = A.observe_signal("s", "c", 3.0)
    assert appels == [1]
    assert r["z"] == round((3.0 - 2.0) / max(0.5, A.SIGNAL_STD_FLOOR), 3)


def test_sans_prediction_fournie_le_comportement_d_avant_tient(monkeypatch):
    monkeypatch.setattr(A, "predict_signal", lambda s, c: _pred())
    assert A.signal_z("s", "c", 3.0) == (3.0 - 2.0) / max(0.5, A.SIGNAL_STD_FLOOR)
