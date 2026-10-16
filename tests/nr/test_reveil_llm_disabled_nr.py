"""NR - /supervisor/llm/activate reveille un LLM du pool DECLARE disabled, sans contourner le pool (15/10).

Audit ChatGPT web du 15/10, VERIFIE sur le code : NokidoLlamaNative est `disabled = true`, donc
absent de `states` au boot ; `/supervisor/llm/activate/<nom>` faisait `states.get(name)` et rendait
404 « not in llm pool », alors que `/service/start` savait creer l'etat a la demande -- et
`tools/llama_cli.py` appelle precisement llm/activate. Les deux routes partagent maintenant
`etatALaDemande`. Le comportement complet exige un superviseur relance : ce NR fige l'ORDRE dans la
source (reveil reserve au pool, enforcePool AVANT startService), comme les NR existants de supervisor.ts.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[2] / "proxy_deno" / "core" / "supervisor.ts").read_text(encoding="utf-8")


def _bloc(debut: str) -> str:
    i = SRC.index(debut)
    return SRC[i:i + 1600]


def test_une_seule_fonction_cree_l_etat_a_la_demande():
    assert "function etatALaDemande(name: string, exigeLlmPool: boolean)" in SRC
    f = _bloc("function etatALaDemande(")
    assert "SERVICES.find(" in f and "exigeLlmPool && !def.llmPool" in f


def test_llm_activate_reveille_puis_borne_le_pool_avant_de_demarrer():
    b = _bloc('p.startsWith("/supervisor/llm/activate/")')
    reveil = b.index("states.get(name) ?? etatALaDemande(name, true)")
    pool = b.index("await enforcePool(name)")
    depart = b.index("startService(state)")
    assert reveil < pool < depart
    assert "not in llm pool" in b  # un non-membre du pool reste refuse


def test_service_start_garde_son_reveil_generique():
    b = _bloc('p.startsWith("/supervisor/service/start/")')
    assert "states.get(name) ?? etatALaDemande(name, false)" in b
    assert re.search(r"unknown service", b)
