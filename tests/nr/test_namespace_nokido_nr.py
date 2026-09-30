#!/usr/bin/env python3
"""NR — le namespace `nokido_agent` tient dans le DEPOT autant que dans la wheel.

PHASE 5, prealable a toute reecriture d'import. Le codemod va produire des lignes
`from nokido_agent.app import forge_x` dans plus de 460 fichiers. Si le namespace
n'est pas importable DEPUIS LE CHECKOUT, la premiere famille migree casse le hub,
la CI, les hooks et les services — avant que le moindre benefice n'arrive,
puisque celui-ci n'existe qu'a l'installation.

POURQUOI `nokido_agent` ET PAS `nokido` — mesure du 2026-09-10, avant migration :
`tools/nokido.py` existe (« Entrypoint unifie Nokido, LE script a executer ») et
`app/Nokido.py` aussi. Comme `sys.path[0]` vaut `tools/` pour un script lance par
chemin, `import nokido` resolvait vers `tools/nokido.py` et `from nokido.app
import x` aurait echoue PARTOUT, avec un message designant la mauvaise cause.

Le test `test_le_namespace_choisi_n_entre_en_collision_avec_aucun_module` ci-dessous
est celui qui manquait : il aurait attrape la collision avant que je pose le
paquet. C'est le garde, pas la note, qui empeche la recidive.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
import tomllib
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git ls-files (l.238)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NAMESPACE = "nokido_agent"
ZONES = ("app", "tools", "recon_silo")


def _conf() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


# ------------------------------------------------------- COLLISION


def test_le_namespace_choisi_n_entre_en_collision_avec_aucun_module():
    """LE GARDE QUI MANQUAIT. Un paquet dont le nom existe deja comme module a
    plat est MASQUE des que sa zone precede la racine dans `sys.path` — ce qui est
    le cas de tout script lance par `python tools/x.py`.

    Windows etant insensible a la casse, la comparaison l'est aussi : `Nokido.py`
    et `nokido.py` entrent tous deux en collision avec un paquet `nokido`.
    """
    collisions = []
    for zone in ZONES:
        dossier = ROOT / zone
        if not dossier.is_dir():
            continue
        for chemin in dossier.glob("*.py"):
            if chemin.stem.lower() == NAMESPACE.lower():
                collisions.append(str(chemin.relative_to(ROOT)))
    assert not collisions, (
        f"le namespace `{NAMESPACE}` est masque par : {collisions}. "
        "Un script lance depuis cette zone importerait le MODULE, pas le paquet."
    )


def test_le_nom_ecarte_est_toujours_pris_donc_la_raison_tient():
    """Contre-epreuve de la decision : si `tools/nokido.py` disparaissait un jour,
    ce test le dirait — et le choix de `nokido_agent` pourrait etre reconsidere.
    Une decision datee doit pouvoir etre reouverte par une mesure, pas oubliee."""
    pris = (ROOT / "tools" / "nokido.py").exists() or (ROOT / "app" / "Nokido.py").exists()
    assert pris, (
        "ni tools/nokido.py ni app/Nokido.py n'existent plus : la collision qui a "
        "motive `nokido_agent` a disparu, le choix merite un reexamen"
    )


# --------------------------------------------------------- CHECKOUT


def test_le_namespace_s_importe_depuis_le_checkout():
    paquet = importlib.import_module(NAMESPACE)
    assert hasattr(paquet, "__version__")


def test_un_module_applicatif_est_atteignable_par_le_namespace():
    """La forme CIBLE doit marcher AVANT qu'on migre quoi que ce soit — sinon on
    migre vers une impasse."""
    mod = importlib.import_module(f"{NAMESPACE}.app.forge_python_bin")
    assert hasattr(mod, "LAFORGE_PYTHON")


def test_un_outil_est_atteignable_par_le_namespace():
    mod = importlib.import_module(f"{NAMESPACE}.tools.forge_pypi_contrat")
    assert mod.DISTRIBUTION == "nokido-agent"


def test_le_meme_module_par_les_deux_chemins_est_le_MEME_OBJET():
    """DEFAUT MESURE le 2026-09-10, et masque par ce test meme.

    La premiere version comparait une CONSTANTE :

        assert plat.LAFORGE_PYTHON == par_ns.LAFORGE_PYTHON   # toujours vrai

    Deux instances distinctes du meme fichier ont evidemment la meme constante.
    Le test passait pendant que la realite etait :

        plat  : forge_db_path                    id=2447687418880
        ns    : nokido_agent.app.forge_db_path   id=2447687423360
        MEME OBJET ? False

    Deux exemplaires du meme module = deux etats separes : caches, singletons,
    connexions, verrous. Mesure : `test_fts_rattrapage_incremental_nr` ouvrait
    DEUX connexions SQLite qui s'attendaient, et le gate pytest tombait en
    Timeout. Et tout `monkeypatch.setattr` sur une forme laissait l'autre intacte.

    On teste desormais l'IDENTITE. C'est la seule propriete qui compte pendant la
    coexistence des deux formes d'import.
    """
    sys.path.insert(0, str(ROOT / "app"))
    plat = importlib.import_module("forge_python_bin")
    par_ns = importlib.import_module(f"{NAMESPACE}.app.forge_python_bin")
    assert plat is par_ns, (
        f"DEUX instances du meme module : {id(plat)} vs {id(par_ns)} — "
        "tout etat (cache, singleton, connexion) serait duplique en silence"
    )


def test_l_identite_vaut_aussi_pour_un_module_a_etat():
    """Contre-epreuve sur un module qui PORTE de l'etat (connexions, chemins de
    base) : c'est la ou la duplication fait des degats, pas sur une constante."""
    sys.path.insert(0, str(ROOT / "app"))
    plat = importlib.import_module("forge_db_path")
    par_ns = importlib.import_module(f"{NAMESPACE}.app.forge_db_path")
    assert plat is par_ns


