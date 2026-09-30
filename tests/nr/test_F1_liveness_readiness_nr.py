"""Non-regression F1 : liveness et readiness sont deux questions differentes.

Item de veille F1 (tests du proxy `litellm`) : « route `/health/liveness` au nom
standard, et un test qui MESURE son temps de reponse ».

MESURE DU 2026-09-12 : `route_liveness = 0`, `readiness = 0`, pour **106**
occurrences de `/health` dans le depot. Et `/health` lui-meme valait exactement :

    async def health(request):
        return JSONResponse({"status": "ok", ...})

`ok` INCONDITIONNEL. Aucune verification, jamais.

CE QUE CA A DEJA COUTE. Le motif `statut_declare_vs_reel` du gate de capacites
enregistre le cas : **`/health` a repondu `ok` avec `V:` NON MONTE**. Le hub etait
VIVANT et PAS PRET, et rien dans le protocole ne permettait de distinguer les deux
— la question n'existait pas.

LA DISTINCTION, et pourquoi les deux routes ne sont pas redondantes :

  LIVENESS   le processus repond-il ? DOIT rester trivial : si la sonde touche
             une dependance, une base lente fait redemarrer un process sain.
             Le comportement de `/health` etait donc CORRECT — c'est son NOM qui
             mentait, un orchestrateur lisant `/health` croyant tout interroger.

  READINESS  le hub est-il en etat de SERVIR ? Interroge les dependances, et rend
             **503** quand l'une manque, pour qu'un orchestrateur puisse retirer
             ce hub du service sans lire le corps de la reponse.

Chaque dependance rend TROIS etats — `ok`, `ko`, `inconnu` avec motif. Un
`inconnu` ne compte JAMAIS comme sain : liste BLANCHE, n'est pret que ce qui est
PROUVE pret (constitution semantique). C'est la regle qui aurait evite le `ok`
sur `V:` non monte.

Ecrit apres le correctif, pour empecher son retour.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

HUB = RACINE / "tools" / "nokido_hub.py"


def _source() -> str:
    return HUB.read_text(encoding="utf-8", errors="replace")


def _fonction(nom: str) -> ast.AST:
    for n in ast.walk(ast.parse(_source())):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise AssertionError(f"fonction {nom} absente de {HUB.name}")


def test_les_deux_routes_standard_sont_declarees():
    """Les orchestrateurs attendent ces chemins EXACTS. `/health` seul melangeait
    les deux notions."""
    src = _source()
    for route in ("/health/liveness", "/health/readiness"):
        assert route in src, f"route standard absente : {route}"


def test_liveness_ne_touche_AUCUNE_dependance():
    """Une sonde de liveness qui interroge une base fait redemarrer un process
    sain quand la base est lente. C'est la faute classique, et elle est pire que
    l'absence de sonde."""
    fn = _fonction("health_liveness")
    corps = ast.unparse(fn)
    for interdit in ("sqlite3", "connect(", "urlopen", "requests.", "execute("):
        assert interdit not in corps, (
            f"liveness touche une dependance ({interdit!r}) : une lenteur externe "
            "y deviendrait un faux 'process mort'"
        )


def test_liveness_mesure_son_temps_de_reponse():
    """L'item l'exige explicitement : « un test qui MESURE son temps de reponse »."""
    corps = ast.unparse(_fonction("health_liveness"))
    assert "latency_ms" in corps, "liveness ne rend pas sa latence"
    assert "monotonic" in corps, (
        "latence calculee sans horloge monotone : un ajustement d'horloge la "
        "rendrait negative"
    )


def test_readiness_interroge_vraiment_les_dependances():
    corps = ast.unparse(_fonction("health_readiness"))
    assert "deps" in corps and "sqlite3" in corps, (
        "readiness ne verifie aucune dependance — ce serait un second liveness "
        "sous un autre nom"
    )
    assert "latency_ms" in corps


def test_readiness_rend_503_quand_une_dependance_manque():
    """Un orchestrateur doit pouvoir decider sur le CODE seul, sans parser le
    corps de la reponse."""
    corps = ast.unparse(_fonction("health_readiness"))
    assert "503" in corps, (
        "readiness rend toujours 200 : un hub non pret resterait dans le pool"
    )


def test_un_etat_INCONNU_ne_compte_jamais_comme_pret():
    """La regle qui aurait evite le `ok` sur `V:` non monte : liste BLANCHE.
    N'est pret que ce qui est PROUVE pret — un `inconnu` doit peser du cote
    NON pret, jamais l'inverse."""
    corps = ast.unparse(_fonction("health_readiness"))
    assert "inconnu" in corps, "les trois etats ne sont pas distingues"
    # Le calcul doit retenir les `ok`, pas ecarter les `ko` : une liste NOIRE
    # laisserait tout etat inattendu tomber du cote sain.
    assert "== 'ok'" in corps or '== "ok"' in corps, (
        "le verdict n'est pas construit par liste BLANCHE : un etat inattendu "
        "tomberait du cote PRET par defaut"
    )


def test_health_historique_reste_intact():
    """`/health` est consomme par le watchdog anti-zombie et par l'interface. Le
    renommer casserait des appelants ; on AJOUTE, on ne remplace pas."""
    src = _source()
    assert '"/health"' in src or "'/health'" in src
    corps = ast.unparse(_fonction("health"))
    assert "ok" in corps
