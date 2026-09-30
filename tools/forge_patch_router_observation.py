"""Poser l'observation du routeur shadow SUR SON CANAL — `handle_rag` action=search.

DEFAUT MESURE le 2026-09-03. La chaine du routeur de recherche est complete et
CORRECTE : `forge_retrieval_router` en mode SHADOW (« calculee et journalisee,
jamais appliquee »), `observer()` qui ecrit `sandbox/router_observations.jsonl`,
`forge_router_replay` qui le consomme. Appelee a la main, elle marche : decision
rendue (`lexical 0.55 / vector 0.45`), 899 octets ecrits.

Mais le journal etait ABSENT, et `forge_router_replay` rendait `lues: 0`.

Cause : l'appel a `observer()` est pose dans `forge_rag_engine.RAGEngine.search()`
(L2141-2155), alors que `rag action=search` du hub passe par
`forge_mcp_registry.handle_rag` -> `_rag_dense_search`. **Un garde pose a cote de
son canal ne garde rien** — le motif du 2026-09-01, ici sur l'observabilite.

Trois hypotheses ecartees par la mesure AVANT d'accuser le cablage :
  - emetteur absent  -> non : `forge_rag_engine` l'appelle bien ;
  - hub non recharge -> non : hub demarre le 03/09 19:06, cablage du 01/09 20:59 ;
  - chaine cassee    -> non : appel direct = 899 o ecrits.
Puis un `rag search` REEL par le hub : le journal n'a pas bouge. C'est le chemin.

CE PATCH n'active RIEN. Le mode reste SHADOW : on observe ce que le routeur AURAIT
decide, on n'applique pas sa decision. La `RouteDecision` n'est pas branchee au
resultat — c'est deliberé, l'activation reste une DONNEE (`LAFORGE_ROUTER_MODE`).

L'`except` journalise en **WARNING**, pas en debug : le bloc d'origine loggait en
`debug`, invisible en production — un silence qui a masque le probleme tout ce
temps. Une observation qui echoue doit s'entendre.

Usage :
    python tools/forge_patch_router_observation.py           # dry-run
    run trusted_script tools/forge_patch_router_observation.py --apply
"""

__FORGE_COLOR__ = "cognition/observabilite-routage"

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CIBLE = ROOT / "app" / "forge_mcp_registry.py"
SENTINELLE = "observation shadow du routeur de recherche"

AVANT = (
    "                return await _aio.to_thread(self._rag_dense_search, topic, limit, "
    "bool(args.get(\"multi\")))\n"
)

APRES = (
    "                _res = await _aio.to_thread(self._rag_dense_search, topic, limit, "
    "bool(args.get(\"multi\")))\n"
    "                # observation shadow du routeur de recherche (2026-09-03).\n"
    "                # Le cablage vivait dans RAGEngine.search(), que CE chemin\n"
    "                # n'emprunte pas : le journal restait vide et le replay rendait\n"
    "                # `lues: 0`. SHADOW = on note ce que le routeur AURAIT decide,\n"
    "                # on n'applique rien. WARNING et non debug : un echec doit\n"
    "                # s'entendre, sinon on remesure ce silence dans six mois.\n"
    "                try:\n"
    "                    import time as _rt_time\n"
    "                    from forge_retrieval_router import decider as _rt_decider\n"
    "                    from forge_retrieval_router import observer as _rt_observer\n"
    "\n"
    "                    _rt_dec = _rt_decider(topic, {})\n"
    "                    _rt_observer(\n"
    "                        \"%d\" % int(_rt_time.time() * 1000), topic, _rt_dec, [],\n"
    "                        contexte={\"k\": limit, \"chemin\": \"handle_rag/_rag_dense_search\",\n"
    "                                  \"multi\": bool(args.get(\"multi\"))})\n"
    "                except Exception as _rt_e:  # noqa: BLE001\n"
    "                    import logging as _rt_log\n"
    "                    _rt_log.getLogger(__name__).warning(\n"
    "                        \"[router] observation shadow impossible (%r)\", _rt_e)\n"
    "                return _res\n"
)

NOTE = (
    "Verifier par l'EFFET, jamais par le rc : lancer un `rag action=search`, puis\n"
    "`tools/forge_router_replay.py` — il doit rendre `lues >= 1` avec\n"
    "chemin=handle_rag/_rag_dense_search. Un redemarrage du hub est necessaire :\n"
    "le module est charge en memoire."
)


def main(argv=None) -> int:
    from nokido_agent.tools.forge_patch_muted_paths import campagne
    return campagne(CIBLE, SENTINELLE, [(AVANT, APRES)],
                    suffixe="router_obs", note_finale=NOTE,
                    argv=sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
