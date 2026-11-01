"""NR : `whoami` ne range plus parmi les « degrades » un pilier que la REGULATION a eteint, et ne conseille plus de le
redemarrer -- mais il le garde VISIBLE (derogation owner 30/10).

Mesure du 30/10 (journal NokidoLlamaKeeper 02 h 07-02 h 09) : le keeper eteint NokidoLlamaEmbed toutes les ~32 s
(« INUTILE : embed.wanted perime + 0 connexion ») ; whoami le classait « stopped » degrade et proposait « restart » --
suivre ce conseil relancerait la lutte contre la regulation. SLEEPING/DISABLED_BY_POLICY n'est pas DEAD. Le pilier
reste visible dans `piliers_endormis` avec son compteur (le battement a 25 redemarrages est un AUTRE defaut, a part).
La politique de fraicheur est celle du keeper (forge_llama_keeper._intention_voulue), jamais une copie.
"""
import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "app")]
from nokido_agent.app import forge_mcp_registry as R  # noqa: E402

SVCS = {"NokidoLlamaEmbed": {"status": "stopped", "restarts": 25},
        "NokidoLlamaReranker": {"status": "crashed", "restarts": 2},
        "NokidoSearxng": {"status": "stopped", "restarts": 1}}


def test_pilier_eteint_par_la_regulation_n_est_pas_degrade_mais_reste_visible():
    endormis = {"NokidoLlamaEmbed", "NokidoLlamaReranker"}
    deg = {d["service"] for d in R.whoami_degraded_services(SVCS, set(), endormis)}
    assert "NokidoLlamaEmbed" not in deg          # stopped par la regulation : pas une panne
    assert "NokidoLlamaReranker" in deg           # crashed : reste degrade, meme pilier endormi
    assert "NokidoSearxng" in deg                 # hors piliers : inchange
    vis = R.whoami_piliers_endormis(SVCS, endormis)
    assert vis == [{"service": "NokidoLlamaEmbed", "status": "stopped", "restarts": 25,
                    "motif": "eteint par la regulation (aucune intention fraiche)"}]


def test_pilier_reclame_mais_arrete_reste_degrade():
    deg = {d["service"] for d in R.whoami_degraded_services(SVCS, set(), set())}
    assert "NokidoLlamaEmbed" in deg              # intention fraiche (pas endormi) et arrete : vraie degradation


def test_les_endormis_suivent_la_politique_du_keeper():
    drapeaux = {"NokidoLlamaEmbed": "embed.wanted", "NokidoLlamaReranker": "rerank.wanted"}
    frais = {"rerank.wanted"}
    assert R.piliers_endormis_par_regulation(drapeaux, lambda d: d in frais) == {"NokidoLlamaEmbed"}
    assert R.piliers_endormis_par_regulation({}, lambda d: False) == set()


def test_whoami_branche_la_politique_du_keeper_et_publie_les_endormis():
    src = (RACINE / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    assert "piliers_endormis_par_regulation(" in src and "_DRAPEAU_PAR_SERVICE" in src and "_intention_voulue" in src
    assert '"piliers_endormis"' in src
    appels = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
              and getattr(n.func, "id", "") == "whoami_degraded_services"]
    assert any(len(a.args) >= 3 for a in appels), "whoami n'excuse pas les piliers endormis"
