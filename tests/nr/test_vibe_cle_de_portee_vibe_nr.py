# -*- coding: utf-8 -*-
"""NR -- owner 9/11 : les cles Mistral ont une PORTEE (console Mistral) : la cle « Nokido » sert VIBE, la cle
« LaForge » sert STUDIO (API La Plateforme). Vibe recevait la cle Studio (MISTRAL_API_KEY, 32 car., budget epuise :
402 billing_api_budget_exhausted). Chaque point d'injection de Vibe lit MISTRAL_VIBE_API_KEY au coffre ; la cle
Studio reste celle de l'API (MISTRAL_API_KEY, intouchee)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_le_lanceur_vibe_lit_la_cle_de_portee_vibe(monkeypatch):
    import nokido_vibe as V
    from nokido_agent.app import forge_secrets as s

    lus = []
    monkeypatch.setattr(s, "get_secret", lambda k, *a, **kw: lus.append(k) or ("v" * 45 if k == "MISTRAL_VIBE_API_KEY" else "s" * 32))
    assert V._cle_mistral() == "v" * 45
    assert lus[0] == "MISTRAL_VIBE_API_KEY"


def test_le_routage_cli_injecte_la_cle_vibe():
    import forge_cli_route as R
    assert R.SECRET_ENV["vibe"]["MISTRAL_API_KEY"] == "MISTRAL_VIBE_API_KEY"


def test_le_harness_injecte_la_cle_vibe():
    from nokido_agent.app import forge_cli_harness as H
    assert H._SECRETS_PAR_AGENT["vibe"]["NOKIDO_MISTRAL_API_KEY"] == "MISTRAL_VIBE_API_KEY"
