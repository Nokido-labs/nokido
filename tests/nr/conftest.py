"""Fixtures partagees des tests NR.

Ce fichier ne contient QU'UNE chose, et volontairement : la reparation d'un
decalage entre ce que les tests du hub web posent et ce que le code lit.

LE DECALAGE (mesure 2026-08-20). Les `test_hub_*.py` configurent l'auth par
`monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", ...)`. Depuis la migration des
secrets vers le coffre DPAPI, `AuthConfig.from_env()` ne lit plus
`os.environ` mais `forge_secrets.get_secret`. Les tests posaient donc un token
que la configuration IGNORAIT : elle chargeait le VRAI token de la machine, et
46 tests echouaient en 401 -- contre un secret de production, jamais contre un
defaut du code. Ils ne mesuraient plus rien.

LA REPARATION. Pour ces fichiers seulement, le coffre REND ce que
l'environnement du test pose. Le contrat verifie redevient celui que ces tests
decrivent : « un admin token configure ouvre la session, son absence ferme
tout ». La production continue de lire le coffre, et aucun autre test NR n'est
touche -- un conftest `autouse` sans garde changerait le comportement de 92
fichiers d'un coup, dont ceux qui veulent justement le vrai coffre.
"""
from __future__ import annotations

import os
import sys

import pytest

# 7/11 : le registre vivant des surfaces indisponibles ne doit jamais decider d'un NR (Mistral marque = 13 NR rouges).
# Pose ici, avant la collecte : `_FICHIER_INDISPO` se lit a l'import de forge_task_executor, sous tous ses noms.
__import__("os").environ["LAFORGE_SURFACES_INDISPO_FICHIER"] = __import__("os").path.join(
    __import__("tempfile").gettempdir(), "nokido_nr_surfaces_indispo_%d.json" % __import__("os").getpid())


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "mesure: chronometrage (saute hors `-m mesure`), pas une regression")
    config.addinivalue_line("markers", "timeout(s): borne de duree du test (pytest-timeout)")


# MARGES MESUREES (11/11, job_da23217046a2 : durees de 21 716 tests SOUS CHARGE CI, tirees des journaux de vol).
# Ces fichiers SAINS durent 15 a 50 s sous 5 workers pour un `--timeout=30` : un rien de charge tue le worker,
# et en `--dist=loadfile` un worker mort fige la suite. Le contrat global de 30 s NE BOUGE PAS ; ces fichiers
# recoivent une borne explicite (3x le pire mesure sans marqueur, 26 s), sauf marqueur deja pose par le test.
# Ajouter un fichier ici = joindre sa mesure (C:/tmp/chasse_tests_lents_vol_20261111.py).
_TIMEOUT_LENTS_S = 90
_FICHIERS_LENTS_MESURES = frozenset((
    "test_ci_bloc_isole_chemin_reel_nr.py", "test_pypi_baseline_nr.py", "test_red_retroactif_nr.py",
    "test_nr_instables_nr.py", "test_cycle_verdict_nr.py", "test_archeologie_outils_nr.py",
    "test_flux_etats_nr.py", "test_juge_tests_verts_rejeu_nr.py", "test_pouls_canon_nr.py",
    "test_dup_adaptateur_entree_nr.py", "test_forge_tui_sonde_nr.py", "test_selecteur_only_nr.py",
    "test_panorama_imports_qualifies_nr.py", "test_zai_palier_gratuit_nr.py", "test_modules_parsables_nr.py",
    "test_garde_ui_mutation_nr.py", "test_generer_appui_nr.py", "test_balayeurs_lisent_le_producteur_nr.py",
    "test_worktrees_preuve_sans_perte_nr.py", "test_ci_selection_partielle_nr.py",
    "test_critical_file_executoire_commit_nr.py", "test_nr_coverage_ratchet_nr.py",
    "test_secrets_noms_env_valeurs_coffre_nr.py", "test_syspath_cartography_nr.py",
    "test_commit_deux_temps_red_green_nr.py", "test_rejeu_red_crash_ou_rouge_nr.py",
    "test_veille_clone_garde_disque_nr.py",
    # tue a 31 s le 10/11 (git grep reel sur le depot, vol_gw3_28984) : chemin reel voulu, borne elargie
    "test_introspect_memoire_active_nr.py",
))


def pytest_collection_modifyitems(config, items):  # pylint: disable=unused-argument
    for item in items:
        nom = os.path.basename(str(item.fspath))
        if nom in _FICHIERS_LENTS_MESURES and item.get_closest_marker("timeout") is None:
            item.add_marker(pytest.mark.timeout(_TIMEOUT_LENTS_S))


