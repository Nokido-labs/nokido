"""NR -- manage_forge_lifecycle presente un jeton au superviseur (bb:active_bugs/lifecycle_ecriture_superviseur_401_20261016).

Mesure 16/10 (3 fois) : STATUS passe, START/RESTART rendent « HTTP 401: Unauthorized ». Cause lue le 17/10 :
`forge_lifecycle_tool._supervisor_call` envoyait la requete SANS AUCUN en-tete d'autorisation, alors que le superviseur
exige un Bearer sur ses mutations (meme defaut que le regulateur RAM en mai, corrige par
`forge_resource_manager._supervisor_auth_headers`). Une seule brique d'en-tetes, nommant son appelant ; jeton lu par
`get_secret` (coffre d'abord, environnement en repli) -- depuis 6b82355ea le hub tient ses jetons du coffre.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_lifecycle_tool as LT  # noqa: E402
from nokido_agent.app import forge_resource_manager as RM  # noqa: E402
from nokido_agent.app import forge_secrets as S  # noqa: E402


class _Rep:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


def _capter(monkeypatch):
    vu = {}

    def urlopen(req, timeout=None):
        vu["entetes"] = {k.lower(): v for k, v in req.header_items()}
        vu["methode"] = req.get_method()
        return _Rep()

    monkeypatch.setattr(LT.urllib.request, "urlopen", urlopen)
    return vu


def test_une_ecriture_du_cycle_de_vie_porte_le_jeton_et_nomme_son_appelant(monkeypatch):
    monkeypatch.setattr(S, "get_secret", lambda cle: "jeton-de-test" if cle == "LAFORGE_SUPERVISOR_TOKEN" else None)
    vu = _capter(monkeypatch)
    LT._supervisor_call("POST", "/supervisor/service/start/NokidoTest")
    assert vu["methode"] == "POST"
    assert vu["entetes"].get("authorization") == "Bearer jeton-de-test", sorted(vu["entetes"])
    assert vu["entetes"].get("laforge-agent-name") == "MANAGE_FORGE_LIFECYCLE"


def test_le_jeton_vient_du_coffre_d_abord(monkeypatch):
    monkeypatch.setenv("LAFORGE_SUPERVISOR_TOKEN", "jeton-de-l-env")
    monkeypatch.setattr(S, "get_secret", lambda cle: "jeton-du-coffre" if cle == "LAFORGE_SUPERVISOR_TOKEN" else None)
    assert RM._supervisor_auth_headers()["Authorization"] == "Bearer jeton-du-coffre"


def test_le_regulateur_garde_son_nom(monkeypatch):
    monkeypatch.setattr(S, "get_secret", lambda cle: None)
    monkeypatch.delenv("LAFORGE_SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("FORGE_MCP_TOKEN", raising=False)
    h = RM._supervisor_auth_headers()
    assert h == {"LaForge-Agent-Name": "RESOURCE_MANAGER"}, "sans jeton : aucun en-tete Authorization vide"
