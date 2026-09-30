"""NR — `introspect` doit etre ATTEIGNABLE, pas seulement declare.

CE QUE CE TEST PROTEGE. Le 2026-08-31, `introspect` a ete declare au catalogue
MCP, son handler ecrit, son ring pose — et le premier appel d'agent a rendu :

    {"error": ["tool 'introspect' not allowed"]}

Declarer un verbe ne le rend pas appelable. Il y a DEUX barrieres distinctes,
et elles ne se voient pas l'une l'autre :

  1. `hub_middleware._ALLOWED_TOOLS` — allowlist STATIQUE du endpoint /mcp.
     Absente, l'appel meurt en 400 a l'EXECUTION, apres avoir passe catalogue et
     RBAC. Le piege etait deja documente pour `forge_deep_explore`, et il a ete
     re-paye a l'identique.
  2. `forge_tool_scope.CORE_TOOLS` — visibilite quand un agent a DECLARE une
     intention de session. Hors CORE, un verbe range dans un groupe disparait
     pour tout agent ayant declare un autre groupe.

La premiere fait echouer l'appel ; la seconde le fait disparaitre. Les deux
doivent tenir, et aucune n'est deductible de l'autre — d'ou ce test.

HERMETIQUE : aucun appel reseau, aucun hub. Le scope est simule dans `tmp_path`.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app import forge_tool_scope as scope  # noqa: E402
from tools import hub_middleware as mw  # noqa: E402

VERBE = "introspect"


# ── barriere 1 : l'allowlist qui refusait reellement ────────────────────────
def test_le_verbe_passe_l_allowlist_du_endpoint():
    """C'est CETTE barriere qui rendait 400 « not allowed », pas le scope."""
    ok, valeur = mw.validate_tool_name(VERBE)
    assert ok is True, valeur
    assert valeur == VERBE


def test_l_allowlist_sait_toujours_refuser():
    """Contre-epreuve : une allowlist qui accepte tout ne garde rien."""
    ok, raison = mw.validate_tool_name("outil_qui_nexiste_pas_xyz")
    assert ok is False
    assert "not allowed" in raison


# ── barriere 2 : la visibilite quel que soit le scope declare ───────────────
def test_le_verbe_est_une_porte_universelle():
    assert VERBE in scope.CORE_TOOLS


def test_un_agent_ayant_declare_un_AUTRE_groupe_le_voit_quand_meme(tmp_path, monkeypatch):
    """Le coeur du contrat : interroger le corps ne depend pas de l'intention.

    Un agent qui a declare « veille » a le meme besoin de savoir ce que Nokido
    sait deja qu'un agent qui a declare « code_recon ».
    """
    etat = tmp_path / "tool_scope.json"
    etat.write_text(json.dumps({
        "AGENT_TEST": {"tools": ["crawl", "biblio"], "ts": time.time(),
                       "group": "veille"}}), encoding="utf-8")
    monkeypatch.setattr(scope, "_STATE", etat)
    scope._reset()
    actifs = scope.active_tools_for("AGENT_TEST")
    assert actifs is not None
    assert VERBE in actifs, "hors CORE_TOOLS, le verbe disparait des qu'un scope est declare"
    assert "crawl" in actifs, "le scope declare doit rester actif"


def test_sans_scope_declare_rien_n_est_filtre(tmp_path, monkeypatch):
    """Fail-open assume : pas de scope = pas de filtre. On le verrouille pour
    qu'un durcissement futur soit un choix, pas un effet de bord."""
    monkeypatch.setattr(scope, "_STATE", tmp_path / "absent.json")
    scope._reset()
    assert scope.active_tools_for("AGENT_SANS_SCOPE") is None


# ── le registre : un seul verbe, celui qu'on croit ──────────────────────────
def _catalogue():
    from app import forge_mcp_registry as reg
    return reg.ToolRegistry()._raw_tool_catalog()


def test_le_verbe_est_declare_une_SEULE_fois():
    """Un doublon d'outil rend le comportement dependant de l'ordre du catalogue."""
    noms = [t["name"] for t in _catalogue()]
    assert noms.count(VERBE) == 1


def test_le_schema_expose_est_bien_celui_d_introspect():
    entree = [t for t in _catalogue() if t["name"] == VERBE][0]
    props = entree["inputSchema"]["properties"]
    assert entree["inputSchema"]["required"] == ["query"]
    assert set(props) == {"query", "budget_tokens"}


def test_le_handler_existe_et_porte_le_bon_nom():
    from app import forge_mcp_registry as reg
    assert hasattr(reg.ToolRegistry(), "handle_%s" % VERBE)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
