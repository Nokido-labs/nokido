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

# Un process de test n'est jamais proprietaire de l'echantillonnage du corps (19/10) : en CI de reference, sans etat
# publie, get_snapshot() le rendait proprietaire et le sampler spawnait arbitrage/eviction DANS pytest. Une valeur
# explicite de l'appelant prime. NR tests/nr/test_sampler_muet_sous_pytest_nr.py.
os.environ.setdefault("LAFORGE_SAMPLER_AUTOSTART", "0")

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
import itertools

import pytest

# ── Doubles de modules : sys.modules ET l'attribut du paquet (2026-10-20) ────
# `from paquet import sous_module` lit d'abord l'ATTRIBUT du paquet : si un voisin de worker xdist a deja
# importe le vrai module, un double pose dans sys.modules seul est contourne (3 rouges de la CI de reference
# 0c9c4e4d0, verts seuls). setitem sur sys.modules pose donc aussi l'attribut du paquet parent, defait avec lui.
_setitem_monkeypatch = pytest.MonkeyPatch.setitem


def _setitem_avec_attribut(self, dic, name, value):
    _setitem_monkeypatch(self, dic, name, value)
    if dic is sys.modules and isinstance(name, str) and "." in name:
        parent, _, enfant = name.rpartition(".")
        if sys.modules.get(parent) is not None:
            self.setattr(sys.modules[parent], enfant, value, raising=False)


pytest.MonkeyPatch.setitem = _setitem_avec_attribut

# ── Collecte PAR LISTE (suite pure de la CI locale) ──────────────────────────
# Mesure du 2026-09-29 (audit stabilite CI, mesures/audits/stabilite_ci.md) : ci_local passait
# ~900 fichiers en ARGUMENTS a pytest, et pytest re-parcourt tout le paquet `tests/nr` (~2 200
# entrees) pour CHACUN : collecte QUADRATIQUE -- 237 s contre 9,8 s avec un seul argument (Linux),
# 6 a 9 min sous Windows, qui poussaient le job GitHub `pytest-pur` au-dela de son plafond de 25 min.
# Desormais ci_local passe `tests` et la liste dans NOKIDO_CI_LISTE : on ecarte ICI, sans les
# importer, les fichiers de test absents de la liste (et les dossiers qui n'en contiennent aucun),
# puis on rejoue l'ORDRE declare. La variable est RETIREE a la configuration : un test qui relance
# pytest en sous-processus ne doit pas heriter du filtre.
#
# xdist (2026-10-14) : la variable etant retiree AVANT que xdist lance ses workers, ceux-ci ne
# l'avaient jamais -- et ci_local retombait, en --turbo, sur les ~1 100 fichiers en arguments.
# Mesure ce jour-la (`ci_local --only pytest --turbo --turbo-workers 3`) : chaque worker a passe
# PLUS DE 10 MIN en collecte (13 M d'operations de metadonnees, zero lecture, aucun test importe)
# avant d'etre arrete ; la calibration mesurait la collecte quadratique, pas le parallelisme.
# Le controleur transmet donc le chemin a chaque worker par le canal de xdist (`workerinput`,
# pose avant la configuration du worker), jamais par l'environnement.
_LISTE_CI: set | None = None
_DOSSIERS_CI: set = set()
_ORDRE_CI: dict = {}
_CHEMIN_CI: str | None = None
_CLE_XDIST = "nokido_ci_liste"


def _rel_depot(p) -> str | None:
    """Chemin relatif au depot (posix) ; None hors du depot (tmp d'un meta-test : jamais filtre)."""
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return None


# ── Plantage NATIF d'un worker : la trace part dans un FICHIER (2026-10-14) ───
# Mesure du jour : un worker xdist est mort sans aucune trace (« node down: Not properly terminated ») et le journal
# Windows compte 15 plantages de `envs\laforge_py314\python.exe` dans `pyarrow\arrow.dll` (0xc0000005) depuis
# minuit. Le faulthandler natif de pytest ecrit sur le stderr du worker, qu'on ne relit pas. Quand ci_local pose
# NOKIDO_FAULTHANDLER_DIR, chaque processus (worker ou principal) y ouvre son fichier : un prochain plantage natif y
# laissera la pile Python de TOUS les threads, et ci_local la montre a la fin du run.
_FAULTHANDLER_FICHIER = None


