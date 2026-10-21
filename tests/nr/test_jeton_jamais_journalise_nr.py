"""NR -- RED7 free tier : un jeton n'atteint JAMAIS les puits de l'executeur (detail persiste et emis au hub) ni
les journaux du client ACP (stderr de l'agent, lignes non JSON).

Enquete AGY 19/10 (job_55a851be -> job_194ae927, M:lit INTEGREE) : 15 puits possibles ; `_clore_delegation` ecrit
`detail` en base ET l'emet au hub, et `ACPClient.on_log` recopie le stderr brut de l'agent, dont l'environnement porte
FORGE_TOKEN_<INSTANCE>. Le redacteur existe (tools/forge_log_redact.redact) : il est BRANCHE, pas recopie.
Assertions BOOLEENNES seulement (consigne owner : jamais afficher une valeur de secret, meme fabriquee) ; lancer en
--tb=no.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_acp_client as A  # noqa: E402
import forge_task_executor as T  # noqa: E402

# Temoin FABRIQUE a l'execution (jamais un litteral : le scan de secrets du depot le refuserait, a raison).
TEMOIN = "ghp_" + "Zq7" * 12


def test_le_redacteur_branche_retire_le_temoin():
    assert TEMOIN not in T._caviarder("Authorization: Bearer " + TEMOIN)


def test_clore_delegation_ne_persiste_ni_n_emet_le_jeton(monkeypatch):
    vus = []
    monkeypatch.setattr(T, "_hub_call", lambda tool, args, token, timeout=30: vus.append(args) or {})
    monkeypatch.setattr(T, "_mark_done", lambda conn, tid, detail, ok: vus.append({"base": detail}))
    monkeypatch.setattr(T, "_db", lambda: type("C", (), {"close": lambda self: None})())
    T._clore_delegation("job_temoin", "x", False, "erreur ACP (RuntimeError): Authorization: Bearer " + TEMOIN)
    assert vus and all(TEMOIN not in str(v) for v in vus)


def test_les_journaux_du_client_acp_sont_caviardes():
    lignes = []
    c = A.ACPClient(cmd=["inexistant"], agent="opencode", on_log=lignes.append)
    c.on_log("[stderr] Authorization: Bearer " + TEMOIN)
    assert lignes and all(TEMOIN not in ligne for ligne in lignes)
