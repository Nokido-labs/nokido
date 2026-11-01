"""`rag_warmup_spawn` doit exister la ou forge_web_service l'importe (import casse, releve 24/10).

app/forge_web_service.py fait `from nokido_agent.app.forge_rag_warmup import rag_warmup_spawn` ;
la fonction ne vivait que dans app/patch_rag_warmup.py (un script de patch jamais applique) :
le bouton de warmup du service web levait ImportError. Aucun vrai processus n'est lance ici.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)


def test_rag_warmup_spawn_existe_et_rend_l_identifiant(monkeypatch):
    import forge_rag_warmup as w

    lances = []
    faux_runner = types.ModuleType("forge_runner")
    faux_runner.spawn = lambda code, prefix="": lances.append((prefix, code)) or "rag_warm_42"
    monkeypatch.setitem(sys.modules, "forge_runner", faux_runner)
    assert callable(getattr(w, "rag_warmup_spawn", None)), "rag_warmup_spawn absent de forge_rag_warmup"
    assert w.rag_warmup_spawn() == "rag_warm_42"
    assert lances and lances[0][0] == "rag_warm"


def test_un_echec_de_lancement_se_dit_sans_lever(monkeypatch):
    import forge_rag_warmup as w

    faux_runner = types.ModuleType("forge_runner")

    def _casse(code, prefix=""):
        raise RuntimeError("runner indisponible")

    faux_runner.spawn = _casse
    monkeypatch.setitem(sys.modules, "forge_runner", faux_runner)
    rendu = w.rag_warmup_spawn()
    assert isinstance(rendu, str) and "runner indisponible" in rendu
