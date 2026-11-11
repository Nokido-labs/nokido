# -*- coding: utf-8 -*-
"""NR (owner 3/11) : `no_auth` apparaissait dans le tray en « Agents actifs » (ring -1, client 127.0.0.1).

Ce n'est pas un agent : c'est le libelle que le hub (`_resolve_ring`, tools/nokido_hub.py) donne a une requete
SANS en-tete Authorization -- typiquement la premiere requete d'un client OAuth MCP avant sa connexion (401 puis
decouverte RFC 9728). Le hub ecrit `presence_no_auth.seen` comme pour un appelant ; la presence le rendait comme
un interlocuteur. Decision owner : le sortir des agents, le compter a part (« requetes sans jeton refusees »).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_presence as P  # noqa: E402


def _empreinte(dossier: Path, agent: str, ring: int, client: str = "127.0.0.1"):
    (dossier.parent / ("presence_%s.seen" % agent)).write_text(json.dumps(
        {"agent": agent, "ts": datetime.now().isoformat(), "ring": ring, "client": client}), encoding="utf-8")


def test_no_auth_n_est_pas_un_interlocuteur(tmp_path):
    porte = tmp_path / "presence"
    porte.mkdir()
    _empreinte(porte, "no_auth", -1)
    _empreinte(porte, "bad_token", -1)
    _empreinte(porte, "claude", 1)
    etat = {e["agent"]: e for e in P.etat_presence(900, identites={}, dossier=porte)}
    assert set(etat) == {"NO_AUTH", "BAD_TOKEN", "CLAUDE"}, "le chemin reel n'a rien rendu : NR a vide"
    for anon in ("NO_AUTH", "BAD_TOKEN"):
        assert etat[anon]["anonyme"] is True
        assert etat[anon]["interlocuteur"] is False
    assert etat["CLAUDE"]["anonyme"] is False
    assert etat["CLAUDE"]["interlocuteur"] is True  # non declare : toujours montre, jamais cache


def test_repartir_met_les_anonymes_a_part(tmp_path):
    porte = tmp_path / "presence"
    porte.mkdir()
    _empreinte(porte, "no_auth", -1)
    _empreinte(porte, "claude", 1)
    inter, organes, anonymes = P.repartir(P.etat_presence(900, identites={}, dossier=porte))
    assert [e["agent"] for e in inter] == ["CLAUDE"]
    assert organes == []
    assert [e["agent"] for e in anonymes] == ["NO_AUTH"]


def test_le_tray_passe_par_repartir():
    src = (ROOT / "tools" / "nokido_tray.py").read_text(encoding="utf-8")
    assert "repartir(" in src, "le tray doit separer les anonymes via forge_presence.repartir"
    assert "sans jeton" in src
