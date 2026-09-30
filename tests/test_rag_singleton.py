"""Singleton RAG — residuel cold-wedge (2026-07-14).

Construire un RAGEngine decode ~691k chunks (GIL-bound, ~2 min, gros pic RAM).
Plusieurs sites le faisaient PAR APPEL (forge_dispatchers, forge_tem_factorize,
forge_handler_advanced) -> N moteurs au lieu de 1. Ces tests verrouillent :
  1. get_rag() = singleton (meme instance),
  2. sous concurrence, UN SEUL build (double-checked lock),
  3. aucun site app/ ne rappelle le constructeur RAGEngine() directement
     (hors forge_rag_engine lui-meme et forge_mixin_ui = process TUI, proprietaire
     legitime de __main__.rag_engine).
"""

import re
import sys
import threading
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de tous les app/*.py
#   (l.73)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import forge_rag_engine as fre  # noqa: E402

# Sites autorises a construire le moteur directement : sa propre definition, et les
# process TUI/app qui SONT proprietaires de __main__.rag_engine (injection historique).
_ALLOWED = {"forge_rag_engine.py", "forge_mixin_ui.py", "Nokido.py"}


@pytest.fixture
def fresh_singleton(monkeypatch):
    """Reset du singleton + moteur factice (evite le decode 691k en test)."""
    builds = []

    class _FakeEngine:
        def __init__(self, db_path=None):
            builds.append(db_path)

    monkeypatch.setattr(fre, "RAGEngine", _FakeEngine)
    monkeypatch.setattr(fre, "_RAG", None)
    return builds


def test_get_rag_returns_same_instance(fresh_singleton):
    first = fre.get_rag()
    second = fre.get_rag()
    assert first is second
    assert len(fresh_singleton) == 1, "le moteur doit etre construit UNE fois"


def test_get_rag_builds_once_under_concurrency(fresh_singleton):
    """Sans double-checked lock, 2 threads concurrents construisaient 2 moteurs."""
    seen = []
    barrier = threading.Barrier(8)

    def _worker():
        barrier.wait()  # maximise la collision sur le check `_RAG is None`
        seen.append(fre.get_rag())

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(fresh_singleton) == 1, f"builds concurrents = {len(fresh_singleton)} (attendu 1)"
    assert len({id(o) for o in seen}) == 1, "tous les threads doivent voir la meme instance"


def test_no_module_constructs_rag_engine_directly():
    """Anti-regression : un nouveau RAGEngine() par appel reintroduit le cold-wedge."""
    offenders = []
    for path in (ROOT / "app").glob("*.py"):
        if path.name in _ALLOWED:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            code = line.split("#", 1)[0]  # ignore les mentions en commentaire
            # `RAGEngine(` colle : les docstrings ecrivent "RAGEngine (optionnel)" (espace)
            if re.search(r"(?<![\w.])RAGEngine\(", code):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, "utiliser get_rag() (singleton) au lieu de RAGEngine() :\n" + "\n".join(offenders)


def test_forge_rag_engine_has_no_forge_rag_engine_alias():
    """`ForgeRAGEngine` n'existe pas : tout import de ce nom est une zone morte
    (ImportError avale par un `except Exception: pass`). Si un jour l'alias est
    ajoute, ce test tombe et il faudra reexaminer les sites qui l'importent."""
    assert not hasattr(fre, "ForgeRAGEngine")
