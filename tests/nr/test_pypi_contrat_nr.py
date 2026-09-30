#!/usr/bin/env python3
"""NR — le CONTRAT de distribution PyPI, ecrit AVANT toute transformation.

PHASE 1 du chantier PyPI. Ce fichier fixe ce que « Nokido est installable depuis
PyPI » veut dire, de facon REFUTABLE, avant qu'une seule ligne du corps ne bouge.

POURQUOI UN CONTRAT AVANT LE CODE. P3 avait ferme son contrat et pourtant P4.2a a
trouve trois ruptures : une commande `#egg=nom[extra]` que pip REFUSE, un module
`nokido` qui n'existe pas, et un corps qui s'importe a plat. Le controle etait
satisfait ; la promesse ne l'etait pas. Un contrat qui ne dit pas CE QU'IL FAUT
PROUVER laisse chacun prouver ce qu'il sait deja.

LA REGLE QUI COMMANDE (owner, 2026-09-10) :

    `pip install` qui reussit n'est PAS la preuve finale.

Une wheel peut s'installer parfaitement pendant que ses imports internes sont
casses. D'ou trois niveaux SEPARES, et jamais un seul booleen :

    INSTALL_OK      la distribution s'installe dans un venv neuf
    RUNTIME_OK      les points d'entree declares repondent hors checkout
    CAPABILITY_OK   une capacite REELLE s'execute, pas seulement `--help`

Un niveau NON MESURE reste `None`. Il ne devient jamais `False` (ce serait
accuser), et surtout jamais `True`.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

contrat = pytest.importorskip(
    "forge_pypi_contrat",
    reason="tools/forge_pypi_contrat.py pas encore ecrit — NR rouge attendu",
)


def _pyproject() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


# ------------------------------------------------------- IDENTITE


def test_le_contrat_nomme_la_distribution_et_elle_correspond():
    """Le nom du contrat n'est pas une opinion : il se confronte au pyproject."""
    assert contrat.DISTRIBUTION == "nokido-agent"
    assert _pyproject()["project"]["name"] == contrat.DISTRIBUTION


def test_les_commandes_publiques_du_contrat_sont_toutes_declarees():
    """Une commande promise et non declaree serait une promesse morte — exactement
    la classe de defaut que P4.2a a payee sur le README."""
    declarees = set(_pyproject()["project"].get("scripts", {}))
    manquantes = set(contrat.COMMANDES_PUBLIQUES) - declarees
    assert not manquantes, f"promises mais non declarees : {sorted(manquantes)}"


def test_chaque_point_d_entree_cible_un_module_qui_existe():
    """`nokido.tools.nokido_hub:main` doit designer un fichier REEL du depot.

    La resolution passe par `[tool.setuptools.package-dir]` : dans le depot,
    `nokido.tools.x` vit a `tools/x.py`. Chercher `nokido/tools/x.py` accuserait a
    tort — le mapping EST la realite, pas un detail de packaging.

    Un entry point qui pointe dans le vide s'installe parfaitement et casse au
    premier lancement : c'est la classe de defaut que P4.2a a payee.
    """
    conf = _pyproject()
    scripts = conf["project"].get("scripts", {})
    mapping = conf["tool"]["setuptools"].get("package-dir", {})

    def _resoudre(module: str) -> Path:
        # Le prefixe le plus SPECIFIQUE gagne : `nokido.tools` avant `nokido`.
        for prefixe in sorted(mapping, key=len, reverse=True):
            if module == prefixe or module.startswith(prefixe + "."):
                reste = module[len(prefixe):].lstrip(".")
                base = ROOT / mapping[prefixe]
                return base / Path(*reste.split(".")) if reste else base
        return ROOT / Path(*module.split("."))

    introuvables = []
    for nom, cible in scripts.items():
        chemin = _resoudre(cible.split(":", 1)[0])
        if not chemin.with_suffix(".py").exists() and not (chemin / "__init__.py").exists():
            introuvables.append(f"{nom} -> {cible} (cherche : {chemin})")
    assert not introuvables, f"entry points sans module : {introuvables}"


def test_les_entry_points_passent_par_le_namespace():
    """CONTRE-EPREUVE. Une cible `tools.x` s'installerait sans erreur puis
    casserait : le paquet `tools` de premier niveau n'existe PAS dans la wheel.

    Le nom du namespace se LIT dans le contrat, il ne se recopie pas ici : coder
    « nokido. » en dur a fait echouer ce test au changement de namespace, alors
    que le pyproject etait juste. Un test qui duplique la source de verite mesure
    sa propre copie.
    """
    scripts = _pyproject()["project"].get("scripts", {})
    assert scripts, "denominateur vide : aucun entry point declare"
    prefixe = contrat.NAMESPACE_CIBLE + "."
    fautifs = [f"{n} -> {c}" for n, c in scripts.items() if not c.startswith(prefixe)]
    assert not fautifs, f"entry points hors namespace {prefixe!r} : {fautifs}"


