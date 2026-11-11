"""NR 11/11 -- trois defauts que SEULE une machine vierge montrait (CI GitHub, run 42930679070, 3 OS).

Le pre-vol local et le poste de l'owner etaient verts ; sur ubuntu, macos et windows heberges : 4 echecs par OS.
  1. `app/forge_symbiotic_bridge.py` importait `requests` au chargement : absent d'une machine vierge, le module ne
     s'importait plus -- alors que ce pont est FAIL-OPEN par contrat (son echec ne bloque jamais l'appel).
  2. `tools/forge_job_liveness._vivant` appelait `tasklist` (Windows seul) : sur Linux et macOS, le processus
     COURANT etait dit mort.
  3. `tools/forge_archeo_socle.ecrire_json` rendait `os.path.relpath(chemin, ROOT)` : entre deux lecteurs
     (`C:` et `D:` sur le runner Windows) c'est une ValueError -- apres avoir ecrit le fichier.
Ces conditions sont SIMULEES ici : le poste ne peut pas les produire, et c'est bien ce qui les cachait.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_le_pont_symbiotique_s_importe_sans_requests(monkeypatch, caplog):
    """Machine vierge : `import requests` leve ImportError -> le module s'importe quand meme ; a l'usage le pont
    reste FAIL-OPEN (rend "", ne leve pas) et DIT que `requests` manque (jamais un AttributeError avale)."""
    monkeypatch.setitem(sys.modules, "requests", None)  # None dans sys.modules = ImportError a l'import
    monkeypatch.delitem(sys.modules, "forge_symbiotic_bridge", raising=False)
    pont = importlib.import_module("forge_symbiotic_bridge")
    try:
        b = pont.SymbioticBridge()
        with caplog.at_level("WARNING", logger="symbiose"):
            assert b._ollama_call_sync("m", "s", "p") == ""  # pylint: disable=protected-access
        assert any("requests" in r.getMessage() and "absent" in r.getMessage() for r in caplog.records), \
            [r.getMessage() for r in caplog.records]
    finally:
        sys.modules.pop("forge_symbiotic_bridge", None)


def test_vivant_reconnait_le_processus_courant_hors_windows(monkeypatch):
    """Hors Windows : pas de `tasklist` ; le PID courant est vivant, un PID inexistant ne l'est pas."""
    import forge_job_liveness as jl

    appels = []

    def faux_kill(pid, sig):
        appels.append((pid, sig))
        if pid == 999999:
            raise ProcessLookupError()
        if pid == 4242:
            raise PermissionError()  # existe, appartient a un autre compte : VIVANT

    # JAMAIS de monkeypatch sur `os.name` ni sur une fonction du module `os` GLOBAL : pytest s'en sert lui-meme
    # (premiere version de ce test : INTERNALERROR, job_e390426b0db6). La plate-forme et la sonde sont INJECTEES.
    monkeypatch.setattr(jl.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("tasklist")))
    assert jl._vivant(1234, _windows=False, _kill=faux_kill) is True  # pylint: disable=protected-access
    assert jl._vivant(4242, _windows=False, _kill=faux_kill) is True  # pylint: disable=protected-access
    assert jl._vivant(999999, _windows=False, _kill=faux_kill) is False  # pylint: disable=protected-access
    assert jl._vivant(0, _windows=False, _kill=faux_kill) is False  # pylint: disable=protected-access
    assert appels and all(sig == 0 for _pid, sig in appels), "seul le signal 0 (sonde) est permis"


def test_ecrire_json_entre_deux_lecteurs_rend_le_chemin_absolu(tmp_path):
    """`relpath` impossible (lecteurs differents) : le fichier est ecrit ET un chemin lisible est rendu."""
    import forge_archeo_socle as socle

    def relpath_impossible(chemin, start=None):
        raise ValueError("path is on mount 'C:', start on mount 'D:'")

    cible = tmp_path / "a" / "b" / "rapport.json"
    rendu = socle.ecrire_json(str(cible), {"x": 1}, _relpath=relpath_impossible)
    assert cible.exists()
    assert os.path.normcase(os.path.abspath(rendu)) == os.path.normcase(str(cible))
