"""
app/forge_dep_manager_auto.py — Runtime automatic dependency recovery.

Complements forge_dep_manager.py: that module statically parses a file's
imports ahead of time; this one catches ImportError AT RUNTIME and installs
the missing package, then retries the import. Reuses
forge_dep_manager.install_missing for the actual pip work — no duplicated
install logic.
"""

import importlib
import logging
from contextlib import contextmanager
from typing import Optional

from nokido_agent.app.forge_dep_manager import install_missing

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("Nokido.DepManagerAuto")

# import-name -> pip package-name, for the common mismatches
PACKAGE_ALIASES: dict[str, str] = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "yaml": "PyYAML",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
}


def _pip_name(module_name: str, package: Optional[str]) -> str:
    """Resolve the pip package name for an import name.

    Explicit ``package`` wins; otherwise the PACKAGE_ALIASES mapping; otherwise
    the import name itself.
    """
    if package:
        return package
    return PACKAGE_ALIASES.get(module_name, module_name)


def safe_import(module_name: str, package: Optional[str] = None):
    """Import ``module_name``; on ImportError, pip-install it once and retry.

    Args:
        module_name: the importable module name (e.g. ``"cv2"``).
        package: explicit pip package name; defaults to the PACKAGE_ALIASES
            mapping, then to ``module_name`` itself.

    Returns:
        The imported module object.

    Raises:
        ImportError: if the module is still missing after one install attempt.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        pkg = _pip_name(module_name, package)
        logger.info("auto-installing %s (for import %s)", pkg, module_name)
        results = install_missing([pkg])
        if not results.get(pkg, False):
            raise ImportError(f"auto-install of {pkg} failed for module {module_name}") from exc
        importlib.invalidate_caches()
        return importlib.import_module(module_name)


@contextmanager
def auto_deps():
    """Context manager: an ImportError inside the block triggers one
    auto-install of the offending package.

    If the install + re-import succeeds the error is swallowed (the caller can
    re-run its logic); if it still fails the original ImportError is re-raised.
    A context manager cannot resume the failed block, so callers needing the
    result should prefer :func:`safe_import` directly.

    Yields:
        None.
    """
    try:
        yield
    except ImportError as exc:
        module_name = exc.name or ""
        if not module_name:
            raise
        try:
            safe_import(module_name)
        except ImportError as inner:
            logger.error("auto_deps: could not recover import %s", module_name)
            raise exc from inner


# --------------------------------------------------------------------------
# pytest suite — no real pip install (only already-present modules / pure maps)
# --------------------------------------------------------------------------


def test_safe_import_existing() -> None:
    mod = safe_import("json")
    assert mod is not None
    assert hasattr(mod, "loads")


def test_safe_import_returns_same_module() -> None:
    import os as _os

    assert safe_import("os") is _os


def test_pip_name_alias() -> None:
    assert _pip_name("cv2", None) == "opencv-python"
    assert _pip_name("PIL", None) == "Pillow"
    assert _pip_name("yaml", None) == "PyYAML"


def test_pip_name_explicit_and_passthrough() -> None:
    assert _pip_name("whatever", "explicit-pkg") == "explicit-pkg"
    assert _pip_name("requests", None) == "requests"


def test_auto_deps_no_error() -> None:
    with auto_deps():
        import os

        assert os is not None


if __name__ == "__main__":
    import json as _j

    print(
        _j.dumps(
            {
                "aliases": PACKAGE_ALIASES,
                "safe_import(json)": str(safe_import("json")),
            },
            indent=2,
        )
    )
