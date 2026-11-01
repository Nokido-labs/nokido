"""NR : le lanceur de secours tente l'echange de jeton RFC 8693 AVANT de lire le coffre (owner 29/10).

Audit AGY du coffre (docs/audit/AUDIT_COFFRE_CLOISONNE_20261029.md, cite verifiee) : _appel_identite exigeait
_get_secret("FORGE_TOKEN_SWARM_LANCEUR") avant meme _session_pour, donc lisait le secret d'une identite ring 3 depuis le
bac a sable meme quand un jeton de job permettait l'echange. Condition prealable au passage au refus du coffre.
Ce NR tient : echange reussi = coffre JAMAIS lu ; echange absent = coffre en repli (comportement d'avant) ; ni l'un ni
l'autre = refus, jamais de repli sur un autre jeton.
"""
import sys
import types
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
from tools import forge_secours_lanceur as SL  # noqa: E402


@pytest.fixture
def hub(monkeypatch):
    vus = {}
    monkeypatch.setattr(SL, "_http", lambda url, payload, headers: vus.update(h=headers) or "ok")
    monkeypatch.setitem(sys.modules, "app.forge_mpc_executor", types.SimpleNamespace(_HUB="http://hub.test"))
    return vus


def _interdit(*a, **k):
    raise AssertionError("coffre lu alors que l'echange de jeton a reussi")


def test_echange_reussi_le_coffre_n_est_jamais_lu(monkeypatch, hub):
    monkeypatch.setattr(SL, "_echange_job", lambda: "JETON_ECHANGE")
    monkeypatch.setattr(SL, "_get_secret", _interdit)
    monkeypatch.setattr(SL, "_jeton_session", _interdit)
    assert SL._appel_identite("task", {"action": "status"}) == "ok"
    assert hub["h"]["Authorization"] == "Bearer JETON_ECHANGE"


def test_sans_echange_le_coffre_reste_le_repli(monkeypatch, hub):
    monkeypatch.setattr(SL, "_echange_job", lambda: None)
    monkeypatch.setattr(SL, "_get_secret", lambda cle: "S")
    monkeypatch.setattr(SL, "_jeton_session", lambda s: "SESSION_" + s)
    assert SL._appel_identite("task", {}) == "ok"
    assert hub["h"]["Authorization"] == "Bearer SESSION_S"


def test_ni_echange_ni_coffre_refuse(monkeypatch, hub):
    monkeypatch.setattr(SL, "_echange_job", lambda: None)
    monkeypatch.setattr(SL, "_get_secret", lambda cle: None)
    with pytest.raises(RuntimeError):
        SL._appel_identite("task", {})
    assert "h" not in hub
