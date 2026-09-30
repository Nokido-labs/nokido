#!/usr/bin/env python3
"""test_entry_points_synchrones_nr.py — un console_script ne peut pas viser un `async def`.

INCIDENT GARDE, mesure du 2026-09-10 dans un venv NEUF hors checkout :

    $ nokido-hub --help
    <coroutine object main at 0x...>
    RuntimeWarning: coroutine 'main' was never awaited
    rc = 1

`nokido_hub.main` est un `async def`. Un console_script genere par setuptools fait
`sys.exit(cible())` : appeler une coroutine rend un OBJET, jamais un code de retour.
L'entry point etait DECLARE, s'INSTALLAIT parfaitement, et n'avait JAMAIS ete execute
depuis une installation — d'ou le contrat a trois niveaux de la phase 8 : INSTALL_OK
ne dit RIEN de RUNTIME_OK. Le correctif est le shim synchrone `tools/nokido_hub_cli.py` ;
CE fichier est ce qui empeche la regression de revenir par un simple changement de cible.

CE QUE CE NR NE FAIT PAS — et pourquoi. Il n'IMPORTE aucune cible : importer
`nokido_hub` initialise des registres et journalise (« registre agent_identities.json
ILLISIBLE »). Un garde ne demarre pas ce qu'il inspecte. La lecture est donc AST, sans
execution — et elle rend TROIS etats et non deux : une cible qu'on n'a pas pu lire est
`ILLISIBLE`, jamais « saine par defaut ».
"""
from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
PYPROJECT = RACINE / "pyproject.toml"

SYNC, ASYNC, ABSENTE, NON_ANALYSABLE, ILLISIBLE = (
    "SYNC", "ASYNC", "ABSENTE", "NON_ANALYSABLE", "ILLISIBLE")


# --------------------------------------------------------------------------- pur
def nature_de_la_cible(source: str, attribut: str) -> str:
    """Nature du symbole `attribut` au niveau module, LU et jamais execute.

    Rend SYNC / ASYNC / ABSENTE / NON_ANALYSABLE. Fonction PURE : elle prend le
    texte du module, pas un chemin — elle se teste sans toucher au disque.
    """
    if "." in attribut:          # `mod:Cls.methode` — hors de portee, on le DIT
        return NON_ANALYSABLE
    try:
        arbre = ast.parse(source)
    except SyntaxError:
        return NON_ANALYSABLE
    for noeud in arbre.body:
        if isinstance(noeud, ast.AsyncFunctionDef) and noeud.name == attribut:
            return ASYNC
        if isinstance(noeud, ast.FunctionDef) and noeud.name == attribut:
            return SYNC
        # `main = _autre_chose` : une affectation ne prouve pas la synchronie
        if isinstance(noeud, ast.Assign) and any(
                isinstance(c, ast.Name) and c.id == attribut for c in noeud.targets):
            return NON_ANALYSABLE
    return ABSENTE


def fichier_de_la_cible(module: str, paquets: dict[str, str]) -> Path | None:
    """Resout `nokido_agent.tools.nokido_hub_cli` vers son fichier DANS LE DEPOT.

    Le mapping vient de `[tool.setuptools.package-dir]` du pyproject : on ne
    code pas en dur une correspondance que le paquet declare lui-meme.
    """
    for prefixe in sorted(paquets, key=len, reverse=True):
        if module == prefixe or module.startswith(prefixe + "."):
            reste = module[len(prefixe):].lstrip(".")
            base = RACINE / paquets[prefixe]
            chemin = base.joinpath(*reste.split(".")) if reste else base
            return chemin.with_suffix(".py")
    return None


def _scripts_et_paquets() -> tuple[dict[str, str], dict[str, str]]:
    donnees = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    scripts = donnees.get("project", {}).get("scripts", {})
    paquets = donnees.get("tool", {}).get("setuptools", {}).get("package-dir", {})
    return scripts, paquets


