# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_053059_groqcerber
#FORGE:[score:90|agent:groq-cerberus|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: docstrings Google-style complets
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:90|agent:groq-cerberus|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
forge_app_context.py — Accesseurs centralisés pour les globals Nokido
=======================================================================
Remplace les 200+ appels forge_context.get_rag_engine(), forge_context.get_settings() etc.
dispersés dans 27 modules.

Usage :
    from forge_app_context import get_rag, get_settings, get_ssh, app_ctx

    rag      = get_rag()        # RAGEngine | None
    settings = get_settings()   # Settings  (jamais None)
    ssh      = get_ssh()        # SSHManager | None

    # Ou via le context object
    ctx = app_ctx()
    ctx.rag_engine, ctx.settings, ctx.ssh_manager
"""


import sys
import logging

logger = logging.getLogger("Nokido.AppContext")

# ── Résolution depuis sys.modules ────────────────────────────────────────────


def _from_main(name: str, default: object | None = None) -> object:
    """
    Cherche un attribut dans __main__ / Nokido / app.Nokido.

    Args:
        name (str): Nom de l'attribut  rechercher.
        default (object | None, optional): Valeur  retourner si l'attribut n'est pas trouv. Defaults to None.

    Returns:
        object: Valeur de l'attribut trouve ou la valeur par dfaut.

    Raises:
        AttributeError: Si l'attribut n'est pas trouvé dans les modules.
    """
    for mod_name in ("__main__", "Nokido", "app.Nokido"):
        m = sys.modules.get(mod_name)
        if m is not None:
            val = getattr(m, name, None)
            if val is not None:
                return val
    return default


# ── Accesseurs individuels ────────────────────────────────────────────────────


def get_rag() -> object:
    """
    RAGEngine active ou None.

    Returns:
        object: RAGEngine ou None.

    Raises:
        Exception: Si une erreur se produit lors de la récupération de RAGEngine.
    """
    return _from_main("rag_engine")


def get_settings() -> object:
    """
    Settings — toujours retourne un objet Settings valide.

    Returns:
        object: Settings.

    Raises:
        Exception: Si une erreur se produit lors de la création de Settings.
    """
    s = _from_main("settings")
    if s is None:
        # PROCESS STANDALONE (script/run_job) : `app.core.settings` exige ROOT (le repo) sur le path,
        # pas seulement ROOT/app -> sans ça l'import échoue, s reste None, et tout lecteur de
        # settings.X crashe (bug reindex_v15 2026-06-17 : settings.max_concurrent_tasks sur None).
        import sys as _sys
        from pathlib import Path as _P
        _root = str(_P(__file__).resolve().parent.parent)
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        try:
            from app.core.settings import create_settings

            s = create_settings()
        except Exception:
            pass
    # Dernier recours — instance minimale
    if s is None:
        try:
            from app.core.settings import Settings

            s = Settings()
        except Exception:
            pass
    return s


def get_ssh() -> object:
    """
    SSHManager ou None.

    Returns:
        object: SSHManager ou None.

    Raises:
        Exception: Si une erreur se produit lors de la récupération de SSHManager.
    """
    return _from_main("ssh_manager")


def get_version_manager() -> object:
    """
    VersionManager ou None.

    Returns:
        object: VersionManager ou None.

    Raises:
        Exception: Si une erreur se produit lors de la création de VersionManager.
    """
    vm = _from_main("version_manager")
    if vm is None:
        try:
            from nokido_agent.app.forge_versioning import VersionManager

            vm = VersionManager()
        except Exception:
            pass
    return vm


def get_agentic() -> object:
    """
    AgenticEngine ou None.

    Returns:
        object: AgenticEngine ou None.

    Raises:
        Exception: Si une erreur se produit lors de la récupération de AgenticEngine.
    """
    return _from_main("agentic_engine")


def get_prefect() -> object:
    """
    PrefectManager ou None.

    Returns:
        object: PrefectManager ou None.

    Raises:
        Exception: Si une erreur se produit lors de la récupération de PrefectManager.
    """
    return _from_main("prefect_manager")


def get_mem_mgr() -> bool:
    """
    OllamaMemoryManager ou None.

    Returns:
        bool: OllamaMemoryManager ou None.

    Raises:
        Exception: Si une erreur se produit lors de la récupération de OllamaMemoryManager.
    """
    return _from_main("mem_optimizer") or _from_main("_mem_mgr")


def get_session_name() -> str:
    """
    Nom de session courant.

    Returns:
        str: Nom de session.

    Raises:
        Exception: Si une erreur se produit lors de la récupération du nom de session.
    """
    return _from_main("session_name") or "default"


# ── Flags HAS_* ──────────────────────────────────────────────────────────────


def has_onnx() -> bool:
    """
    Vérifie si ONNX est disponible.

    Returns:
        bool: True si ONNX est disponible, False sinon.

    Raises:
        Exception: Si une erreur se produit lors de la vérification de la disponibilité de ONNX.
    """
    return bool(_from_main("HAS_ONNX", False))


def has_memory() -> bool:
    """
    Vérifie si la mémoire est disponible.

    Returns:
        bool: True si la mémoire est disponible, False sinon.

    Raises:
        Exception: Si une erreur se produit lors de la vérification de la disponibilité de la mémoire.
    """
    return bool(_from_main("HAS_MEMORY", False))


def has_loops() -> bool:
    """
    Vérifie si les boucles sont disponibles.

    Returns:
        bool: True si les boucles sont disponibles, False sinon.

    Raises:
        Exception: Si une erreur se produit lors de la vérification de la disponibilité des boucles.
    """
    return bool(_from_main("HAS_LOOPS", False))


def has_scoring() -> bool:
    """
    Vérifie si le scoring est disponible.

    Returns:
        bool: True si le scoring est disponible, False sinon.

    Raises:
        Exception: Si une erreur se produit lors de la vérification de la disponibilité du scoring.
    """
    return bool(_from_main("HAS_SCORING", False))


def has_textual() -> bool:
    """
    Vérifie si le texte est disponible.

    Returns:
        bool: True si le texte est disponible, False sinon.

    Raises:
        Exception: Si une erreur se produit lors de la vérification de la disponibilité du texte.
    """
    return bool(_from_main("HAS_TEXTUAL", False))


def has_services() -> bool:
    """
    Vérifie si les services sont disponibles.

    Returns:
        bool: True si les services sont disponibles, False sinon.

    Raises:
        Exception: Si une erreur se produit lors de la vérification de la disponibilité des services.
    """
    return bool(_from_main("HAS_SERVICES", False))


def has_faiss() -> bool:
    """
    Vérifie si FAISS est disponible.

    Returns:
        bool: True si FAISS est disponible, False sinon.

    Raises:
        Exception: Si une erreur se produit lors de la vérification de la disponibilité de FAISS.
    """
    return bool(_from_main("HAS_FAISS", False))


def has_sandbox() -> bool:
    """
    Vérifie si le sandbox est disponible.

    Returns:
        bool: True si le sandbox est disponible, False sinon.

    Raises:
        Exception: Si une erreur se produit lors de la vérification de la disponibilité du sandbox.
    """
    return bool(_from_main("HAS_SANDBOX", False))


def has_skilltree() -> bool:
    """
    Vérifie si l'arbre de compétences est disponible.

    Returns:
        bool: True si l'arbre de compétences est disponible, False sinon.

    Raises:
        Exception: Si une erreur se produit lors de la vérification de la disponibilité de l'arbre de compétences.
    """
    return bool(_from_main("HAS_SKILLTREE", False))


def has_prefect() -> bool:
    """
    Vérifie si Prefect est disponible.

    Returns:
        bool: True si Prefect est disponible, False sinon.

    Raises:
        Exception: Si une erreur se produit lors de la vérification de la disponibilité de Prefect.
    """
    return bool(_from_main("HAS_PREFECT", False))


def has_web_search() -> bool:
    """
    Vérifie si la recherche web est disponible.

    Returns:
        bool: True si la recherche web est disponible, False sinon.

    Raises:
        Exception: Si une erreur se produit lors de la vérification de la disponibilité de la recherche web.
    """
    try:
        from nokido_agent.app.forge_web import is_web_search_enabled

        return is_web_search_enabled()
    except Exception:
        return bool(_from_main("HAS_WEB_SEARCH", False))


# ── Context object ────────────────────────────────────────────────────────────


class _AppContext:
    """
    Accès lazy à tous les globals Nokido.
    Usage : ctx = app_ctx(); ctx.rag_engine
    """

    __slots__ = ()

    @property
    def rag_engine(self) -> object:
        """
        RAGEngine active ou None.

        Returns:
            object: RAGEngine ou None.

        Raises:
            Exception: Si une erreur se produit lors de la récupération de RAGEngine.
        """
        return get_rag()

    @property
    def settings(self) -> object:
        """
        Settings — toujours retourne un objet Settings valide.

        Returns:
            object: Settings.

        Raises:
            Exception: Si une erreur se produit lors de la création de Settings.
        """
        return get_settings()

    @property
    def ssh_manager(self) -> object:
        """
        SSHManager ou None.

        Returns:
            object: SSHManager ou None.

        Raises:
            Exception: Si une erreur se produit lors de la récupération de SSHManager.
        """
        return get_ssh()

    @property
    def version_manager(self) -> object:
        """
        VersionManager ou None.

        Returns:
            object: VersionManager ou None.

        Raises:
            Exception: Si une erreur se produit lors de la création de VersionManager.
        """
        return get_version_manager()

    @property
    def agentic_engine(self) -> object:
        """
        AgenticEngine ou None.

        Returns:
            object: AgenticEngine ou None.

        Raises:
            Exception: Si une erreur se produit lors de la récupération de AgenticEngine.
        """
        return get_agentic()

    @property
    def prefect_manager(self) -> object:
        """
        PrefectManager ou None.

        Returns:
            object: PrefectManager ou None.

        Raises:
            Exception: Si une erreur se produit lors de la récupération de PrefectManager.
        """
        return get_prefect()

    @property
    def mem_mgr(self) -> object:
        """
        OllamaMemoryManager ou None.

        Returns:
            object: OllamaMemoryManager ou None.

        Raises:
            Exception: Si une erreur se produit lors de la récupération de OllamaMemoryManager.
        """
        return get_mem_mgr()

    @property
    def session_name(self) -> object:
        """
        Nom de session courant.

        Returns:
            object: Nom de session.

        Raises:
            Exception: Si une erreur se produit lors de la récupération du nom de session.
        """
        return get_session_name()

    # Flags
    @property
    def HAS_ONNX(self) -> object:
        """
        Vérifie si ONNX est disponible.

        Returns:
            object: True si ONNX est disponible, False sinon.

        Raises:
            Exception: Si une erreur se produit lors de la vérification de la disponibilité de ONNX.
        """
        return has_onnx()

    @property
    def HAS_MEMORY(self) -> object:
        """
        Vérifie si la mémoire est disponible.

        Returns:
            object: True si la mémoire est disponible, False sinon.

        Raises:
            Exception: Si une erreur se produit lors de la vérification de la disponibilité de la mémoire.
        """
        return has_memory()

    @property
    def HAS_LOOPS(self) -> object:
        """
        Vérifie si les boucles sont disponibles.

        Returns:
            object: True si les boucles sont disponibles, False sinon.

        Raises:
            Exception: Si une erreur se produit lors de la vérification de la disponibilité des boucles.
        """
        return has_loops()

    @property
    def HAS_SCORING(self) -> object:
        """
        Vérifie si le scoring est disponible.

        Returns:
            object: True si le scoring est disponible, False sinon.

        Raises:
            Exception: Si une erreur se produit lors de la vérification de la disponibilité du scoring.
        """
        return has_scoring()

    @property
    def HAS_SERVICES(self) -> object:
        """
        Vérifie si les services sont disponibles.

        Returns:
            object: True si les services sont disponibles, False sinon.

        Raises:
            Exception: Si une erreur se produit lors de la vérification de la disponibilité des services.
        """
        return has_services()

    @property
    def HAS_FAISS(self) -> object:
        """
        Vérifie si FAISS est disponible.

        Returns:
            object: True si FAISS est disponible, False sinon.

        Raises:
            Exception: Si une erreur se produit lors de la vérification de la disponibilité de FAISS.
        """
        return has_faiss()

    @property
    def HAS_SANDBOX(self) -> object:
        """
        Vérifie si le sandbox est disponible.

        Returns:
            object: True si le sandbox est disponible, False sinon.

        Raises:
            Exception: Si une erreur se produit lors de la vérification de la disponibilité du sandbox.
        """
        return has_sandbox()

    @property
    def HAS_SKILLTREE(self) -> object:
        """
        Vérifie si l'arbre de compétences est disponible.

        Returns:
            object: True si l'arbre de compétences est disponible, False sinon.

        Raises:
            Exception: Si une erreur se produit lors de la vérification de la disponibilité de l'arbre de compétences.
        """
        return has_skilltree()

    @property
    def HAS_PREFECT(self) -> object:
        """
        Vérifie si Prefect est disponible.

        Returns:
            object: True si Prefect est disponible, False sinon.

        Raises:
            Exception: Si une erreur se produit lors de la vérification de la disponibilité de Prefect.
        """
        return has_prefect()

    @property
    def HAS_WEB_SEARCH(self) -> object:
        """
        Vérifie si la recherche web est disponible.

        Returns:
            object: True si la recherche web est disponible, False sinon.

        Raises:
            Exception: Si une erreur se produit lors de la vérification de la disponibilité de la recherche web.
        """
        return has_web_search()


_ctx = _AppContext()


def app_ctx() -> _AppContext:
    """
    Retourne le context object singleton.

    Returns:
        _AppContext: Context object.

    Raises:
        Exception: Si une erreur se produit lors de la récupération du context object.
    """
    return _ctx
