"""NR point 2 de l'homeostasie (owner 29/10) : PERIODE REFRACTAIRE de l'eviction Ollama.

Physiologie : apres une decharge, un neurone ne peut pas etre re-stimule aussitot (periode refractaire), ce qui empeche
l'emballement ; principe inscrit le 20/10 (« inhibition par defaut, periode refractaire »). Technique : oomd n'agit
que sur une pression soutenue, breathe pose un verrou de direction. Mesure du 29/10 : request_resources (etape 2a,
LRU Ollama) dechargeait laforge-qwen a chaque refus d'admission, un client le rechargeait, et ainsi de suite.
Un modele RECHARGE peu apres son eviction = preuve de demande : il n'est plus decharge pendant la periode
refractaire, SAUF detresse vitale (seuil existant LAFORGE_DETRESSE_LIBRE_GB).
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _rm():
    nom = "forge_resource_manager_nr_refractaire"
    if nom in sys.modules:
        return sys.modules[nom]
    sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]
    spec = importlib.util.spec_from_file_location(nom, ROOT / "app" / "forge_resource_manager.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[nom] = m
    spec.loader.exec_module(m)
    return m


def _prepare(monkeypatch, m, libre_go):
    dechargees = []
    monkeypatch.setattr(m, "ollama_loaded_models", lambda: [{"name": "laforge-qwen:latest", "size_gb": 1.09}])
    monkeypatch.setattr(m, "ollama_unload", lambda nom: dechargees.append(nom) or True)
    monkeypatch.setattr(m, "_free_now", lambda: libre_go)
    monkeypatch.setattr(m, "_audit_lifecycle", lambda *a, **k: None)
    m._OLLAMA_EVINCES.clear()
    return dechargees


def test_premiere_eviction_inchangee(monkeypatch):
    m = _rm()
    d = _prepare(monkeypatch, m, libre_go=3.0)
    actions = m._evincer_ollama_lru(needed=4.0, horloge=lambda: 1000.0, refresh=lambda: None)
    assert d == ["laforge-qwen:latest"] and any(a.startswith("ollama_unload:laforge-qwen") for a in actions)


def test_recharge_dans_la_periode_refractaire_non_dechargee(monkeypatch):
    m = _rm()
    d = _prepare(monkeypatch, m, libre_go=3.0)
    m._evincer_ollama_lru(needed=4.0, horloge=lambda: 1000.0, refresh=lambda: None)
    actions = m._evincer_ollama_lru(needed=4.0, horloge=lambda: 1000.0 + 120, refresh=lambda: None)
    assert d == ["laforge-qwen:latest"]  # une seule decharge
    assert any("REFRACTAIRE" in a for a in actions)


def test_apres_la_periode_refractaire_dechargeable(monkeypatch):
    m = _rm()
    d = _prepare(monkeypatch, m, libre_go=3.0)
    m._evincer_ollama_lru(needed=4.0, horloge=lambda: 1000.0, refresh=lambda: None)
    m._evincer_ollama_lru(needed=4.0, horloge=lambda: 1000.0 + m.OLLAMA_REFRACTAIRE_S + 1, refresh=lambda: None)
    assert d == ["laforge-qwen:latest", "laforge-qwen:latest"]


def test_detresse_vitale_outrepasse_la_periode_refractaire(monkeypatch):
    m = _rm()
    d = _prepare(monkeypatch, m, libre_go=1.0)   # sous le seuil de detresse (1,5 Go par defaut)
    m._evincer_ollama_lru(needed=4.0, horloge=lambda: 1000.0, refresh=lambda: None)
    actions = m._evincer_ollama_lru(needed=4.0, horloge=lambda: 1000.0 + 60, refresh=lambda: None)
    assert d == ["laforge-qwen:latest", "laforge-qwen:latest"]
    assert any("DETRESSE" in a for a in actions)