def pytest_sessionstart(session):
    # data_nr/ est ignore par git : ses jeux de reference sont GENERES depuis le code (forge_dataset_sync),
    # comme le fait tools/mcp_nr.py avant ses suites. Sans cela un pytest nu lit un dossier absent
    # (4 fichiers de tests en FileNotFoundError). Ne regenere que les jeux perimes ; non bloquant.
    try:
        from nokido_agent.app.forge_dataset_sync import sync_before_nr
        sync_before_nr(verbose=False)
    except Exception:  # noqa: BLE001 - les tests concernes echoueront en disant le fichier absent
        __import__("logging").getLogger(__name__).warning("datasets NR non regeneres", exc_info=True)


def _tuer_faux_orphelins(dossier) -> int:
    """Tue les descendants du process courant qui executent `<dossier>/faux.py` ; rend leur nombre.

    10/11, job_b486a06b80ae : 24 NR (ACP surtout) laissaient leur faux agent stdio vivant apres le
    teardown ; sous un worker xdist longue vie ils s'accumulaient (21 orphelins tues a la main)."""
    import psutil

    cible = os.path.normcase(str(os.path.join(str(dossier), "faux.py")))
    tues = []
    for c in psutil.Process().children(recursive=True):
        try:
            if any(os.path.normcase(a) == cible for a in c.cmdline()):
                c.kill()
                tues.append(c)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    psutil.wait_procs(tues, timeout=3)
    return len(tues)


@pytest.fixture(autouse=True)
def _faux_orphelins_au_teardown(request):
    """Apres le test : si SON tmp_path porte un faux.py, aucun faux agent ne lui survit.
    Ne demande PAS tmp_path (aucun dossier cree pour les autres tests) ; muet sur toute erreur."""
    yield
    tmp = request.node.funcargs.get("tmp_path") if hasattr(request.node, "funcargs") else None
    try:
        if tmp is not None and (tmp / "faux.py").exists():
            _tuer_faux_orphelins(tmp)
    except Exception:  # noqa: BLE001 - un nettoyage ne fait jamais echouer le test
        pass


_NOMS_ADMISSION = ("app.forge_lane_admission", "forge_lane_admission", "nokido_agent.app.forge_lane_admission")


@pytest.fixture(autouse=True)
def _attribution_ram_neutralisee(monkeypatch):
    """10/11, pre-vol job_fa2fd1001593 : un refus d'admission appelait `_qui_tient(None)` -> attribuer_pression()
    REEL (toute la machine, 11,3 s a froid, job_f8d12ac54be7) -> >30 s sous 5 workers -> pytest-timeout
    os._exit -> worker gw1 mort, suite figee. 20 NR passent par l'admission, 1 seul neutralisait.
    Ici : attribution PAR DEFAUT neutralisee (dite, jamais tue) ; une attribution INJECTEE reste reelle."""
    for nom in _NOMS_ADMISSION:
        m = sys.modules.get(nom)
        orig = getattr(m, "_qui_tient", None) if m is not None else None
        if orig is None:
            continue

        def _neutre(attribuer=None, _orig=orig):
            if attribuer is None:
                return "attribution neutralisee (NR hermetique : attribuer_pression reel = 11,3 s a froid)"
            return _orig(attribuer)
        monkeypatch.setattr(m, "_qui_tient", _neutre)


_MODULES_ACP_SIGNES = ("test_acp_router_permissions_nr", "test_acp_views_csrf_nr", "test_acp_views_nr")