def test_l_identite_vaut_dans_les_deux_sens_d_import():
    """L'ordre ne doit pas decider : namespace d'abord puis plat doit donner le
    meme objet que l'inverse."""
    sys.path.insert(0, str(ROOT / "tools"))
    par_ns = importlib.import_module(f"{NAMESPACE}.tools.forge_pypi_contrat")
    plat = importlib.import_module("forge_pypi_contrat")
    assert plat is par_ns


def test_le_shim_ne_masque_pas_un_sous_module_deja_importe():
    """Le shim ne doit jamais ecraser une entree de `sys.modules`."""
    importlib.import_module(NAMESPACE)
    avant = sys.modules.get(f"{NAMESPACE}.app")
    importlib.reload(importlib.import_module(NAMESPACE))
    assert sys.modules.get(f"{NAMESPACE}.app") is avant


def test_reload_d_un_module_ponte_reexecute_bien_son_contenu(monkeypatch, tmp_path):
    """CONTRAT MANQUANT, mesure le 2026-09-13.

    Les tests ci-dessus verrouillent l'IDENTITE. Aucun ne disait ce que doit
    faire un RECHARGEMENT -- et `_PontIdentite.exec_module` rend `None`, donc
    `importlib.reload` sur un module ponte ne reexecute RIEN, sans lever la
    moindre erreur. C'est exact pour un import (le contenu a deja ete execute
    par `create_module`), et faux pour un reload.

    Mesure du jour : le SEUL pre-import de `nokido_agent.app.forge_access_switches`
    suffit a faire echouer `test_switches_db_isolee_nr::test_la_variable_isole_la_table`
    en 0,61 s, parce que la constante top-level n'est jamais recalculee.

    Un rechargement inerte est un GENERATEUR DE FAUX VERTS : un test qui
    recharge pour observer une reconfiguration passe sans rien verifier. Sur
    4594 fichiers scannes (0 illisible), 14 appels a reload existent, dont un
    NR de garde fail-closed et un site de PRODUCTION. Le contrat est donc
    double -- identite d'objet ET reexecution effective.

    DEUX TOURS, volontairement : un correctif qui ne marche qu'une fois n'en
    est pas un.
    """
    import forge_access_switches as plat

    ponte = importlib.import_module(f"{NAMESPACE}.app.forge_access_switches")
    assert ponte is plat, "l'identite d'objet reste acquise (contrats ci-dessus)"

    try:
        for tour in (1, 2):
            cible = tmp_path / ("tour%d.db" % tour)
            monkeypatch.setenv("LAFORGE_SWITCHES_DB_PATH", str(cible))
            recharge = importlib.reload(plat)
            assert recharge is plat, (
                "tour %d : le rechargement doit rendre le MEME objet" % tour)
            assert recharge.DEFAULT_DB_PATH == str(cible), (
                "tour %d : le fichier n'a PAS ete reexecute -- l'exec_module du "
                "pont est inerte" % tour)
            assert sys.modules["forge_access_switches"] is plat
            assert sys.modules[f"{NAMESPACE}.app.forge_access_switches"] is plat
            assert plat.__file__.replace("\\", "/").endswith(
                "app/forge_access_switches.py"), (
                "tour %d : le fichier reexecute doit rester celui du module plat"
                % tour)
    finally:
        # Retrait des DEUX clefs : sans quoi ce test laisserait le module
        # pointe sur un chemin temporaire et deviendrait lui-meme le pollueur
        # qu'il denonce. Le pont etant peut-etre inerte, un simple reload de
        # restauration ne suffirait pas -- c'est tout l'objet du test.
        monkeypatch.delenv("LAFORGE_SWITCHES_DB_PATH", raising=False)
        for _clef in ("forge_access_switches",
                      f"{NAMESPACE}.app.forge_access_switches"):
            sys.modules.pop(_clef, None)


