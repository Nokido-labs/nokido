"""
tests/conftest.py — Configuration globale pytest Nokido
=========================================================
- Force PYSIDE6 pour pytestqt
- Active le backend offscreen si pas de display (CI/SSH)
- Fournit les fixtures communes
"""
import os, sys

# Forcer isolation user-site pour eviter le bug anyio Roaming/Python/Python312
os.environ.setdefault("PYTHONNOUSERSITE", "1")

# Verifier qu'on tourne sous miniforge3 (Nokido canonical interpreter)
if "miniforge3" not in sys.executable.lower() and not os.environ.get("LAFORGE_TEST_ALLOW_ANY_PY"):
    import warnings
    warnings.warn(
        f"Tests should run under miniforge3, got {sys.executable}. "
        "Set LAFORGE_TEST_ALLOW_ANY_PY=1 to bypass."
    )

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP  = ROOT / "app"

# ── Paths ──────────────────────────────────────────────────────────────────
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP))

# ── Qt backend — forcer PySide6 ────────────────────────────────────────────
os.environ.setdefault("PYTEST_QT_API", "pyside6")

# ── Offscreen si pas de display (CI, SSH, MCP) ─────────────────────────────
# QT_QPA_PLATFORM=offscreen : rendu sans fenêtre visible
# Les widgets existent en mémoire, QTest fonctionne normalement
if not os.environ.get("DISPLAY") and sys.platform == "win32":
    # Windows n'a pas besoin de DISPLAY — laisser tel quel
    pass
elif not os.environ.get("DISPLAY") and sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ── Nokido.env ────────────────────────────────────────────────────────────
_env = ROOT / "Nokido.env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# ── Fixtures partagées ─────────────────────────────────────────────────────
import pytest

# ── Collecte PAR LISTE (suite pure de la CI locale) ──────────────────────────
# Mesure du 2026-09-29 (audit stabilite CI, mesures/audits/stabilite_ci.md) : ci_local passait
# ~900 fichiers en ARGUMENTS a pytest, et pytest re-parcourt tout le paquet `tests/nr` (~2 200
# entrees) pour CHACUN : collecte QUADRATIQUE -- 237 s contre 9,8 s avec un seul argument (Linux),
# 6 a 9 min sous Windows, qui poussaient le job GitHub `pytest-pur` au-dela de son plafond de 25 min.
# Desormais ci_local passe `tests` et la liste dans NOKIDO_CI_LISTE : on ecarte ICI, sans les
# importer, les fichiers de test absents de la liste (et les dossiers qui n'en contiennent aucun),
# puis on rejoue l'ORDRE declare. La variable est RETIREE a la configuration : un test qui relance
# pytest en sous-processus ne doit pas heriter du filtre.
_LISTE_CI: set | None = None
_DOSSIERS_CI: set = set()
_ORDRE_CI: dict = {}


def _rel_depot(p) -> str | None:
    """Chemin relatif au depot (posix) ; None hors du depot (tmp d'un meta-test : jamais filtre)."""
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return None


def pytest_configure(config):
    global _LISTE_CI, _DOSSIERS_CI, _ORDRE_CI
    chemin = os.environ.pop("NOKIDO_CI_LISTE", None)
    if not chemin:
        return
    lignes = [l.strip().replace("\\", "/") for l in
              Path(chemin).read_text(encoding="utf-8").splitlines() if l.strip()]
    _LISTE_CI = set(lignes)
    _ORDRE_CI = {l: i for i, l in enumerate(lignes)}
    _DOSSIERS_CI = {"/".join(l.split("/")[:k]) for l in lignes for k in range(1, l.count("/") + 1)}


def pytest_ignore_collect(collection_path, config):
    if _LISTE_CI is None:
        return None
    rel = _rel_depot(collection_path)
    if rel is None:
        return None
    if Path(collection_path).is_dir():
        return None if (rel in _DOSSIERS_CI or rel == "") else True
    # tout module hors liste, pas seulement `test_*.py` : `*_test.py` est aussi collecte par defaut.
    # Ecarter un module de la COLLECTE n'empeche pas un test liste de l'importer.
    if rel.endswith(".py") and Path(collection_path).name not in ("conftest.py", "__init__.py"):
        return None if rel in _LISTE_CI else True
    return None


def pytest_collection_modifyitems(session, config, items):
    if not _ORDRE_CI:
        return
    # tri STABLE : l'ordre des tests a l'interieur d'un fichier est conserve
    items.sort(key=lambda it: _ORDRE_CI.get(_rel_depot(it.path) or "", 10 ** 9))


