# -*- coding: utf-8 -*-
"""NR -- les gels de boucle MESURES par forge_loop_sentinel ne reviennent pas (2026-10-01).

Journal de la sentinelle, 7 jours : 736 s de boucle du hub figee. Coupables traites :
porte d'admission (567 s), handle_query (45 s), list_providers (28 s), _all_tools (7 s),
chaine d'ancetres authz (7,6 s). Cliquet AST : ces appels synchrones ne reapparaissent pas
EN DIRECT dans une fonction `async` (ils y passent par asyncio.to_thread). Plus : le cache
d'ancetres evite la re-enumeration, et la sentinelle VOIT un pool to_thread sature.
"""
import ast
import asyncio
import importlib
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _appels_directs_en_async(fichier: str, cible: str) -> list:
    """Appels `cible(...)` / `x.cible(...)` poses DIRECTEMENT dans un `async def`
    (hors fonctions et lambdas imbriquees). Passer `cible` a to_thread n'est pas un appel."""
    arbre = ast.parse((ROOT / fichier).read_text(encoding="utf-8"))
    trouves = []

    def visiter(noeud, en_async):
        for enfant in ast.iter_child_nodes(noeud):
            if isinstance(enfant, (ast.FunctionDef, ast.Lambda)):
                visiter(enfant, False)
            elif isinstance(enfant, ast.AsyncFunctionDef):
                visiter(enfant, True)
            else:
                if en_async and isinstance(enfant, ast.Call):
                    f = enfant.func
                    nom = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                    if nom == cible:
                        trouves.append(enfant.lineno)
                visiter(enfant, en_async)
    visiter(arbre, False)
    return trouves


@pytest.mark.parametrize("fichier,cible", [
    ("app/forge_mcp_registry.py", "_check_res"),
    ("app/forge_mcp_registry.py", "_all_tools"),
    ("app/forge_mcp_registry.py", "_handle_query_sync"),
    ("app/forge_provider_admin.py", "list_providers"),
])
def test_aucun_appel_synchrone_mesure_en_direct_sur_la_boucle(fichier, cible):
    assert _appels_directs_en_async(fichier, cible) == [], (
        "%s appelle %s EN DIRECT dans une fonction async (lignes ci-dessus) : la boucle du "
        "hub se fige pendant l'appel -- passer par asyncio.to_thread" % (fichier, cible))


def test_handle_query_delegue_a_un_fil():
    arbre = ast.parse((ROOT / "app/forge_mcp_registry.py").read_text(encoding="utf-8"))
    defs = {n.name: n for n in ast.walk(arbre) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert isinstance(defs["handle_query"], ast.AsyncFunctionDef)
    assert isinstance(defs["_handle_query_sync"], ast.FunctionDef)
    assert "to_thread" in ast.unparse(defs["handle_query"])


def test_la_chaine_d_ancetres_n_est_pas_reenumeree(monkeypatch):
    az = importlib.import_module("nokido_agent.app.forge_authz_shadow")
    monkeypatch.setattr(az, "_CACHE_ANCETRES", {})
    appels = []

    class Proc:
        def __init__(self, pid):
            appels.append(pid)
            self.pid = pid

        def name(self):
            return "p.exe"

        def parent(self):
            return None

    faux = type("psutil", (), {"Process": Proc})
    assert az._chaine_ancetres(faux, 4242) == ["p.exe(4242)"]
    assert az._chaine_ancetres(faux, 4242) == ["p.exe(4242)"]
    assert appels == [4242], "le second appel a re-enumere au lieu de lire le cache"


def test_la_sentinelle_voit_un_pool_sature(monkeypatch):
    ls = importlib.import_module("nokido_agent.app.forge_loop_sentinel")
    monkeypatch.setattr(ls, "_POOL", {**ls._POOL, "ticks": 0, "satures": 0, "file_max": 0,
                                      "file_fenetre": 0, "journal_ts": 0.0})
    lache = threading.Event()

    async def scenario():
        boucle = asyncio.get_running_loop()
        boucle.set_default_executor(ThreadPoolExecutor(max_workers=1))
        occupe = asyncio.ensure_future(asyncio.to_thread(lache.wait, 5))
        en_attente = asyncio.ensure_future(asyncio.to_thread(lambda: None))
        await asyncio.sleep(0.2)
        ls._mesurer_pool(None)
        lache.set()
        await occupe
        await en_attente

    asyncio.run(scenario())
    pool = ls.stats()["pool"]
    assert pool["satures"] == 1 and pool["file_max"] >= 1 and pool["max_workers"] == 1
