"""Tout chemin `github` du registre MCP lit le jeton au COFFRE avant l'environnement.

Paye DEUX FOIS sur le MEME fichier : `run action=github` corrige le 2026-09-03
(4c3ff5c363b6), puis `handle_github` -- oublie ce jour-la -- corrige le 2026-09-13.
Motif deja nomme dans RULES_SHARED : deux chemins pour la meme capacite, un seul lit
la politique du corps.

Ce que le trou coutait. L'environnement du process du hub est VIDE, donc l'appel
partait ANONYME ; or sur un depot PRIVE GitHub repond 404 et non 403, si bien qu'un
appel non authentifie et un acces refuse portent le MEME code. Des heures ont ete
passees a verifier un jeton, des scopes, une autorisation SSO et une appartenance
d'organisation qui etaient bons depuis le debut.

PORTEE DE LA PREUVE -- ce NR est STRUCTUREL, il ne prouve pas le runtime. Il lit le
module reel par AST (pas une regex : une mention n'est pas une structure) et verifie
l'ORDRE des deux sources dans chaque fonction qui construit une URL de l'API GitHub.
La contre-epreuve du bas montre qu'il REFUSE l'ancienne forme -- sans elle, rien ne
distinguerait ce test d'un test qui passe quoi qu'il arrive.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
MODULE = RACINE / "app" / "forge_mcp_registry.py"

_ANCRE = "api.github.com/repos/"


def _constantes(noeud: ast.AST):
    for n in ast.walk(noeud):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.value


def _lit_l_environnement(appel: ast.Call) -> bool:
    """`<quelque chose>.environ.get("GITHUB_TOKEN", ...)` -- et rien d'autre."""
    f = appel.func
    if not (isinstance(f, ast.Attribute) and f.attr == "get"):
        return False
    if not (isinstance(f.value, ast.Attribute) and f.value.attr == "environ"):
        return False
    return any(isinstance(a, ast.Constant) and a.value == "GITHUB_TOKEN"
               for a in appel.args)


def sites_github(source: str) -> dict[str, tuple[int | None, int | None]]:
    """Par fonction construisant une URL GitHub : (ligne du coffre, ligne de l'env)."""
    arbre = ast.parse(source)
    sites: dict[str, tuple[int | None, int | None]] = {}
    for fn in ast.walk(arbre):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_ANCRE in t for t in _constantes(fn)):
            continue
        # Le coffre peut etre importe sous un alias : on le resout, on ne le devine pas.
        alias = {"get_secret"}
        for n in ast.walk(fn):
            if isinstance(n, ast.ImportFrom):
                for a in n.names:
                    if a.name == "get_secret":
                        alias.add(a.asname or a.name)
        coffre = env = None
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            nom = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if nom in alias:
                coffre = n.lineno if coffre is None else min(coffre, n.lineno)
            elif _lit_l_environnement(n):
                env = n.lineno if env is None else min(env, n.lineno)
        sites[fn.name] = (coffre, env)
    return sites


@pytest.fixture(scope="module")
def sites() -> dict[str, tuple[int | None, int | None]]:
    if not MODULE.exists():
        pytest.fail("module introuvable : %s -- ce n'est pas 'aucun site'" % MODULE)
    return sites_github(MODULE.read_text(encoding="utf-8", errors="replace"))


def test_le_module_reel_expose_bien_plusieurs_chemins_github(sites):
    """Sans ce garde, un renommage ferait passer le test A VIDE -- donc au vert."""
    assert len(sites) >= 2, (
        "moins de 2 chemins GitHub reperes (%r) : l'ancre %r ne les capte plus, "
        "le test ne prouverait plus rien" % (sorted(sites), _ANCRE))


def test_chaque_chemin_github_lit_le_coffre_avant_l_environnement(sites):
    for nom, (coffre, env) in sorted(sites.items()):
        assert coffre is not None, (
            "%s construit une URL GitHub sans jamais consulter le coffre : l'appel "
            "part ANONYME et le 404 qui suit sera lu comme un refus d'acces" % nom)
        if env is not None:
            assert coffre < env, (
                "%s lit l'environnement (L%d) AVANT le coffre (L%d) : "
                "l'environnement est la couche qu'aucune rotation ne met a jour"
                % (nom, env, coffre))


def test_l_anonymat_est_NOMME_et_non_laisse_a_deviner(sites):
    """Un capteur ne rend pas la meme valeur pour deux causes distinctes."""
    source = MODULE.read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(source)
    vus = []
    for fn in ast.walk(arbre):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name not in sites:
            continue
        if any("ANONYME" in t for t in _constantes(fn)):
            vus.append(fn.name)
    assert vus, (
        "aucun chemin GitHub ne nomme le cas ANONYME : sur un depot prive, 404 "
        "signifie aussi bien 'mal forme' que 'acces refuse', et le message le tait")


# --- CONTRE-EPREUVE : le controle doit REFUSER l'ancienne forme -------------------
# Sans elle, les trois tests ci-dessus passeraient meme si `sites_github` etait faux.

_ANCIENNE_FORME = '''
import os as _os

async def handle_github(self, args, agent, ring):
    repo = args.get("repo", "")
    _h = {"User-Agent": "LaForge/1.0"}
    tok = _os.environ.get("GITHUB_TOKEN", "")
    if tok:
        _h["Authorization"] = f"token {tok}"
    base = f"https://api.github.com/repos/{repo}"
    return base
'''

_FORME_CORRIGEE = '''
import os as _os

async def handle_github(self, args, agent, ring):
    repo = args.get("repo", "")
    _h = {"User-Agent": "LaForge/1.0"}
    tok = ""
    try:
        from nokido_agent.app.forge_secrets import get_secret as _gs_gh
        tok = (_gs_gh("GITHUB_TOKEN") or "").strip()
    except Exception:
        pass
    if not tok:
        tok = _os.environ.get("GITHUB_TOKEN", "")
    if tok:
        _h["Authorization"] = f"token {tok}"
    base = f"https://api.github.com/repos/{repo}"
    return base
'''


def test_contre_epreuve_l_ancienne_forme_est_bien_REFUSEE():
    coffre, env = sites_github(_ANCIENNE_FORME)["handle_github"]
    assert coffre is None, "le controle croit voir un coffre la ou il n'y en a pas"
    assert env is not None, "le controle ne voit meme pas la lecture de l'environnement"


def test_contre_epreuve_la_forme_corrigee_est_bien_ACCEPTEE():
    coffre, env = sites_github(_FORME_CORRIGEE)["handle_github"]
    assert coffre is not None and env is not None
    assert coffre < env, "l'ordre coffre-puis-environnement n'est pas reconnu"
