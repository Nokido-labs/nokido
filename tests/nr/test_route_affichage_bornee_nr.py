# -*- coding: utf-8 -*-
"""Non-regression — une page ne doit pas attendre deux minutes un backend fige.

Mesure 2026-08-26 : `/api/agents` a depasse 25 s, apres avoir repondu en 73 ms puis en
5682 ms au cours de la meme session. La route appelle `list_providers`, qui SONDE les
backends LLM ; ollama etait fige (runner orphelin de 4,8 Go). Le client HTTP du portail
etait regle sur **120 s** pour tous les appels, sans distinction.

Le defaut n'est pas la lenteur du backend — c'est de la laisser traverser jusqu'a la
page. Deux minutes d'attente devant une interface ne sont jamais une reponse ; « je n'ai
pas pu savoir en 10 s » en est une.

Trois etats, comme partout : donnees / appel refuse (502) / backend trop lent (503, avec
la cause NOMMEE). Confondre les deux derniers envoie chercher un bug dans le registre
alors que le probleme est ailleurs.

Hermetique : AST et lecture, aucun appel reseau.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WIRED = ROOT / "app" / "web_hub" / "wired_routes.py"


@pytest.fixture(scope="module")
def source():
    if not WIRED.exists():
        pytest.skip("wired_routes.py absent de cette copie")
    return WIRED.read_text(encoding="utf-8", errors="replace")


def _fonction(source: str, nom: str):
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    return None


def _corps(source: str, nom: str) -> str:
    n = _fonction(source, nom)
    if n is None:
        pytest.skip("fonction %s absente" % nom)
    return "\n".join(source.splitlines()[n.lineno - 1:(n.end_lineno or n.lineno)])


def test_call_accepte_un_timeout(source):
    """Sans parametre, toute route herite du plafond historique de 120 s."""
    n = _fonction(source, "_call")
    assert n is not None, "_call introuvable"
    noms = [a.arg for a in n.args.args]
    assert "timeout" in noms, "_call doit exposer un timeout par appel"


def test_le_client_http_utilise_ce_timeout(source):
    """Un parametre non transmis serait un garde branche sur rien."""
    corps = _corps(source, "_call")
    assert "timeout=timeout" in corps, (
        "le timeout du parametre n'est pas passe au client HTTP")
    assert "timeout=120.0)" not in corps, "valeur codee en dur encore presente"


def test_agents_borne_son_appel(source):
    """LE test : la route d'affichage ne doit pas prendre le plafond de travail."""
    corps = _corps(source, "agents")
    assert "timeout=" in corps, "/api/agents appelle le hub sans borne"
    import re
    m = re.search(r"timeout=([0-9.]+)", corps)
    assert m, "borne illisible"
    assert float(m.group(1)) <= 15.0, (
        "borne de %s s : trop long pour une page" % m.group(1))


def test_agents_distingue_lent_de_refuse(source):
    """Confondre les deux envoie chercher un bug la ou il n'y en a pas."""
    corps = _corps(source, "agents")
    assert "503" in corps and "502" in corps, (
        "un backend trop lent (503) n'est pas un appel refuse (502)")
    assert "cause" in corps, "la cause doit etre nommee dans la reponse"


def test_agents_rend_une_forme_exploitable_meme_en_echec(source):
    """Le consommateur lit `agents` : l'omettre en cas d'echec casse la page."""
    corps = _corps(source, "agents")
    i = corps.find("except")
    assert i > 0, "aucune branche d'erreur"
    assert '"agents"' in corps[i:], (
        "la reponse d'erreur doit porter un `agents` vide, pas seulement un message")


def test_les_appels_de_travail_gardent_le_plafond(source):
    """Ne pas borner ce qui est LEGITIMEMENT long (ingestion, swarm) : ce test
    protege contre une correction trop zelee dans l'autre sens."""
    n = _fonction(source, "_call")
    defauts = n.args.defaults
    assert defauts, "_call doit garder une valeur par defaut"
    valeur = defauts[-1]
    assert isinstance(valeur, ast.Constant) and valeur.value >= 60, (
        "le defaut doit rester genereux pour les appels de travail")
