"""NR -- le journal d'actes porte les LECTURES et ne grossit plus sans borne (owner 31/10).

MESURE du 2026-10-31 : la carte d'attention (forge_stats `attention`) restait VIDE en production -- elle lit
logs/actes_agents.jsonl, qui ne journalisait que les outils qui AGISSENT ; aucune lecture n'y entrait. Et ce
journal pesait 49,6 Mo sans aucune rotation. Choix owner : journaliser aussi les lectures (chemin + symbole,
jamais le contenu ni la reponse) et faire tourner le journal au-dela de 20 Mo.

Chemin REEL : net_log (le point de passage du hub), pas des actes fabriques a la main.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_network_logger as nl  # noqa: E402


@pytest.fixture
def journal(monkeypatch, tmp_path):
    chemin = tmp_path / "actes_agents.jsonl"
    monkeypatch.setattr(nl, "_JOURNAL_ACTES", chemin, raising=False)
    monkeypatch.setattr(nl, "_get_audit", lambda: None)  # jamais le vrai mcp_audit.log
    return chemin


def _appel(outil: str, arguments: dict) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": outil, "arguments": arguments}})


def _lignes(chemin: Path) -> list[dict]:
    return [json.loads(x) for x in chemin.read_text(encoding="utf-8").splitlines()] if chemin.exists() else []


def test_une_lecture_entre_au_journal_avec_son_chemin_et_son_symbole(journal):
    nl.net_log(nl.NetworkChannel.HTTP_CLAUDE, nl.Direction.IN, tool="read_function_body", agent="CLAUDE",
               ring=1, payload_in=_appel("read_function_body",
                                         {"path": "app/forge_x.py", "function_name": "calcul",
                                          "explanation": "pourquoi"}))
    [acte] = _lignes(journal)
    assert (acte["sens"], acte["outil"], acte["agent"]) == ("LECTURE", "read_function_body", "CLAUDE")
    assert "app/forge_x.py" in acte["extrait"] and "calcul" in acte["extrait"]
    assert "pourquoi" not in acte["extrait"]  # seulement chemin + symbole


def test_la_reponse_d_une_lecture_n_est_jamais_journalisee(journal):
    nl.net_log(nl.NetworkChannel.HTTP_CLAUDE, nl.Direction.OUT, tool="read", agent="CLAUDE",
               ring=1, payload_out="def secret_contenu(): ...")
    assert _lignes(journal) == []


def test_la_carte_d_attention_compte_la_lecture(journal, tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "forge_x.py").write_text("x = 1\n", encoding="utf-8")
    nl.net_log(nl.NetworkChannel.HTTP_CLAUDE, nl.Direction.IN, tool="read", agent="CLAUDE",
               ring=1, payload_in=_appel("read", {"action": "file", "path": "app/forge_x.py"}))
    carte = nl.carte_attention(racine=tmp_path)
    assert carte["lectures_totales"] == 1
    assert [f["chemin"] for f in carte["fichiers"]] == ["app/forge_x.py"]


def test_une_charge_coupee_garde_le_chemin_sans_inventer(journal):
    coupe = _appel("read", {"action": "file", "path": "app/forge_y.py", "lines": 40})[:-12]
    nl.net_log(nl.NetworkChannel.HTTP_CLAUDE, nl.Direction.IN, tool="read", agent="CLAUDE",
               ring=1, payload_in=coupe)
    [acte] = _lignes(journal)
    assert acte["forme"] == "TEXTE_NON_ANALYSABLE"
    assert "app/forge_y.py" in acte["extrait"]


def test_le_journal_tourne_au_dela_du_seuil(journal, monkeypatch):
    monkeypatch.setattr(nl, "_ACTES_MAX_OCTETS", 100)
    journal.write_text("x" * 200 + "\n", encoding="utf-8")
    nl.net_log(nl.NetworkChannel.HTTP_CLAUDE, nl.Direction.IN, tool="read", agent="CLAUDE",
               ring=1, payload_in=_appel("read", {"action": "file", "path": "app/z.py"}))
    ancien = journal.with_name(journal.name + ".1")
    assert ancien.exists() and ancien.read_text(encoding="utf-8").startswith("x" * 200)
    [acte] = _lignes(journal)
    assert acte["sens"] == "LECTURE"
