"""NR (29/10) : l'appel au conseiller est BORNE EN DUREE -- « jamais bloquant » doit valoir pour le temps aussi.

Mesure : les 4 executeurs OpenCode (DEFAUT2 a 5) ont appele le conseiller (LiteLLM nemotron-3-ultra, Ollama Cloud) a
15:54:52, puis plus une ligne de journal pendant 15 min : le creneau ollama_cloud_ultra ne declare aucun delai et
_appeler_conseiller ne bornait que les EXCEPTIONS. Le delai ne doit pas reproduire C2.1 (audit 29/10 : un with
ThreadPoolExecutor attend la tache a sa sortie) : shutdown(wait=False).
"""
import importlib.util
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _ex():
    nom = "forge_task_executor_nr_conseiller"
    if nom in sys.modules:
        return sys.modules[nom]
    sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app"), str(ROOT / "tools")]
    spec = importlib.util.spec_from_file_location(nom, ROOT / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[nom] = m
    spec.loader.exec_module(m)
    return m


def _routeur(monkeypatch, fn):
    mod = types.ModuleType("nokido_agent.app.forge_llm_router")
    mod.conseiller = fn
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_llm_router", mod)


def test_conseiller_muet_coupe_au_delai(monkeypatch):
    m = _ex()
    monkeypatch.setattr(m, "CONSEIL_DELAI_S", 0.5)
    _routeur(monkeypatch, lambda *a, **k: time.sleep(5) or {"avis": "trop tard"})
    t0 = time.monotonic()
    r = m._appeler_conseiller("t", "plan", "ctx")
    assert time.monotonic() - t0 < 2.0
    assert r["avis"] == "" and "DELAI" in r.get("erreur", "")


def test_conseiller_rapide_inchange(monkeypatch):
    m = _ex()
    monkeypatch.setattr(m, "CONSEIL_DELAI_S", 5.0)
    _routeur(monkeypatch, lambda *a, **k: {"avis": "ok", "fournisseur": "x"})
    r = m._appeler_conseiller("t", "plan", "ctx")
    assert r["avis"] == "ok" and r["fournisseur"] == "x"