@pytest.fixture(scope="session")
def nokido_root():
    """Chemin racine du projet."""
    return ROOT

@pytest.fixture(scope="session")
def nokido_db():
    """Chemin embeddings.db."""
    return ROOT / "RAG" / "embeddings.db"

@pytest.fixture(autouse=True)
def _isolate_endocrine_blood(tmp_path, monkeypatch):
    """AUCUN test n'ecrit dans le SANG DE PRODUCTION.

    Mesure le 2026-07-16 : la table `endocrine_signals` de la vraie base portait
    `ADRENALINE_HUB_PRESSURE` (fresh=0.800) et `HORMONE_FOCUS` avec `source=pytest`,
    residus vieux de 9 JOURS. La derniere valeur en production de l'adrenaline du hub
    avait donc ete posee par un TEST. Inoffensif au read -- le decay les ramene a
    0.000 -- mais c'est de la pollution du milieu interieur, et un lecteur qui
    utiliserait `fresh_level` verrait la valeur du test.

    On redirige l'ORGANE, pas la base entiere : poser `LAFORGE_DB` vers un temp
    isolerait TOUT le RAG et casserait les tests qui lisent des donnees reelles.
    `forge_endocrine._conn()` relit le global `DB` a chaque appel -- ce monkeypatch
    mord donc aussi sur le dual-write de `forge_hormones`, qui delegue a
    `forge_endocrine.release`.

    L'isolation est cote HARNAIS, pas cote organe : le code de production n'a pas a
    savoir qu'il est teste. Et `autouse` parce qu'elle ne doit PAS dependre du fait
    qu'un auteur de test y pense -- c'est precisement ce qui a manque pendant 9 jours.
    """
    try:
        import forge_endocrine as fe
    except Exception:
        return  # module absent de ce contexte de test -> rien a isoler
    monkeypatch.setattr(fe, "DB", tmp_path / "endocrine_test.db", raising=False)


@pytest.fixture(autouse=True)
def _isolate_postal(tmp_path, monkeypatch):
    """AUCUN test n'ecrit dans la VRAIE boite postale.

    Mesure le 2026-09-29 : depuis que l'approbation d'un depot de pair et la releve de
    ses reponses postent des accuses (`forge_postal.post`), trois NR qui isolaient la base
    M2M mais PAS la base postale (test_pair_quarantaine_nr, ..._geste_owner_nr,
    test_pair_mcp_nr) ont depose cinq courriers PAIR:CLIENT-A/B dans la boite REELLE de
    CLAUDE. Meme patron que le sang endocrinien ci-dessus : l'organe relit son global `DB`
    a chaque `_conn()`, on le redirige cote HARNAIS, sous ses DEUX noms d'import (deux
    noms = deux instances), et `autouse` pour ne pas dependre de la memoire de l'auteur.
    """
    for nom in ("forge_postal", "nokido_agent.app.forge_postal"):
        try:
            module = __import__(nom, fromlist=["DB"])
        except Exception:
            continue  # module absent de ce contexte de test -> rien a isoler
        monkeypatch.setattr(module, "DB", tmp_path / "postal_test.db", raising=False)


# ---------------------------------------------------------------------------
# PISTE FERMEE — ne pas la rouvrir sans mesure contradictoire (2026-09-13)
#
# Une fixture `autouse` a ete posee ici pour rendre les caches lourds au-dela de
# 1 200 Mo, le lot pur de la CI etant tue par le garde RSS vers 9-12 Go. DEUX
# versions ont ete mesurees sur le lot COMPLET :
#   1. `run_reclaimers(needed_gb=1.0)` -> inoperante pour DEUX raisons, chacune
#      suffisante : `_RECLAIMERS` ne contient que `lmstudio_models`
#      (`rag_dense_cache` n'est enregistre qu'a l'INSTANCIATION de ToolRegistry),
#      et la boucle casse des que `_free_now() >= needed_gb` -- la machine avait
#      6,59 Go libres ;
#   2. vidage direct de `_dense_cache` sur les instances vivantes -> 0 baisse de
#      RSS sur 9 292 tests.
#
# CE QUE LA MESURE A ETABLI, et qui ferme la piste : au moment ou le RSS atteint
# 2 568 Mo, `gc` ne voit AUCUN tableau numpy vivant et 1,79 M d'objets qui ne
# totalisent pas ces Go. La memoire n'est donc pas RETENUE par un objet Python :
# elle est allouee puis rendue par Python, et le heap n'est pas rendu a l'OS.
# [[scalene-sur-le-vivant-la-recette-2026-08-20]] l'avait deja dit pour la part
# native : sous Windows, ni scalene ni memray ne l'atteignent.
#
# Le remede n'est donc PAS un reclaim entre deux tests -- aucun ne peut rendre ce
# que Python a deja rendu -- mais l'isolation en PROCESSUS. A noter : xdist ne le
# fait pas non plus, il MULTIPLIE (4 workers = 13 998 Mo contre ~9 200 en
# sequentiel, mesure le meme jour).
# ---------------------------------------------------------------------------


