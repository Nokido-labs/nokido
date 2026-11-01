# -*- coding: utf-8 -*-
"""NR - le REPLI legacy du hub applique la borne du jeton maitre comme le videur (parite)."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

MAITRE = "maitre-factice-0123456789"
JETON_VIBE = "jeton-factice-ABCDEF-123456"


@pytest.fixture(autouse=True)
def _bac(monkeypatch, tmp_path):
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LAFORGE_DATA_DIR", raising=False)
    monkeypatch.setenv("LAFORGE_MASTER_BORNE", "1")


def _hub(monkeypatch):
    import nokido_hub as hub
    monkeypatch.setattr(hub, "HUB_TOKEN", MAITRE, raising=False)
    monkeypatch.setattr(hub, "_AGENT_TOKENS", {"VIBE": JETON_VIBE}, raising=False)
    return hub


def _req(nom):
    h = {"Authorization": "Bearer " + MAITRE, "LaForge-Agent-Name": nom}
    return SimpleNamespace(headers=h, client=SimpleNamespace(host="127.0.0.1"))


def _casser_videur(monkeypatch):
    import nokido_agent.app.forge_videur as vv

    def _boom(*a, **k):
        raise RuntimeError("videur force en echec")
    monkeypatch.setattr(vv, "resolve_identity", _boom)


def test_repli_maitre_declarant_claude_est_borne(monkeypatch):
    hub = _hub(monkeypatch)
    _casser_videur(monkeypatch)
    ring, qui = hub._resolve_ring(_req("CLAUDE"))
    assert ring >= 4 and qui == "CLAUDE"


def test_repli_maitre_declarant_master_garde_le_ring_registre(monkeypatch):
    hub = _hub(monkeypatch)
    _casser_videur(monkeypatch)
    ring, _ = hub._resolve_ring(_req("MASTER"))
    # ring du registre (2 en production, decision owner 26/09) ; la graine de test peut differer.
    assert ring == hub._agent_ring("MASTER", 3)


def test_repli_sans_interrupteur_inchange(monkeypatch):
    hub = _hub(monkeypatch)
    monkeypatch.delenv("LAFORGE_MASTER_BORNE")
    _casser_videur(monkeypatch)
    ring, _ = hub._resolve_ring(_req("CLAUDE"))
    assert ring == hub._agent_ring("CLAUDE", 3)


# Parite sur le perimetre de la BORNE (noms soumis a la regle). MASTER/MASTER_TOKEN en sont
# exclus : leur ring vient du registre de chaque chemin (ecart de graine hub/videur, hors borne).
@pytest.mark.parametrize("nom", ["CLAUDE", "INCONNU_X"])
def test_parite_nominal_et_repli(monkeypatch, nom):
    hub = _hub(monkeypatch)
    nominal = hub._resolve_ring(_req(nom))
    _casser_videur(monkeypatch)
    repli = hub._resolve_ring(_req(nom))
    assert nominal[0] == repli[0], (nom, nominal, repli)


@pytest.mark.parametrize(
    ("principal_header", "declared_header"),
    [("PRINCIPAL", "DECLARE"), ("DECLARE", "PRINCIPAL")],
)
def test_jeton_partage_et_headers_distincts_ne_montent_pas_le_ring(
    monkeypatch, tmp_path, principal_header, declared_header
):
    import nokido_agent.app.forge_videur as videur

    jeton = "jeton-partage-nr"
    monkeypatch.setattr(videur, "_load_store", lambda: {"PRINCIPAL": 4, "DECLARE": 1})
    monkeypatch.setattr(videur, "_maybe_elevate", lambda agent, ring, local, via: ring)
    hub = _hub(monkeypatch)
    monkeypatch.setattr(hub, "_AGENT_TOKENS", {"PRINCIPAL": jeton, "DECLARE": jeton})
    req = types.SimpleNamespace(
        headers={
            "Authorization": "Bearer " + jeton,
            "X-Agent-Name": principal_header,
            "LaForge-Agent-Name": declared_header,
        },
        client=types.SimpleNamespace(host="127.0.0.1"),
    )

    import json
    journal = tmp_path / "auth_events.jsonl"
    monkeypatch.setattr(videur, "_chemin_auth_events", lambda: journal)
    ring, identite_resolue = hub._resolve_ring(req)
    evenement = json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])

    assert (ring, identite_resolue) == (4, "PRINCIPAL")
    # `principal` = identite PROUVEE par le credential, jamais une assertion d'en-tete :
    # dans la permutation inverse, l'en-tete X-Agent-Name dit DECLARE (ring 1) alors
    # que le principal retenu est PRINCIPAL (ring 4) -- le journal ne doit pas mentir.
    assert evenement["principal"] == "PRINCIPAL"
    assert evenement["principal_annonce"] == principal_header
    assert evenement["declared"] == declared_header
    assert evenement["via"] == "shared_token"
