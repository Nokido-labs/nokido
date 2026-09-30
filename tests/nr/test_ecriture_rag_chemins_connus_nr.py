r"""NR — l'inventaire des chemins qui ECRIVENT dans la base RAG est CONNU.

MESURE DU 2026-09-21. Trois routes d'ingestion ont recu `_admin_tok_ok` et
rendent 401 sans porteur -- prouve en runtime. Il serait faux d'en conclure que
la base RAG est protegee.

    POST /ingest/url      401   garde
    POST /ingest/bulk     401   garde
    POST /ingest/qualify  401   garde
    POST /api/ingest      ouverte (appelants internes sans porteur)
    POST /api/watch/create -> forge_watch_agent.create_job
                           -> 7 noeuds dont IngestAgent
                           -> ECRIT DANS LE RAG SANS PASSER PAR /ingest/*

=> PROTEGER UNE URL NE PROTEGE PAS UNE CAPACITE.

Ce NR ne garde donc pas une route : il garde la LISTE des chemins par lesquels
la capacite « ecrire dans la base RAG » est atteignable. Il est VERT sur l'etat
mesure, et il ROUGIT si un chemin apparait ou disparait sans qu'on le dise --
dans les DEUX sens, comme `test_route_authz_inventaire_nr` dont il reprend la
forme plutot que d'en inventer une autre.

POURQUOI PAS UN GARDE DE PLUS
=============================
`/api/watch/create` n'est PAS gardable en l'etat : l'UI du hub l'appelle en
`fetch` inline (nokido_hub.py:2181) SANS en-tete d'autorisation. L'armer
casserait l'interface -- « un 401 inattendu sur une route legitime est une
regression, pas une victoire ».

`/api/ingest` ne l'est pas non plus : ses deux appelants internes
(forge_clawhub_bridge:437, forge_dsl:229) n'envoient que `Content-Type`, et
`_admin_tok_ok` n'accepte un jeton propre que pour `_ADMIN_ORGANES`, qui ne
contient QUE `SUPERVISOR`. Les armer demanderait d'elargir cette liste ou de
leur donner le maitre -- or le maitre CONSERVE l'agent du header et son ring,
c'est-a-dire un passe-partout d'identite, precisement ce que la revue du
2026-09-18 a retire a l'interface web.

Ces deux points sont des DECISIONS, pas des oublis. Ce NR les rend visibles au
lieu de les laisser se reperdre.

MISE A JOUR 2026-09-26. La decision sur `/api/watch/create` a CHANGE le 2026-09-24
(ccae2830b, AUTH-3/4/6) : la route est enveloppee a l'ENREGISTREMENT par
`_garde_ui` (jeton admin OU session du portail + origine locale), son appelant
-- la page -- envoie ses identifiants `same-origin`, et l'attribution vient du
principal PROUVE, plus du champ `agent` du corps. Ce NR est reste rouge deux jours
faute d'avoir ete mis a jour : il le dit desormais par l'etat `GARDE_UI`, verifie
a l'enregistrement (le handler seul ne porte pas la garde).

CE QU'IL NE PROUVE PAS : il lit l'AST du depot. Qu'un chemin soit inventorie ne
dit rien de son comportement runtime, et l'inventaire ne couvre que ce que
l'analyse statique atteint -- un ecrivain passant par un module non nomme ici
lui echapperait. La borne est dite, elle n'est pas contournee.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: Chemins MESURES par lesquels la capacite « ecrire dans le RAG » est
#: atteignable depuis une requete HTTP. Chacun porte son etat de garde.
CHEMINS_ECRITURE_RAG = {
    "/ingest/url": "GARDE",
    "/ingest/bulk": "GARDE",
    "/ingest/qualify": "GARDE",
    "/api/ingest": "OUVERT",
    # via forge_watch_agent.IngestAgent ; garde posee a l'enregistrement (ccae2830b, 2026-09-24)
    "/api/watch/create": "GARDE_UI",
}

#: Le garde reutilise, dont le refus a ete mesure (401) le 2026-09-21.
_GARDE = "_admin_tok_ok"


def _racine() -> Path:
    for base in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[1]):
        if (base / "tools" / "nokido_hub.py").exists():
            return base
    raise AssertionError("racine du depot introuvable depuis ce test")


def _hub_src() -> str:
    return (_racine() / "tools" / "nokido_hub.py").read_text(encoding="utf-8")


def _handlers(src: str) -> dict:
    import re
    return {m.group(1): m.group(2) for m in re.finditer(r'Route\("([^"]+)",\s*(\w+)', src)}


def _enveloppes_ui(src: str) -> dict:
    """{route: handler interne} des routes enveloppees par `_garde_ui` A L'ENREGISTREMENT."""
    import re
    return {m.group(1): m.group(2) for m in re.finditer(r'Route\("([^"]+)",\s*_garde_ui\((\w+),', src)}


