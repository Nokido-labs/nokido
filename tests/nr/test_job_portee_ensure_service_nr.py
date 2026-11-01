"""NR 31/10 (accord owner) : un job du bac redemarre un service par un jeton COURT, plus par le jeton permanent.

Mesure COF-1 31/10 07:46 -> 08:13 : 46 lectures du coffre, dont 42 par 14 process forge_supervisor_ctl lances par des jobs
(restart d'executeurs). Le jeton de job (identite JOB) n'avait que task:status/task:assign : l'echange refusait la portee
`nokido_ensure_service:appel`, et HubClient retombait sur le coffre (forge_hub_client._jeton_courant, repli tardif :
FORGE_TOKEN_SUPERVISOR_CTL + SERVICES + jeton_pour). Owner : accorder la portee -- meme pouvoir qu'avant, mais lie au job,
expirable, borne a cet outil. Jamais `run:*` depuis le bac (inchange).
"""
from __future__ import annotations

from nokido_agent.app import forge_oauth_route as O
from nokido_agent.app import forge_token_exchange as TX


def test_la_portee_d_un_appel_ensure_service():
    assert TX.portee_requise("nokido_ensure_service", {"service": "x", "desired_state": "restarted"}) == \
        "nokido_ensure_service:appel"


def test_job_a_droit_a_ensure_service():
    assert "nokido_ensure_service:appel" in O.POLITIQUE_DEFAUT["JOB"]["scopes"]


def test_jamais_run_depuis_le_bac():
    for ident, pol in O.POLITIQUE_DEFAUT.items():
        assert not any(s.startswith("run:") for s in pol["scopes"]), ident
