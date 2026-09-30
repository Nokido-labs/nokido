"""NR -- un appel ALERTANT (gros ou lent) est compte : l'alerte ne peut plus emporter l'usage.

MESURE du 2026-09-25 (passerelle :7777, nokido/auto) : le journal de decision disait
« NON_COMPTE: OperationalError: no such table: network_log ». `log_call` insere l'usage dans
token_usage, puis -- si l'appel depasse un seuil (cout, latence, jetons) -- insere une alerte dans
`network_log`, table ABSENTE de la base de journal depuis la bascule du 2026-09-22
(sandbox/journal_token_usage.db). L'exception tombait AVANT le commit : l'usage partait avec la
transaction annulee. Ce sont les appels les PLUS GROS ou les PLUS LENTS -- les plus chers -- qui
n'etaient jamais comptes, pour TOUS les appelants de log_call.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_token_monitor as tm  # noqa: E402


def test_un_appel_alertant_est_compte_meme_sans_network_log(tmp_path, monkeypatch):
    base = tmp_path / "journal_token_usage.db"  # base NEUVE : pas de network_log, comme en prod
    monkeypatch.setattr(tm, "DB", base)
    tm.log_call(agent_id="NR", provider="mistral", model="mistral/codestral-latest",
                prompt_tokens=41010, completion_tokens=40,
                latency_ms=float(tm.ALERT_LATENCY_MS) * 10, source="nr_alertant")
    lignes = sqlite3.connect(base).execute(
        "select prompt_tokens, completion_tokens, source from token_usage").fetchall()
    assert lignes == [(41010, 40, "nr_alertant")], "usage d'un appel alertant PERDU"


def test_un_appel_ordinaire_reste_compte(tmp_path, monkeypatch):
    base = tmp_path / "journal_token_usage.db"
    monkeypatch.setattr(tm, "DB", base)
    tm.log_call(agent_id="NR", provider="mistral", model="m", prompt_tokens=79,
                completion_tokens=19, latency_ms=10.0, source="nr_ordinaire")
    assert sqlite3.connect(base).execute("select count(*) from token_usage").fetchone()[0] == 1
