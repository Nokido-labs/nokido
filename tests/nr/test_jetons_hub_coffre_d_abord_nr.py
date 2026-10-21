"""NR -- famille 1 du chantier SECU (bb:active_bugs/secu_secrets_cloud_lus_dans_env_37_fichiers_geles_20261016) :
le JETON DU HUB se lit au coffre d'abord. forge_secrets.get_secret lit deja coffre DPAPI -> WCM -> Nokido.env ->
environnement (repli en dernier, avertissement « non securise ») : remplacer os.environ par get_secret ne casse aucun
client qui n'a que l'environnement. Oracle : la regle laforge-cloud-secret-from-env (tools/forge_golden_rules_ast.py).
Lot A (16/10) : scripts a un seul site.
"""
import os
import sys

_DEPOT = os.path.join(os.path.dirname(__file__), "..", "..")
_TOOLS = os.path.join(_DEPOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_golden_rules_ast as g  # noqa: E402

LOT_A = ("tools/test_hub_mcp_handshake.py", "tools/test_software_creator_e2e.py", "tools/forge_wheel_probe_monthly.py",
         "tools/forge_ui_generator.py", "tools/forge_bundle_primitives.py", "tools/forge_bell.py",
         "tools/forge_execute_loop.py")


LOT_B = ("tools/forge_mcp_proxy.py", "tools/forge_openai_proxy.py")
LOT_C = ("tools/gemini_hub_relay.py", "tools/forge_py314t_flip_canary.py", "tools/forge_py314t_readiness.py",
         "tools/forge_freetier_probe.py")


LOT_D = ("tools/forge_goap_online_launch.py", "tools/ollama_cloud_proxy_agent.py")


def test_les_derniers_sites_lisent_le_coffre_d_abord():
    """Mesure sous SYSTEM du 16/10 (mode DEV owner) : 1 valeur distincte par nom entre les stores du coffre, WCM et
    Nokido.env absents -> basculer ces lecteurs en coffre d'abord ne change aucune valeur servie. forge_mcp_registry :
    derogation owner du 16/10."""
    restants = ["%s:%s" % (rel, f["line"])
                for rel in ("tools/nokido_hub.py", "tools/nokido.py", "tools/forge_db_encrypt_migrate.py",
                            "app/forge_mcp_registry.py")
                for f in g.scan_file(os.path.join(_DEPOT, rel)) if f["rule"] == "laforge-cloud-secret-from-env"]
    assert not restants, restants


def test_le_demon_multi_llm_lit_le_jeton_du_hub_au_coffre_d_abord():
    """Balayage du 16/10 apres le lot 1 : multi_llm_daemon lisait FORGE_MCP_TOKEN dans l'env au chargement (L640)."""
    rel = "tools/multi_llm_daemon.py"
    restants = ["%s:%s" % (rel, f["line"]) for f in g.scan_file(os.path.join(_DEPOT, rel))
                if f["rule"] == "laforge-cloud-secret-from-env"]
    assert not restants, restants


def test_le_lot_d_lit_les_jetons_au_coffre_d_abord():
    """forge_goap_online_launch interrogeait le coffre SEULEMENT si l'env etait vide (env d'abord) ;
    ollama_cloud_proxy_agent lisait OLLAMA_API_KEY et le jeton du hub dans l'env au chargement."""
    restants = ["%s:%s" % (rel, f["line"]) for rel in LOT_D for f in g.scan_file(os.path.join(_DEPOT, rel))
                if f["rule"] == "laforge-cloud-secret-from-env"]
    assert not restants, restants


def test_le_lot_c_outils_autonomes_lisent_le_jeton_du_hub_au_coffre_d_abord():
    restants = ["%s:%s" % (rel, f["line"]) for rel in LOT_C for f in g.scan_file(os.path.join(_DEPOT, rel))
                if f["rule"] == "laforge-cloud-secret-from-env"]
    assert not restants, restants


def test_le_lot_b_les_proxies_lisent_le_jeton_du_hub_au_coffre_d_abord():
    restants = ["%s:%s" % (rel, f["line"]) for rel in LOT_B for f in g.scan_file(os.path.join(_DEPOT, rel))
                if f["rule"] == "laforge-cloud-secret-from-env"]
    assert not restants, restants


def test_le_lot_a_lit_le_jeton_du_hub_au_coffre_d_abord():
    restants = ["%s:%s" % (rel, f["line"]) for rel in LOT_A for f in g.scan_file(os.path.join(_DEPOT, rel))
                if f["rule"] == "laforge-cloud-secret-from-env"]
    assert not restants, restants
