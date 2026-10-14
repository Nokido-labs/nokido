"""NR -- la veille automatique porte SON identite, pas le badge commun SERVICES (2026-10-13).

NokidoRSSWatcher ingerait sous SERVICES (ring 4) quand l'outil `rag` exige 3 : « GATE_DENIED: ring 4 <= requis 3 »
a chaque cycle, « 0 chunks ingeres », 13 522 refus dans la seule fin de son journal. Remede (owner, GO a) : une
identite propre RSS_WATCHER au ring 3, sans relever SERVICES -- ce qui ouvrirait l'ecriture au RAG a tout organe qui
emprunte ce badge.
"""
from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import nokido_agent.app.forge_rss_watcher as W

REGISTRE = Path(__file__).resolve().parents[2] / "config" / "agent_identities.json"


def _identites() -> dict:
    def trouver(o):
        if isinstance(o, dict):
            if "SERVICES" in o and isinstance(o["SERVICES"], dict):
                return o
            for v in o.values():
                r = trouver(v)
                if r is not None:
                    return r
        return None

    return trouver(json.loads(REGISTRE.read_text(encoding="utf-8")))


def test_le_registre_declare_rss_watcher_au_ring_3_sans_relever_services():
    reg = _identites()
    assert reg["RSS_WATCHER"]["ring"] == 3
    assert reg["SERVICES"]["ring"] == 4, "relever SERVICES ouvrirait le RAG a tout organe qui l'emprunte"


class _Rep(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_l_ingestion_presente_son_identite_et_demande_son_jeton(monkeypatch):
    demandes, entetes = [], []
    cred = types.ModuleType("forge_agent_credential")
    cred.jeton_pour = lambda agent: demandes.append(agent) or "jeton-de-test"
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_agent_credential", cred)

    def _urlopen(req, timeout=None):
        entetes.append(dict(req.header_items()))
        return _Rep(json.dumps({"result": {"content": [{"text": "1 chunk(s) indexe(s)"}]}}).encode())

    monkeypatch.setattr(W.urllib.request, "urlopen", _urlopen)
    W._ingest("texte", "source", "veille", "doc", "auteur", "resume")
    assert demandes == ["RSS_WATCHER"]
    assert entetes and entetes[0].get("X-agent-name") == "RSS_WATCHER", entetes
