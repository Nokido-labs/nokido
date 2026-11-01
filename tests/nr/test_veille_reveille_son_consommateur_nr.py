# -*- coding: utf-8 -*-
"""NR (28/10) : creer une veille REVEILLE son consommateur (NokidoWatchAgent, service on-demand).

Mesure 28/10 13:58 : 6 veilles creees restaient `pending keywords` -- NokidoWatchAgent absent du superviseur
depuis le redemarrage complet de 12:55 ; create_job() ecrivait les chaines et ne reveillait personne (la skill
demandait de le faire a la main). Meme classe que les executeurs endormis du matin : du travail attend, rien ne
reveille celui qui doit le faire. Le reveil ne bloque jamais la creation, et ne touche jamais le VRAI superviseur
sous pytest."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_watch_agent as wa  # noqa: E402


def test_create_job_reveille_le_consommateur(monkeypatch):
    import nokido_agent.app.forge_db_path as dbp
    monkeypatch.setattr(dbp, "write_retry", lambda tx: None)
    appels = []
    monkeypatch.setattr(wa, "_reveiller_consommateur", lambda: appels.append(1) or "DEMANDE")
    cid = wa.create_job(theme="t", idea_id="veille_active", agent="TEST")
    assert cid.startswith("wj_") and appels == [1]


def test_un_echec_de_reveil_ne_bloque_pas_la_creation(monkeypatch):
    import nokido_agent.app.forge_db_path as dbp
    monkeypatch.setattr(dbp, "write_retry", lambda tx: None)

    def boom():
        raise OSError("superviseur injoignable")

    monkeypatch.setattr(wa, "_reveiller_consommateur", boom)
    assert wa.create_job(theme="t", idea_id="veille_active", agent="TEST").startswith("wj_")


def test_sous_pytest_le_vrai_superviseur_n_est_pas_appele(monkeypatch):
    import urllib.request

    def interdit(*a, **k):
        raise AssertionError("le vrai superviseur a ete appele depuis un test")

    monkeypatch.setattr(urllib.request, "urlopen", interdit)
    assert wa._reveiller_consommateur() == "SAUTE_SOUS_TEST"