def test_aucune_cible_d_entry_point_n_est_une_coroutine():
    """DEFAUT MESURE le 2026-09-10, et ANTERIEUR a la migration.

    `nokido-hub` pointait `nokido_hub:main`, qui est un `async def`. Un
    `console_script` fait `sys.exit(cible())` : appeler une coroutine rend un
    objet, jamais un code de retour. Resultat, dans un venv neuf :

        <coroutine object main at 0x...>
        RuntimeWarning: coroutine 'main' was never awaited
        rc = 1

    Le point d'entree etait DECLARE, s'INSTALLAIT parfaitement, et n'a JAMAIS
    fonctionne. C'est exactement la classe de defaut que ce chantier existe pour
    attraper : presence != validite != preuve d'execution.

    Le controle se fait par AST : charger les modules pour le savoir aurait des
    effets de bord (le hub initialise son registre a l'import).
    """
    import ast
    conf = _pyproject()
    scripts = conf["project"].get("scripts", {})
    mapping = conf["tool"]["setuptools"].get("package-dir", {})
    assert scripts, "denominateur vide : aucun entry point declare"

    def _fichier(module: str) -> Path:
        for prefixe in sorted(mapping, key=len, reverse=True):
            if module == prefixe or module.startswith(prefixe + "."):
                reste = module[len(prefixe):].lstrip(".")
                base = ROOT / mapping[prefixe]
                return (base / Path(*reste.split("."))).with_suffix(".py")
        return (ROOT / Path(*module.split("."))).with_suffix(".py")

    coroutines = []
    for nom, cible in scripts.items():
        module, _, fonction = cible.partition(":")
        chemin = _fichier(module)
        if not chemin.exists():
            continue
        arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"),
                          filename=str(chemin))
        for noeud in arbre.body:
            if isinstance(noeud, ast.AsyncFunctionDef) and noeud.name == fonction:
                coroutines.append(f"{nom} -> {cible} (async def)")
    assert not coroutines, (
        "entry point(s) pointant une coroutine — `sys.exit(coroutine)` rend 1 "
        f"sans rien executer : {coroutines}"
    )


def test_l_extra_hub_existe():
    """Le contrat promet `nokido-agent[hub]` : l'extra doit exister, sinon pip
    l'ignore SILENCIEUSEMENT et installe un tronc sans le hub."""
    extras = _pyproject()["project"].get("optional-dependencies", {})
    assert contrat.EXTRA_REFERENCE in extras


# ------------------------------------------------- TROIS NIVEAUX


def test_les_trois_niveaux_sont_distincts_et_non_mesures_par_defaut():
    """Aucun niveau ne vaut PASS tant qu'il n'a pas ete mesure. `None` est le seul
    etat initial honnete : ni succes, ni accusation."""
    v = contrat.verdict_vierge()
    assert set(v) == {"INSTALL_OK", "RUNTIME_OK", "CAPABILITY_OK"}
    assert all(x is None for x in v.values())


def test_un_niveau_non_mesure_interdit_le_verdict_favorable():
    """CONTRE-EPREUVE CENTRALE. Installation reussie + runtime reussi, mais
    capacite JAMAIS mesuree : le global ne peut pas etre SUCCESS. C'est la regle
    terminale du mandat — STOP_NON_CERTIFIANT ne se convertit ni en FAIL ni en
    SUCCESS."""
    v = contrat.verdict_vierge()
    v["INSTALL_OK"] = True
    v["RUNTIME_OK"] = True
    global_, motif = contrat.trancher(v)
    assert global_ == "STOP_NON_CERTIFIANT"
    assert "CAPABILITY_OK" in motif


def test_un_niveau_en_echec_donne_FAIL_et_pas_STOP():
    """Symetrie : une mesure qui a REELLEMENT echoue n'est pas une absence de
    mesure. Confondre les deux effacerait un vrai defaut."""
    v = contrat.verdict_vierge()
    v["INSTALL_OK"] = False
    global_, _ = contrat.trancher(v)
    assert global_ == "FAIL"


def test_tout_vert_donne_SUCCESS():
    v = {"INSTALL_OK": True, "RUNTIME_OK": True, "CAPABILITY_OK": True}
    global_, _ = contrat.trancher(v)
    assert global_ == "SUCCESS"