# ---------------------------------------------------------------- niveau unitaire
def test_la_fonction_distingue_sync_async_et_absent():
    """Le garde doit MORDRE : sans ce test, un predicat toujours SYNC passerait."""
    assert nature_de_la_cible("def main():\n    return 0\n", "main") == SYNC
    assert nature_de_la_cible("async def main():\n    return 0\n", "main") == ASYNC
    assert nature_de_la_cible("def autre():\n    pass\n", "main") == ABSENTE
    assert nature_de_la_cible("main = 3\n", "main") == NON_ANALYSABLE
    assert nature_de_la_cible("def main(:\n", "main") == NON_ANALYSABLE


def test_le_temoin_historique_est_bien_vu_comme_fautif():
    """`nokido_hub.main` EST un `async def` : si l'entry point y revient, rouge.

    C'est la cible exacte que le pyproject portait avant le 2026-09-10. Le jour
    ou elle est saisie a nouveau, le test au-dessus doit echouer — on le prouve
    ici sur le fichier REEL, pas sur une chaine fabriquee.
    """
    hub = RACINE / "tools" / "nokido_hub.py"
    if not hub.exists():
        pytest.skip(f"temoin absent : {hub}")          # absence DITE, pas avalee
    assert nature_de_la_cible(hub.read_text(encoding="utf-8", errors="replace"),
                              "main") == ASYNC, (
        "nokido_hub.main n'est plus un async def : ce temoin ne prouve plus rien, "
        "le rendre a nouveau discriminant avant de le supprimer")


# ------------------------------------------------------------- niveau integration
def test_tout_console_script_declare_vise_un_callable_synchrone():
    scripts, paquets = _scripts_et_paquets()

    # Denominateur AFFIRME : une lecture qui rend zero entry point serait un
    # garde MUET qui paraitrait rigoureux (mesure du 2026-09-10 sur un scan vide).
    assert len(scripts) >= 1, f"aucun [project.scripts] lu dans {PYPROJECT}"
    assert paquets, "[tool.setuptools.package-dir] absent : resolution impossible"

    fautifs: list[str] = []
    illisibles: list[str] = []
    vus = 0

    for nom, cible in scripts.items():
        module, _, attribut = cible.partition(":")
        fichier = fichier_de_la_cible(module, paquets)
        if fichier is None:
            illisibles.append(f"{nom} -> {cible} (module hors package-dir)")
            continue
        try:
            source = fichier.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            illisibles.append(f"{nom} -> {fichier.name} ({type(exc).__name__})")
            continue
        vus += 1
        nature = nature_de_la_cible(source, attribut)
        if nature in (ASYNC, ABSENTE):
            fautifs.append(f"{nom} = {cible} -> {nature}")

    assert not fautifs, (
        "console_script(s) inexecutable(s) — un `async def` rend une coroutine, "
        "jamais un code de retour, et une cible absente casse a l'installation :\n  "
        + "\n  ".join(fautifs))
    assert vus == len(scripts), (
        f"couverture incomplete : {vus}/{len(scripts)} cibles lues, "
        f"non lues = {illisibles}")


def test_le_shim_du_hub_repond_sans_importer_le_hub():
    """`--help` ne doit RIEN demarrer : l'import du hub est TARDIF, dans main()."""
    shim = RACINE / "tools" / "nokido_hub_cli.py"
    assert shim.exists(), f"shim absent : {shim}"
    arbre = ast.parse(shim.read_text(encoding="utf-8", errors="replace"))

    au_niveau_module = {
        alias.name for noeud in arbre.body if isinstance(noeud, ast.Import)
        for alias in noeud.names
    } | {
        noeud.module for noeud in arbre.body
        if isinstance(noeud, ast.ImportFrom) and noeud.module
    }
    interdits = {n for n in au_niveau_module if n and "nokido_hub" in n and "cli" not in n}
    assert not interdits, (
        f"le hub est importe au niveau module ({interdits}) : `--help` initialiserait "
        "des registres et journaliserait. L'import doit rester dans main().")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
