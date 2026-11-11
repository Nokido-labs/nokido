"""NR -- le moniteur --hub-restart ne declare plus NON_RELANCE un hub relance (10/11 soir).

Mesure : ordre-b87fe6c9ee00 ATTEINT (boot pid 22648, journal ordres_bureau.jsonl), moniteur :
« HUB NON_RELANCE en 200s ... (None) ». Le hub tourne sous un autre compte : psutil voit le LISTEN sans pid,
`_ecouteur_hub` rendait None (« personne ») -- UNKNOWN lu comme NO. Contrats :
  1. LISTEN sur le port sans pid lisible -> "ILLISIBLE", jamais None ;
  2. evenement `atteint` d'un ordre restart(-hub) au journal, boot recent, /health sain -> HUB RELANCE (rc 0) ;
  3. un `atteint` ANCIEN (boot avant la fenetre) ne prouve rien -> pas de RELANCE sur sa foi.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_job_watch_cli as C  # noqa: E402


def test_listen_sans_pid_est_illisible(monkeypatch):
    import psutil

    c = SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=8766), pid=None)
    monkeypatch.setattr(psutil, "net_connections", lambda kind="tcp": [c])
    assert C._ecouteur_hub(8766) == "ILLISIBLE"


def _journal(tmp_path, boot_ts):
    j = tmp_path / "ordres_bureau.jsonl"
    j.write_text(json.dumps({"id": "ordre-x", "action": "restart-hub", "evenement": "atteint",
                             "preuve": {"boot_hub_ts": boot_ts, "pid": 22648}}) + "\n", encoding="utf-8")
    return j


def test_atteint_au_journal_prouve_la_relance(monkeypatch, tmp_path, capsys):
    t = [1000.0]
    monkeypatch.setattr(C, "_ecouteur_hub", lambda port=8766: "ILLISIBLE")
    monkeypatch.setattr(C, "_hub_sain", lambda port=8766: True)
    monkeypatch.setattr(C, "JOURNAL_ORDRES", _journal(tmp_path, 995.0))
    rc = C.surveiller_hub_restart(10, 1, _horloge=lambda: t[0], _dormir=lambda s: t.__setitem__(0, t[0] + s))
    assert rc == 0
    assert "HUB RELANCE" in capsys.readouterr().out


def test_atteint_ancien_ne_prouve_rien(monkeypatch, tmp_path, capsys):
    t = [1000.0]
    monkeypatch.setattr(C, "_ecouteur_hub", lambda port=8766: "ILLISIBLE")
    monkeypatch.setattr(C, "_hub_sain", lambda port=8766: True)
    monkeypatch.setattr(C, "JOURNAL_ORDRES", _journal(tmp_path, 100.0))
    rc = C.surveiller_hub_restart(10, 1, _horloge=lambda: t[0], _dormir=lambda s: t.__setitem__(0, t[0] + s))
    assert rc != 0