def _corps(src: str) -> dict:
    return {n.name: n for n in ast.walk(ast.parse(src))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _appelle(fn, cible: str) -> bool:
    if fn is None:
        return False
    for x in ast.walk(fn):
        if isinstance(x, ast.Call):
            nom = getattr(x.func, "attr", None) or getattr(x.func, "id", None)
            if nom == cible:
                return True
    return False


# ─────────────────────  L INVENTAIRE EST COMPLET  ─────────────────────────

def test_toutes_les_routes_inventoriees_existent_encore():
    """Un chemin qui disparait du hub doit se voir : l'inventaire deviendrait
    faussement rassurant en gardant une entree morte."""
    h = _handlers(_hub_src())
    manquantes = [r for r in CHEMINS_ECRITURE_RAG if r not in h]
    assert not manquantes, (
        "routes inventoriees ABSENTES du hub : %s. Si elles ont ete supprimees, "
        "retirer l'entree ; sinon le chemin a change de forme." % manquantes)


@pytest.mark.parametrize("route", [r for r, e in CHEMINS_ECRITURE_RAG.items() if e == "GARDE"])
def test_les_chemins_declares_GARDES_le_sont_reellement(route):
    src = _hub_src()
    fn = _corps(src).get(_handlers(src)[route])
    assert _appelle(fn, _GARDE), (
        "%s est inventoriee GARDE mais son handler n'appelle pas %s : "
        "l'inventaire ment sur l'etat reel" % (route, _GARDE))


@pytest.mark.parametrize("route", [r for r, e in CHEMINS_ECRITURE_RAG.items() if e == "GARDE_UI"])
def test_les_chemins_declares_GARDE_UI_sont_enveloppes_a_l_enregistrement(route):
    """La garde n'est PAS dans le handler : elle l'enveloppe dans `Route(...)`. Un
    retour a `Route(route, handler)` nu la retirerait sans toucher au handler."""
    src = _hub_src()
    assert route in _enveloppes_ui(src), (
        "%s est inventoriee GARDE_UI mais n'est plus enveloppee par _garde_ui a "
        "l'enregistrement : l'inventaire ment sur l'etat reel" % route)
    assert _appelle(_corps(src).get("_garde_ui"), _GARDE), (
        "_garde_ui n'appelle plus %s : re-mesurer ce qu'elle verifie" % _GARDE)


@pytest.mark.parametrize("route", [r for r, e in CHEMINS_ECRITURE_RAG.items() if e not in ("GARDE", "GARDE_UI")])
def test_les_chemins_declares_OUVERTS_le_sont_encore(route):
    """Symetrique, et c'est lui qui evite que le gain se reperde en silence :
    si l'un gagne une garde, TANT MIEUX -- mais l'inventaire doit le dire,
    sinon le chiffre cesse d'etre vrai. Meme contrat que
    `test_route_authz_inventaire_nr`."""
    src = _hub_src()
    fn = _corps(src).get(_handlers(src)[route])
    assert not _appelle(fn, _GARDE), (
        "%s est inventoriee OUVERT mais son handler appelle desormais %s. "
        "Mettre a jour CHEMINS_ECRITURE_RAG -- et verifier que ses appelants "
        "portent bien un jeton, sinon c'est une regression, pas un gain."
        % (route, _GARDE))


# ──────────────────  LE CONTOURNEMENT EST NOMME  ──────────────────────────

def test_le_chemin_indirect_passe_bien_par_une_chaine_d_agents():
    """LE COEUR. `/api/watch/create` n'ecrit pas elle-meme : elle cree une
    chaine dont un noeud ingere. C'est ce qui la rend invisible a un audit qui
    ne regarde que les `INSERT` du handler."""
    mod = _racine() / "app" / "forge_watch_agent.py"
    assert mod.exists(), "forge_watch_agent introuvable : le chemin indirect n'est plus mesurable"
    src = mod.read_text(encoding="utf-8")
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "create_job"),
              None)
    assert fn is not None, "create_job a disparu : re-mesurer le chemin indirect"
    corps = ast.unparse(fn)
    assert "IngestAgent" in corps, (
        "create_job ne cree plus de noeud IngestAgent : le chemin d'ecriture "
        "indirect a change, re-mesurer avant de conclure qu'il a disparu")
    assert "INSERT" in corps, "create_job n'insere plus : re-mesurer"


def test_l_attribution_du_job_vient_du_PRINCIPAL_prouve():
    """Jusqu'au 2026-09-24 : `agent = body.get("agent", "ADMIN_UI")` -- attribution
    DECLAREE par l'appelant (meme faute que `header_agent`), ENREGISTREE ici.
    Depuis ccae2830b elle vient du principal pose par `_garde_ui` depuis la preuve.
    Symetrique : un retour au champ du corps fait rougir ce test.
    """
    src = _hub_src()
    fn = _corps(src).get(_enveloppes_ui(src).get("/api/watch/create"))
    assert fn is not None, "handler interne de /api/watch/create introuvable : re-mesurer"
    corps = ast.unparse(fn).replace('"', "'")
    assert "principal" in corps, "l'attribution ne lit plus le principal prouve"
    assert "body.get('agent'" not in corps, (
        "l'attribution de /api/watch/create revient au corps de la requete : "
        "une attribution ne se declare pas")


def test_l_instrument_voit_une_garde_quand_il_y_en_a_une():
    """Un detecteur qui ne rend jamais rien est indistinguable d'un code sain."""
    nu = ast.parse("async def nu(r):\n    return 1\n").body[0]
    arme = ast.parse("async def a(r):\n    if not _admin_tok_ok(r):\n        return 401\n").body[0]
    assert _appelle(nu, _GARDE) is False
    assert _appelle(arme, _GARDE) is True