@pytest.fixture(autouse=True)
def _cle_acp_de_test(request, monkeypatch):
    """Les NR ACP historiques decident via le routeur : leur fournir une cle Ed25519 de TEST (jamais la vraie)."""
    if request.module.__name__.rsplit(".", 1)[-1] not in _MODULES_ACP_SIGNES:
        return
    import sys
    from pathlib import Path

    from cryptography.hazmat.primitives import serialization as S
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    tools = str(Path(__file__).resolve().parents[2] / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import forge_acp_hub as H
    import forge_acp_router as R

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(S.Encoding.Raw, S.PublicFormat.Raw)
    monkeypatch.setattr(R, "_epingle_defaut", lambda: {"kt": pub})
    monkeypatch.setattr(R, "signer_hub", lambda payload: H.sceller("acp_decision", payload, (priv, "kt")))


# TRACEUR D'IMPORT (19/10, plantages arrow.dll des workers de CI) : desarme sauf si NOKIDO_TRACE_IMPORT est pose
# (ci_local --trace-import pyarrow). Il journalise le test en cours au premier chargement du module surveille.
_TRACE_IMPORT = os.environ.get("NOKIDO_TRACE_IMPORT", "").strip()
if _TRACE_IMPORT:
    from nokido_agent.tools import forge_trace_import as _trace_import

    _trace_import.armer([m.strip() for m in _TRACE_IMPORT.split(",")])

    def pytest_runtest_setup(item):
        _trace_import.COURANT["test"] = item.nodeid


@pytest.fixture(autouse=True)
def _coffre_suit_l_environnement(request, monkeypatch):
    # GARDE DE PORTEE : uniquement les tests du hub web. Le nom de fichier est
    # un critere grossier, mais il est LISIBLE -- et une fixture globale muette
    # serait bien pire qu'un filtre explicite qu'on peut contester.
    nom = getattr(request.node, "fspath", None)
    if nom is None or not os.path.basename(str(nom)).startswith("test_hub_"):
        return
    try:
        import forge_secrets
    except Exception:  # noqa: BLE001 - coffre absent : les tests d'env restent valides
        return
    monkeypatch.setattr(forge_secrets, "get_secret",
                        lambda cle, *a, **kw: os.environ.get(cle) or None,
                        raising=False)


@pytest.fixture(autouse=True)
def _pas_de_verdict_reel_depuis_un_test(monkeypatch, tmp_path_factory):
    """19/10 : le verdict automatique de l'executeur (recompense + transient au tableau noir) est COUPE dans tous les
    tests NR. Mesure : les NR de delegation avaient ecrit ~23 faux verdicts (job_empty_01, job_repli_01, t-vibe...)
    dans le vrai registre de recompense, dont des VIDE qui punissaient des repondeurs. Portee globale VOULUE : aucun
    test ne doit ecrire ce registre ; les NR du verdict le rallument avec leurs doublures (`setenv("1")`)."""
    monkeypatch.setenv("NOKIDO_VERDICT_AUTO", "0")
    # Conseiller souverain (24/10) : coupe par defaut dans les NR (aucun reseau) ; ses NR le rallument avec un double.
    monkeypatch.setenv("LAFORGE_CONSEILLER", "0")
    # Repli web Ollama Cloud (26/10) : coupe par defaut -- aucun test n'envoie de requete au cloud ; son NR le rallume.
    monkeypatch.setenv("LAFORGE_WEB_OLLAMA", "0")
    # Organe de recherche unique (T2a, 10/11) : etages Tavily (payant) et sources primaires (GitHub/PyPI) coupes
    # par defaut -- aucun test ne sort sur le reseau ; test_organe_recherche_cascade_nr les rallume avec ses doubles.
    monkeypatch.setenv("LAFORGE_WEB_TAVILY", "0")
    monkeypatch.setenv("LAFORGE_WEB_PRIMAIRES", "0")
    # Reveil de SearXNG sur echec (10/11 soir) : coupe -- aucun test ne reclame Docker ; test_web_reveil_searxng_nr
    # le rallume avec un double.
    monkeypatch.setenv("LAFORGE_WEB_REVEIL", "0")
    # Vetos de sommeil (26/10) : aucun test n'ecrit dans le sandbox/veto_sommeil que lit Hamilton (un pytest y avait
    # laisse « examen de la soif (nr) », pid mort, 15 min de veto reel).
    # Un repertoire NEUF par test : un veto laisse par run_once (que seul run() leve) ne fuit pas dans le test suivant.
    monkeypatch.setenv("LAFORGE_VETO_SOMMEIL_DIR", str(tmp_path_factory.mktemp("veto_sommeil")))
    # Pouls du harness worker (27/10) : les tests de delegation simulent le harness ; ils ne lisent pas le VRAI pouls
    # de la machine (mort la nuit -> « Vibe non lance »). test_harness_worker_vivant_avant_delegation_nr le retire.
    monkeypatch.setenv("LAFORGE_HARNESS_POULS_IGNORE", "1")
    # Meme regle pour le bus d'essaim (19/10) : aucun test n'ecrit le VRAI miroir sandbox/reflexion.jsonl.
    monkeypatch.setenv("NOKIDO_BUS_TACHES", "0")
    # Et pour le journal d'usage du RAG (19/10, extracteur de citations) : aucun test n'ecrit logs/rag_usage_signal.jsonl.
    monkeypatch.setenv("NOKIDO_RAG_SIGNAL", "0")
    # Etat VIVANT des executeurs (31/10, choix owner « isoler d'abord ») : 14 NR de l'executeur lisaient le VRAI
    # coupe-circuit (« en repos jusqu'a 14:38 : 2 pannes ») et le VRAI census (« glm-4.5-flash quota epuise jusqu'a
    # 18:05 ») -- rouges le jour ou les budgets s'epuisent, verts en CI de reference isolee. Un fichier NEUF par test ;
    # un NR qui veut un etat le pose lui-meme (setenv / monkeypatch SORTIE).
    monkeypatch.setenv("LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE",
                       str(tmp_path_factory.mktemp("coupe_circuit") / "opencode_coupe_circuit.json"))
    _census = sys.modules.get("forge_free_tier_census") or sys.modules.get("nokido_agent.tools.forge_free_tier_census")
    if _census is None:
        try:
            import forge_free_tier_census as _census  # noqa: PLC0415 - import paresseux, seulement s'il est importable
        except Exception:  # noqa: BLE001 - muet-ok : sans census importable, l'executeur le lit INCONNU (None)
            _census = None
    if _census is not None:
        monkeypatch.setattr(_census, "SORTIE", tmp_path_factory.mktemp("census") / "free_tier_census.json")
