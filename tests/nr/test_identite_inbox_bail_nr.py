# -*- coding: utf-8 -*-
"""NR - un jeton a bail VALIDE est une identite PROUVEE pour `_identite_inbox`.

Mesure 22-24/10 : 6 organes a bail finissaient en `bad_token` (ring 4, sujet non prouve)
car `_identite_inbox` re-resolvait le bail contre le seul magasin statique.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _bail():
    p = base64.urlsafe_b64encode(json.dumps({"sub": "RSS_WATCHER", "ring": 2, "exp": 9e9}).encode()).decode().rstrip("=")
    return p + ".sig"


def test_bail_valide_est_prouve(monkeypatch, tmp_path):
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(tmp_path))
    import nokido_hub as hub
    from nokido_agent.app import forge_integrity as fi
    monkeypatch.setattr(hub, "HUB_TOKEN", "maitre-factice-0123456789", raising=False)
    monkeypatch.setattr(hub, "_AGENT_TOKENS", {}, raising=False)
    monkeypatch.setattr(fi, "get_manager", lambda: SimpleNamespace(_secret=b"s"))
    monkeypatch.setattr(fi.CapabilityToken, "decode",
                        classmethod(lambda cls, raw, secret, **k: SimpleNamespace(sub="RSS_WATCHER", ring=2)))
    req = SimpleNamespace(headers={"Authorization": "Bearer " + _bail(), "LaForge-Agent-Name": "RSS_WATCHER"},
                          client=SimpleNamespace(host="127.0.0.1"))
    ident = hub._identite_inbox(req)
    assert ident["sujet_prouve"] is True and ident["agent"] == "RSS_WATCHER"
