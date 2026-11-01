# -*- coding: utf-8 -*-
"""NR (28/10, owner : « on avait convenu d'un procede plus reactif ») : le hub RECLAME Docker en son nom et le
RELACHE des qu'il n'en a plus besoin (claim_docker / release_claim du keeper : la derniere reclamation relachee
arrete Docker sans attendre le TTL de docker.wanted, 900 s).

Mesure 28/10 13:2x : RAM 97,8 %, vmmemWSL 2,4 Go -- Docker garde par le seul TTL d'ensure_docker(), renouvele a
chaque appel docker_* ; personne ne le relachait."""
import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_docker_supervisor as fds  # noqa: E402


def _faux_keeper(monkeypatch):
    journal = []
    k = types.SimpleNamespace(
        claim_docker=lambda owner: journal.append(("claim", owner)),
        release_claim=lambda owner: journal.append(("release", owner)) or {"released": True},
        ensure_docker=lambda: journal.append(("ensure",)),
    )
    monkeypatch.setattr(fds, "_keeper", lambda: k)
    return journal


def test_la_demande_est_une_reclamation_nommee(monkeypatch):
    journal = _faux_keeper(monkeypatch)
    fds._demander_docker()
    assert journal == [("claim", fds.PROPRIETAIRE_DOCKER)]


def test_relache_apres_inactivite(monkeypatch):
    journal = _faux_keeper(monkeypatch)
    monkeypatch.setattr(fds, "RELACHE_APRES_S", 0.05)

    async def faux_rpc(self, method, params, timeout):
        return {"content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(fds.DockerSupervisor, "_jsonrpc", faux_rpc)

    async def scenario():
        sup = fds.DockerSupervisor()
        await sup.call_tool("mcp-find", {})
        await sup.call_tool("mcp-find", {})  # un 2e appel repousse la relache
        await asyncio.sleep(0.2)

    asyncio.run(scenario())
    assert ("release", fds.PROPRIETAIRE_DOCKER) in journal
    assert journal.count(("release", fds.PROPRIETAIRE_DOCKER)) == 1


def test_sans_keeper_simule_un_test_ne_touche_pas_le_vrai_docker(monkeypatch):
    """Garde : sous pytest, sans `_keeper` remplace, ni reclamation ni relache n'atteignent le vrai keeper."""
    appels = []

    def vrai_keeper():  # meme NOM que l'original : simule un test qui n'a rien remplace
        appels.append(1)
        raise AssertionError("le vrai keeper a ete appele depuis un test")

    vrai_keeper.__name__ = "_keeper"
    monkeypatch.setattr(fds, "_keeper", vrai_keeper)
    fds._demander_docker()
    fds._relacher_docker()
    assert appels == []


def test_rafraichir_catalogue_relache_en_sortant(monkeypatch, capsys):
    journal = _faux_keeper(monkeypatch)

    class _Sup:
        async def list_tools(self, force=False):
            return [{"name": "mcp-find"}]

        def shutdown(self):
            pass

    monkeypatch.setattr(fds, "get_supervisor", lambda: _Sup())
    assert fds.main(["--rafraichir-catalogue"]) == 0
    assert journal[-1] == ("release", fds.PROPRIETAIRE_DOCKER)