# ---------------------------------------------------------- INSTALLE


def test_le_pyproject_declare_le_mapping_des_paquets():
    """Sans `package-dir`, la wheel ne contiendrait pas les sous-paquets : l'import
    marcherait ici et casserait une fois installe. C'est le piege exact de P4.2a —
    ce qui marche dans le checkout ne prouve rien sur l'installation."""
    st = _conf()["tool"]["setuptools"]
    mapping = st.get("package-dir", {})
    assert mapping.get(f"{NAMESPACE}.app") == "app"
    assert mapping.get(f"{NAMESPACE}.tools") == "tools"
    for attendu in (NAMESPACE, f"{NAMESPACE}.app", f"{NAMESPACE}.tools"):
        assert attendu in st.get("packages", []), f"{attendu} absent des packages"


def _inits_versionnes(zone: str) -> list[Path]:
    """Les `__init__.py` que le runner recevra REELLEMENT — vue git.

    `Path.rglob` voit le DISQUE ; une wheel n'embarque que ce que git versionne.
    Les deux vues divergent, et c'est le disque qui ment sur ce que le paquet
    contiendra : mesure du 2026-09-10, `app/rag/` (squelette d'avril, un
    `__init__.py` de docstring et rien d'autre) est capture par la regle
    `.gitignore` `RAG/` — insensible a la casse sous Windows — donc absent de
    tout clone propre. L'exiger dans la declaration CASSAIT le build de la
    wheel ; `pyproject.toml` a raison de l'omettre, et c'est ce garde-ci qui
    jugeait au mauvais endroit.

    Meme source de verite que `test_wheel_paquets_declares_nr._vue_git`, et
    meme regle sur le denominateur : vide = NON MESURABLE, jamais « sain ».
    """
    r = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(ROOT), "ls-files", "--", zone],
        capture_output=True, text=True, errors="replace", timeout=180)
    assert r.returncode == 0, f"git ls-files a echoue : {r.stderr[-300:]}"
    fichiers = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    assert fichiers, (
        f"aucun fichier suivi sous {zone}/ : denominateur VIDE, verdict non certifiant")
    return [ROOT / f for f in fichiers if f.endswith("/__init__.py")]


def test_la_liste_des_paquets_couvre_les_sous_paquets_reels():
    """CONTRE-EPREUVE du denominateur : une liste explicite se perime en silence.
    Chaque paquet VERSIONNE doit y figurer, sinon la wheel est amputee sans que
    rien n'echoue. « Versionne », et non « present sur le disque » : cf.
    `_inits_versionnes`."""
    declares = set(_conf()["tool"]["setuptools"].get("packages", []))
    manquants = []
    for zone in ("app", "tools"):
        base = ROOT / zone
        if not base.is_dir():
            continue
        for init in _inits_versionnes(zone):
            rel = init.parent.relative_to(base)
            nom = f"{NAMESPACE}.{zone}" + ("." + ".".join(rel.parts) if rel.parts else "")
            if any(p in {"_attic", "node_modules", "backups", "archive"} for p in rel.parts):
                continue
            if nom not in declares:
                manquants.append(nom)
    assert not manquants, f"sous-paquets reels absents de la declaration : {manquants}"


def test_les_entry_points_passent_par_le_namespace():
    scripts = _conf()["project"].get("scripts", {})
    assert scripts, "denominateur vide : aucun entry point declare"
    fautifs = [f"{n} -> {c}" for n, c in scripts.items() if not c.startswith(f"{NAMESPACE}.")]
    assert not fautifs, f"entry points hors namespace : {fautifs}"