def _armer_faulthandler(config) -> str | None:
    global _FAULTHANDLER_FICHIER
    dossier = os.environ.get("NOKIDO_FAULTHANDLER_DIR")
    if not dossier:
        return None
    import faulthandler
    qui = (getattr(config, "workerinput", None) or {}).get("workerid", "principal")
    try:
        Path(dossier).mkdir(parents=True, exist_ok=True)
        chemin = Path(dossier) / ("faulthandler_%s_%d.log" % (qui, os.getpid()))
        _FAULTHANDLER_FICHIER = open(chemin, "w", encoding="utf-8")  # garde OUVERT : faulthandler y ecrit au crash
        faulthandler.enable(file=_FAULTHANDLER_FICHIER, all_threads=True)
        return str(chemin)
    except OSError:
        return None  # le dossier illisible n'empeche pas la suite : ci_local le dira (aucun fichier)


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    global _LISTE_CI, _DOSSIERS_CI, _ORDRE_CI, _CHEMIN_CI
    # trylast : APRES le faulthandler natif de pytest, qui reecrirait sinon la cible vers le stderr du worker.
    _armer_faulthandler(config)
    chemin = (os.environ.pop("NOKIDO_CI_LISTE", None)
              or (getattr(config, "workerinput", None) or {}).get(_CLE_XDIST))
    if not chemin:
        return
    _CHEMIN_CI = chemin
    lignes = [l.strip().replace("\\", "/") for l in
              Path(chemin).read_text(encoding="utf-8").splitlines() if l.strip()]
    _LISTE_CI = set(lignes)
    _ORDRE_CI = {l: i for i, l in enumerate(lignes)}
    _DOSSIERS_CI = {"/".join(l.split("/")[:k]) for l in lignes for k in range(1, l.count("/") + 1)}


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node):
    """Controleur xdist : chaque worker recoit le chemin de la liste avant sa propre configuration."""
    if _CHEMIN_CI:
        node.workerinput[_CLE_XDIST] = _CHEMIN_CI


def pytest_runtest_logreport(report):
    """Garde TDD « rouge d'abord » (owner 2026-10-16) : un test en ECHEC (phase call) est note dans le registre des
    rouges que lit governed_edit (tools/forge_governed_edit.avertissement_tdd). Jamais bloquant : un registre
    illisible ne change pas l'issue du test, il fait seulement que l'avertissement n'est pas leve."""
    if getattr(report, "when", "") != "call" or not getattr(report, "failed", False):
        return
    import json as _j
    import time as _t

    chemin = Path(os.environ.get("LAFORGE_TDD_ROUGES")
                  or (Path(__file__).resolve().parents[1] / "sandbox" / "workspace" / "tdd_rouges.jsonl"))
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("a", encoding="utf-8") as f:
            f.write(_j.dumps({"ts": _t.time(), "nodeid": report.nodeid,
                              "fichier": str(getattr(report, "fspath", ""))}, ensure_ascii=False) + "\n")
    except OSError:  # muet-ok : registre illisible = avertissement non leve, jamais un test casse
        pass


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

@pytest.fixture(scope="session")
def _bac_des_organes(tmp_path_factory):
    """UN repertoire pour toute la session, ou vivent les bases isolees des organes.

    Mesure du 2026-10-06 (CI de reference 741c65341) : les deux isolations autouse ci-dessous
    demandaient `tmp_path`, donc un REPERTOIRE NEUF pour chacun des ~13 600 tests -- pour
    calculer le chemin d'une base que presque aucun test n'ecrit. `test_tous_modules_nr`
    (5 079 tests triviaux, aucun au-dela de 0,3 s) coutait 42 s, ~8 ms de surcout par test,
    avec ou sans pytest-timeout. L'isolation reste PAR TEST : un nom de fichier unique par
    test dans ce repertoire, et le fichier n'existe que si le test ecrit.
    """
    return tmp_path_factory.mktemp("organes_isoles")


@pytest.fixture
def tmp_path(tmp_path_factory, request):
    """tmp_path en O(1) (19/10, 2 pre-controles tues) : celui de pytest cherche son numero en balayant TOUT le basetemp,
    qui grossit d'un dossier par test -- O(n2) sur la suite pure sans xdist, Timeout 30 s dans os.scandir sous
    contention disque. Ici : mkdtemp direct dans le basetemp, sans aucun balayage.

    Dossier COURT (20/10, CI de reference 477e02f93 : « '$GIT_DIR' too big ») : « pytest » + 14 car. du nom + « _ » + 8
    = 29 car., sous les ~31 du defaut -- le lot `pytest_tXX/` et un nom a 30 car. passaient MAX_PATH dans le worktree
    profond de la reference. Le prefixe « pytest » garde le segment qu'exige forge_secrets._coffre_test sous --turbo
    (basetemp `bt`, workers `popen-gwN`)."""
    import re as _re
    import tempfile
    from pathlib import Path as _Path

    nom = _re.sub(r"\W", "_", request.node.name)[:14]
    return _Path(tempfile.mkdtemp(prefix="pytest" + nom + "_", dir=tmp_path_factory.getbasetemp()))