def test_l_ordre_de_priorite_met_l_echec_avant_l_absence():
    """Un FAIL demontre prime sur un niveau non mesure : on ne cache pas un defaut
    derriere une mesure manquante."""
    v = {"INSTALL_OK": False, "RUNTIME_OK": None, "CAPABILITY_OK": None}
    assert contrat.trancher(v)[0] == "FAIL"


# ------------------------------------------------------- PIEGES


def test_le_contrat_n_exige_pas_un_import_nokido_inexistant():
    """PIEGE PAYE EN P3 : le README affirmait « the import path is `nokido` »
    alors qu'aucun module de ce nom n'existe. Le contrat ne doit exiger
    `import nokido` que si le namespace est REELLEMENT la — sinon il fabrique une
    exigence invraisemblable et fait echouer la mesure pour la mauvaise raison."""
    attendu = contrat.imports_publics_attendus(ROOT)
    if not (ROOT / "src" / "nokido").is_dir() and not (ROOT / "nokido").is_dir():
        assert "nokido" not in attendu, (
            "le contrat exige `import nokido` alors que le namespace n'existe pas"
        )


def test_le_contrat_dit_ce_qu_il_ne_couvre_pas():
    """Un contrat qui ne nomme pas ses angles morts se lit comme exhaustif."""
    assert contrat.HORS_PERIMETRE, "aucun angle mort declare"
    assert isinstance(contrat.HORS_PERIMETRE, tuple)


def test_le_denominateur_des_commandes_est_non_vide():
    """Regle owner : un instrument au denominateur vide est NON-CERTIFIANT. Si la
    liste des commandes se vidait, tous les controles passeraient en silence."""
    assert len(contrat.COMMANDES_PUBLIQUES) >= 5


# ------------------------------------------- SEQUENCE DE PUBLICATION
#
# Correction owner du 2026-09-10 : « toute publication publique sur pypi.org est
# INTERDITE tant que le cycle TestPyPI n'a pas ete execute et certifie ».


def test_la_publication_commence_par_testpypi():
    """L'ordre est structurel, pas une preference : une version publiee sur PyPI
    ne peut JAMAIS etre re-uploadee. TestPyPI est le seul endroit ou un defaut se
    paie sans consequence irreversible."""
    assert contrat.SEQUENCE_PUBLICATION[0] == "testpypi"
    assert contrat.SEQUENCE_PUBLICATION[-1] == "pypi"


def test_pypi_refuse_si_une_propriete_testpypi_est_non_mesuree():
    """GATE. Installation et runtime verts, mais independance au checkout jamais
    verifiee : la publication publique est refusee. Une propriete NON MESUREE
    n'est pas une propriete acquise."""
    temoin = contrat.temoin_publication_vierge("testpypi")
    for cle in temoin:
        if cle != "checkout_independant":
            temoin[cle] = "mesure"
    temoin["checkout_independant"] = None
    ok, motif = contrat.gate_testpypi(temoin)
    assert ok is False
    assert "checkout_independant" in motif


def test_pypi_refuse_si_une_propriete_testpypi_est_en_echec():
    temoin = {c: "mesure" for c in contrat.temoin_publication_vierge("testpypi")}
    temoin["capacite_executee"] = False
    ok, motif = contrat.gate_testpypi(temoin)
    assert ok is False
    assert "capacite_executee" in motif


def test_un_temoin_testpypi_complet_autorise_pypi():
    temoin = {c: "mesure" for c in contrat.temoin_publication_vierge("testpypi")}
    ok, _ = contrat.gate_testpypi(temoin)
    assert ok is True


def test_le_temoin_de_publication_a_un_denominateur_non_vide():
    """Un temoin sans champ requis validerait tout. Regle owner : denominateur
    vide = NON-CERTIFIANT."""
    champs = contrat.temoin_publication_vierge("testpypi")
    assert len(champs) >= 7
    for requis in ("version", "artefact_sha256", "source_installation",
                   "capacite_executee", "checkout_independant"):
        assert requis in champs


def test_les_options_qui_masqueraient_le_defaut_sont_nommees_et_interdites():
    """`--no-index` ou un `--find-links` vers le depot feraient reussir
    l'installation en la nourrissant du checkout — c'est-a-dire en mesurant
    exactement ce qu'on veut exclure."""
    for interdite in ("--no-index", "--find-links"):
        assert any(interdite in x for x in contrat.OPTIONS_PIP_INTERDITES)


def test_une_divergence_contrat_pyproject_est_detectee():
    """CONTRE-EPREUVE de l'instrument lui-meme : il doit SAVOIR dire non."""
    faux = {"project": {"name": "autre-chose", "scripts": {}}}
    ecarts = contrat.confronter(faux)
    assert ecarts, "une divergence flagrante n'a pas ete detectee"
