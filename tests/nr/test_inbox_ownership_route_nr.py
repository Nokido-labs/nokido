# -*- coding: utf-8 -*-
"""NR RUNTIME — `DENY` ne doit pas seulement repondre 403 : il ne doit RIEN faire.

    DENY -> generateur NON CREE -> `pop()` JAMAIS APPELE -> aucun message consomme

Une reponse correcte ne prouve pas l'absence d'effet. `_INBOX.pop()` RETIRE le
message de la file : un refus qui aurait deja consomme aurait vole le courrier
tout en le refusant a son proprietaire -- le pire des deux mondes.

    METHODE != EFFET. Verifier le code de statut ne mesure que la METHODE.

AUCUNE BOITE REELLE N'EST TOUCHEE. `INBOX` est substituee par un compteur : le
test ne fait jamais `pop()` sur une file contenant du courrier utile. Et le
compteur DOIT pouvoir bouger -- le cas ALLOW le prouve, sinon les `pops == 0`
des cas negatifs seraient vrais par impuissance de la sonde.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _p in (_RACINE, _RACINE / "app", _RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

hub = importlib.import_module("nokido_hub")
videur = importlib.import_module("forge_videur")


class _Entetes(dict):
    """Insensible a la casse, comme les en-tetes HTTP reels."""

    def get(self, cle, defaut=None):
        for k, v in self.items():
            if k.lower() == str(cle).lower():
                return v
        return defaut


class _Client:
    host = "127.0.0.1"


class _Requete:
    def __init__(self, agent_id, entetes=None):
        self.path_params = {"agent_id": agent_id}
        self.headers = _Entetes(entetes or {})
        self.client = _Client()

    async def is_disconnected(self):
        return False


class _InboxCompteur:
    """Remplace la vraie INBOX. Compte, ne consomme rien de reel."""

    def __init__(self):
        self.pops = 0

    async def pop(self, agent_id, timeout=None):
        self.pops += 1
        return None


@pytest.fixture()
def compteur(monkeypatch):
    c = _InboxCompteur()
    cible = importlib.import_module("nokido_agent.app.forge_message_frame")
    monkeypatch.setattr(cible, "INBOX", c)
    return c


def _appeler(requete):
    return asyncio.run(hub.inbox_stream(requete))


def _sujet(monkeypatch, agent, prouve=True, via="token"):
    monkeypatch.setattr(hub, "_identite_inbox",
                        lambda _r: {"agent": agent, "via": via,
                                    "sujet_prouve": prouve})


# ── LA CONTRE-EPREUVE D'ABORD : la sonde sait-elle voir un pop ? ─────────

def test_ALLOW_le_proprietaire_consomme_vraiment(compteur, monkeypatch):
    """Sans ce test, tous les `pops == 0` ci-dessous seraient vrais parce que
    la sonde ne sait rien compter."""
    _sujet(monkeypatch, "CLAUDE")
    r = _appeler(_Requete("CLAUDE"))
    assert getattr(r, "status_code", None) != 403, r
    flux = r.body_iterator

    async def _deux():
        it = flux.__aiter__()
        await it.__anext__()   # "connected"
        await it.__anext__()   # declenche le pop
    asyncio.run(_deux())
    assert compteur.pops >= 1, (
        "ALLOW n'a atteint aucun pop : la sonde ne mesure rien, et les cas "
        "negatifs seraient verts par impuissance")


def test_ALLOW_pour_un_ALIAS_du_consommateur_reel(compteur, monkeypatch):
    """`gemini_poll_daemon` s'annonce GEMINI et ecoute `/inbox/agt_gemini`.
    Si ce test rougit, l'armement COUPE un consommateur legitime."""
    _sujet(monkeypatch, "GEMINI")
    r = _appeler(_Requete("agt_gemini"))
    assert getattr(r, "status_code", None) != 403, (
        "le daemon legitime est COUPE par l'armement : %s" % r)


# ── LES CAS NEGATIFS : 403 *ET* AUCUN EFFET ─────────────────────────────

@pytest.mark.parametrize("agent_id,sujet,prouve,via,quoi", [
    ("CLAUDE", "ANTIGRAVITY", True, "token", "sujet different"),
    ("CLAUDE", None, True, "token", "sujet absent"),
    ("CLAUDE", "CLAUDE", False, "header", "identite DECLAREE, non prouvee"),
    ("CLAUDE", "CLAUDE", False, "master_token", "porteur du maitre"),
    ("CLAUDE", "CLAUDE", False, "delegated:WEBHUB", "delegation"),
    ("CLAUDE", "CLAUDE", False, "repli_legacy", "repli"),
    ("INCONNU_XYZ_42", "INCONNU_XYZ_42", True, "token", "inconnu auto-autorise"),
])
def test_DENY_repond_403_ET_n_atteint_jamais_pop(compteur, monkeypatch,
                                                 agent_id, sujet, prouve, via, quoi):
    _sujet(monkeypatch, sujet, prouve=prouve, via=via)
    r = _appeler(_Requete(agent_id))
    assert getattr(r, "status_code", None) == 403, "%s : pas refuse (%s)" % (quoi, r)
    assert compteur.pops == 0, (
        "%s : REFUSE mais le courrier a ete consomme (%d pop) — DENY doit etre "
        "SANS EFFET, pas seulement sans reponse" % (quoi, compteur.pops))


def test_DENY_si_l_index_des_boites_se_tait(compteur, monkeypatch):
    """Registre muet -> refus, jamais repli permissif sur le nom brut."""
    _sujet(monkeypatch, "CLAUDE")
    monkeypatch.setattr(videur, "_index_boites", lambda: {})
    r = _appeler(_Requete("CLAUDE"))
    assert getattr(r, "status_code", None) == 403, r
    assert compteur.pops == 0, r


def test_SANS_porteur_aucune_identite_et_aucun_effet(compteur):
    """Chemin REEL, sans monkeypatch de l'identite : pas de Bearer du tout."""
    r = _appeler(_Requete("CLAUDE"))
    assert getattr(r, "status_code", None) == 403, r
    assert compteur.pops == 0, r


# ── LA DUPLICATION D'EXTRACTION NE DOIT PAS DERIVER ─────────────────────

def test_identite_inbox_et_resolve_ring_nomment_le_MEME_agent():
    """`_identite_inbox` reprend l'extraction de `_resolve_ring`. Deux copies
    derivent en silence : on verrouille qu'elles s'accordent sur l'agent.

    Sans porteur valide, les deux doivent conclure a l'absence d'identite --
    et surtout PAS l'une a `None` et l'autre a un nom declare.
    """
    req = _Requete("CLAUDE", {"X-Agent-Name": "CLAUDE"})
    ident = hub._identite_inbox(req)
    assert not ident.get("sujet_prouve"), (
        "un en-tete sans porteur a suffi a prouver un sujet : %s" % ident)
    ring, agent = hub._resolve_ring(req)
    assert ring < 0 or not ident.get("agent") or agent == ident.get("agent"), (
        "les deux chemins d'extraction ont DERIVE : _resolve_ring dit %r, "
        "_identite_inbox dit %r" % (agent, ident.get("agent")))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