@pytest.fixture(scope="session", autouse=True)
def _plafond_git(tmp_path_factory):
    """Aucun git lance sous un tmp de test ne remonte au depot Nokido (19/10, CI de reference : le basetemp vit DANS
    l'arbre sous le compte du hub ; `git status -uall` dans un wt non initialise balayait le depot entier et tenait
    son index.lock). Interrupteur global, lu par chaque git fils."""
    base = str(tmp_path_factory.getbasetemp())
    ancien = os.environ.get("GIT_CEILING_DIRECTORIES")
    os.environ["GIT_CEILING_DIRECTORIES"] = os.pathsep.join(p for p in (base, ancien) if p)
    yield
    if ancien is None:
        os.environ.pop("GIT_CEILING_DIRECTORIES", None)
    else:
        os.environ["GIT_CEILING_DIRECTORIES"] = ancien


_COMPTEUR_DE_TESTS = itertools.count()


@pytest.fixture
def _numero_de_test():
    """Un numero par test, commun aux deux bases isolees du meme test."""
    return next(_COMPTEUR_DE_TESTS)


@pytest.fixture(autouse=True)
def _isolate_endocrine_blood(_bac_des_organes, _numero_de_test, monkeypatch):
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
    monkeypatch.setattr(fe, "DB", _bac_des_organes / ("endocrine_%d.db" % _numero_de_test), raising=False)


@pytest.fixture(autouse=True)
def _isolate_reveils_et_registres(_bac_des_organes, _numero_de_test, monkeypatch):
    """AUCUN test ne REVEILLE un organe reel ni n'ecrit dans un registre VIVANT (19/10).

    Mesure du 19/10 : deux fois dans l'apres-midi, un test de la CI a fait un crawl reel ->
    forge_docker_agent.demander_crawl4ai -> sandbox/crawl4ai.wanted + docker.wanted ; le keeper a relance
    Docker (vmmemWSL 3,15 Go, RAM a 95,1 % pendant la CI). La provenance des reveils (acf8e4035) a montre
    en plus un NR ecrivant dans le VRAI signal_emissions.db. Meme patron que le sang endocrinien : on
    redirige l'ORGANE cote HARNAIS, sous ses deux noms d'import, autouse.
      * drapeaux Docker / crawl4ai -> le bac (la vraie logique tourne, le keeper ne lit pas le bac) ;
      * couplage des signaux (emissions, journal date, provenances) -> le bac ;
      * registre des intentions (moteur timecode, sinon RAG/embeddings.db) -> une base du bac, creee a la
        demande seulement.
    """
    import importlib

    for nom in ("nokido_agent.app.forge_docker_agent", "forge_docker_agent"):
        try:
            da = importlib.import_module(nom)
        except Exception:  # noqa: BLE001 -- module absent de ce contexte : rien a isoler
            continue
        monkeypatch.setattr(da, "WANT_FLAG", _bac_des_organes / ("docker_%d.wanted" % _numero_de_test),
                            raising=False)
        monkeypatch.setattr(da, "CRAWL4AI_FLAG", _bac_des_organes / ("crawl4ai_%d.wanted" % _numero_de_test),
                            raising=False)
        monkeypatch.setattr(da, "AUDIT", _bac_des_organes / ("docker_audit_%d.jsonl" % _numero_de_test),
                            raising=False)
    for nom in ("nokido_agent.app.forge_signal_coupling", "forge_signal_coupling"):
        try:
            sc = importlib.import_module(nom)
        except Exception:  # noqa: BLE001
            continue
        monkeypatch.setattr(sc, "DB", _bac_des_organes / ("signal_%d.db" % _numero_de_test), raising=False)
    for nom in ("nokido_agent.app.forge_timecode", "forge_timecode"):
        try:
            tc = importlib.import_module(nom)
        except Exception:  # noqa: BLE001
            continue
        moteur = {}
        base = _bac_des_organes / ("timecode_%d.db" % _numero_de_test)
        avant = getattr(tc, "_engine", None)

        def _moteur_isole(_tc=tc, _m=moteur, _b=base, _avant=avant):
            # Un moteur pose PAR LE TEST (monkeypatch de _engine) prime : sans cela son ecriture partait dans le bac
            # et test_le_journal_d_intentions_ne_fige_plus_la_boucle_sous_verrou comptait 0 (CI de reference e6642dcf1).
            pose = getattr(_tc, "_engine", None)
            if pose is not None and pose is not _avant:
                return pose
            if "e" not in _m:
                _m["e"] = _tc.TimecodeEngine(_b)
            return _m["e"]

        monkeypatch.setattr(tc, "get_timecode_engine", _moteur_isole, raising=False)


@pytest.fixture(autouse=True)
def _isolate_postal(_bac_des_organes, _numero_de_test, monkeypatch):
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
        monkeypatch.setattr(module, "DB", _bac_des_organes / ("postal_%d.db" % _numero_de_test), raising=False)


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
