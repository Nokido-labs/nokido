# -*- coding: utf-8 -*-
"""NR -- owner 30/10 « ne perd pas le travail » : a 16:40:52 la regulation a endormi les 13 NokidoTaskExecutor* d'un
coup ; le census AGY en cours (job_3eb3feb2, 13 min de travail) est mort avec son executeur et a ete refait. CONTROL !=
OWNERSHIP : la regulation peut endormir un executeur oisif, pas un executeur dont l'agent a une tache EN VOL -- sauf
urgence vitale (la machine qui porte le travail passe avant). Tasks.db illisible = on ne sait pas : comportement d'avant."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402

TOML = '''
[[services]]
name = "NokidoTaskExecutorAntigravity"
args = ["x.py", "--agent", "ANTIGRAVITY"]
[[services]]
name = "NokidoTaskExecutorMistral"
args = ["x.py", "--agent", "MISTRAL"]
'''


def _monde(tmp_path, monkeypatch, en_vol=("ANTIGRAVITY",)):
    toml = tmp_path / "services.toml"
    toml.write_text(TOML, encoding="utf-8")
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT)")
    for i, ag in enumerate(en_vol):
        c.execute("INSERT INTO tasks VALUES (?, ?, 'running')", ("t%d" % i, ag))
    c.commit()
    c.close()
    monkeypatch.setattr(rm, "_SERVICES_TOML_REGUL", toml)
    monkeypatch.setattr(rm, "_TASKS_DB_REGUL", db)
    appels = []

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import urllib.request as _ur
    monkeypatch.setattr(_ur, "urlopen", lambda req, timeout=4: appels.append(req.full_url) or _R())
    monkeypatch.setattr(rm, "_retenir_evince", lambda s: None)
    return appels


def test_executeur_au_travail_n_est_pas_endormi(tmp_path, monkeypatch):
    appels = _monde(tmp_path, monkeypatch)
    monkeypatch.setattr(rm, "_ram_libre_gb", lambda: 8.0)
    ok, motif = rm._sleep_service_verdict("NokidoTaskExecutorAntigravity")
    assert ok is False and motif.startswith("TRAVAIL_EN_VOL")
    assert appels == []  # aucune requete au superviseur


def test_executeur_oisif_est_endormi(tmp_path, monkeypatch):
    appels = _monde(tmp_path, monkeypatch)
    monkeypatch.setattr(rm, "_ram_libre_gb", lambda: 8.0)
    ok, _ = rm._sleep_service_verdict("NokidoTaskExecutorMistral")
    assert ok is True and len(appels) == 1


def test_urgence_vitale_passe_outre(tmp_path, monkeypatch):
    appels = _monde(tmp_path, monkeypatch)
    monkeypatch.setattr(rm, "_ram_libre_gb", lambda: 0.1)
    ok, _ = rm._sleep_service_verdict("NokidoTaskExecutorAntigravity")
    assert ok is True and len(appels) == 1
