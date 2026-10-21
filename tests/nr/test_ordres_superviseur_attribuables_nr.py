"""NR -- un ordre envoye au superviseur par un organe porte le NOM de cet organe.

Fait keeper_arrete_embedder_en_usage_sans_intention_20261015, point (2) : les POST /supervisor/service/stop du
15/10 (17:14:58Z, 17:36:39Z) etaient journalises `agent_declare: "?"` dans sandbox/supervisor_ordres.jsonl -- le
keeper passe par forge_ensure_service.ensure -> forge_supervisor_ctl, et aucun maillon ne posait l'en-tete
`LaForge-Agent-Name` que lit `_journalOrdre` (proxy_deno/core/supervisor.ts). Il a fallu le journal du keeper
pour retrouver l'auteur.
"""
import os
import sys

import pytest

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_llama_keeper as K  # noqa: E402
import forge_supervisor_ctl as C  # noqa: E402


class _Reponse:
    status = 200

    def read(self):
        return b"{}"

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_le_client_du_superviseur_declare_l_agent_de_son_environnement(monkeypatch):
    vues = []
    monkeypatch.setenv("NOKIDO_CTL_AGENT", "LLAMA_KEEPER")
    monkeypatch.setattr(C.urllib.request, "urlopen", lambda req, timeout=0: vues.append(req) or _Reponse())
    C._call("/supervisor/service/stop/NokidoLlamaEmbed", "POST")
    assert vues[0].get_header("Laforge-agent-name") == "LLAMA_KEEPER"


def test_le_keeper_declare_son_identite_a_son_point_d_entree(monkeypatch):
    monkeypatch.setenv("NOKIDO_CTL_AGENT", "HERITE_DU_LANCEUR")   # setenv : restaure a la fin du test

    def arret():
        raise SystemExit(0)

    monkeypatch.setattr(K, "tick", arret)
    with pytest.raises(SystemExit):
        K.main()
    assert os.environ.get("NOKIDO_CTL_AGENT") == "LLAMA_KEEPER"
