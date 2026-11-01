# -*- coding: utf-8 -*-
"""NR -- owner 30/10 « c'est de l'hygiene systematique » : une recherche web PONCTUELLE (sans owner) reveillait
Docker par `docker.wanted` et ne le rendait jamais ; reveil rate, Docker restait allume. Un appel ponctuel prend la
reclamation nommee `searxng_ponctuel` et la RELACHE a toute sortie (succes comme echec) ; le delai de grace du keeper
garde Docker pour les recherches suivantes. Un appel AVEC owner garde son contrat (la chaine relache au verdict)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_watch_agent as wa  # noqa: E402


def _keeper(monkeypatch):
    journal = []
    faux = types.ModuleType("nokido_agent.tools.forge_docker_keeper")
    faux.claim_docker = lambda o: journal.append(("claim", o))
    faux.release_claim = lambda o: journal.append(("release", o)) or {"released": True}
    faux.ensure_docker = lambda: journal.append(("want", None))
    faux._boot_timeout_for_load = lambda: (1, "test")
    faux._docker_info_ok = lambda: (False, "test")
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_docker_keeper", faux)
    sup = types.ModuleType("nokido_agent.tools.forge_supervisor_ctl")
    sup._call = lambda *a, **k: (200, {})
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_supervisor_ctl", sup)
    monkeypatch.setattr(wa, "_SEARX_LAST_ENSURE_TS", 0.0)
    monkeypatch.setattr(wa.time if hasattr(wa, "time") else __import__("time"), "sleep", lambda s: None,
                        raising=False)
    return journal


def test_reveil_rate_relache_la_reclamation(monkeypatch):
    journal = _keeper(monkeypatch)
    monkeypatch.setattr(wa.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert wa._ensure_searxng(wait_s=0) is False
    assert ("claim", "searxng_ponctuel") in journal
    assert journal[-1] == ("release", "searxng_ponctuel")


def test_succes_ponctuel_relache_aussi(monkeypatch):
    journal = _keeper(monkeypatch)

    class _R:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(wa.urllib.request, "urlopen", lambda *a, **k: _R())
    assert wa._ensure_searxng(wait_s=0) is True
    assert journal[-1] == ("release", "searxng_ponctuel")


def test_appel_avec_owner_ne_relache_pas_lui_meme(monkeypatch):
    journal = _keeper(monkeypatch)
    monkeypatch.setattr(wa.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    wa._ensure_searxng(wait_s=0, owner="chaine_x")
    assert ("claim", "chaine_x") in journal
    assert not any(e[0] == "release" for e in journal)