def _piste_fermee_relache_les_caches_lourds():  # noqa: D401 - conserve, non cablee
    """Rend les caches que le corps sait deja rendre -- personne ne le lui demande ici.

    Mesure 2026-09-13 : le lot pur de la CI est tue par le garde RSS apres etre
    monte a 8,4 Go en 8 592 tests. La memoire n'est PAS du garbage (`gc.collect()`
    rend zero) : elle est RETENUE par `self._dense_cache` du registre MCP, que
    `_load_dense_cache` remplit avec toute la base vectorisee -- 595 832 chunks,
    dict `meta` plus matrice numpy de ~2,4 Go.

    Or ce cache a DEJA son liberateur : `register_reclaimer("rag_dense_cache", ...)`
    (`forge_mcp_registry`). En service, c'est le resource manager qui le declenche
    sous pression RAM. Sous pytest, ce declencheur n'existe pas : le reclaimer est
    ecrit, enregistre, et jamais appele -- un garde branche sur un signal que
    personne n'emet. On emet le signal, on n'ecrit pas un second mecanisme.

    Consequence mesurable attendue : les six fichiers les plus couteux du lot
    (1 991 a 647 Mo chacun EN CONTEXTE, mais 55 a 142 Mo joues SEULS) cessent
    d'heriter de la charge laissee par leurs predecesseurs.

    Le seuil evite de payer un reclaim a chaque test : en regime sain il ne tire
    jamais. Aucun chemin ne leve : un nettoyage qui echoue ne doit pas transformer
    un test vert en rouge, et son echec n'est pas le sujet du test en cours.
    """
    yield
    try:
        import psutil

        rss_mo = psutil.Process().memory_info().rss // 1048576
    except Exception:
        return  # sans mesure on ne decide rien : on s'abstient, on n'invente pas
    if rss_mo < _SEUIL_RECLAIM_MO:
        return

    # MESURE 2026-09-13, premiere version de cette fixture : elle appelait
    # `run_reclaimers(needed_gb=1.0)` et n'a rendu ZERO octet sur 9 292 tests.
    # Deux causes, toutes deux verifiees et toutes deux suffisantes :
    #   1. `_RECLAIMERS` ne contient que `lmstudio_models` -- `rag_dense_cache`
    #      n'est enregistre qu'a l'INSTANCIATION de ToolRegistry, pas a l'import ;
    #   2. `run_reclaimers` casse sa boucle des que `_free_now() >= needed_gb`,
    #      or la machine avait 6,59 Go libres.
    # J'avais donc branche un emetteur sans destinataire -- exactement le defaut
    # que cette fixture est censee corriger. On vise ici l'objet qui PORTE le
    # cache, sans dependre ni d'un singleton expose (il n'y en a pas) ni de la
    # politique globale de reclaim (qui deviderait aussi les modeles LM Studio,
    # sans rapport avec les tests).
    #
    # Le filtre sur le NOM de classe precede tout acces d'attribut : un getattr
    # aveugle sur `gc.get_objects()` declencherait les properties de n'importe
    # quel objet vivant.
    try:
        import gc

        for obj in gc.get_objects():
            if type(obj).__name__ != "ToolRegistry":
                continue
            if getattr(obj, "_dense_cache", None):
                obj._dense_cache = None
        gc.collect()
    except Exception:
        pass

@pytest.fixture(scope="session")
def events_db():
    """Chemin events.db."""
    return ROOT / "sandbox" / "events.db"

@pytest.fixture
def mcp_local_bridge():
    """Bridge MCP local (stdio) — pour tests d'intégration MCP."""
    from forge_desktop.core.mcp_connector import local_bridge
    return local_bridge()
