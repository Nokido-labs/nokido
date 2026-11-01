# -*- coding: utf-8 -*-
"""NR (31/10) -- le hook Stop de friction DIT un scoreur illisible au lieu de rendre 0 en silence.

forge_dialogue_score_session etait cable sans garantie de mesurer : `except Exception: return 0` sur l'import du
scoreur. Un hook Stop ne bloque jamais (rc 0), mais le motif doit sortir sur stderr ET dans le watermark.
"""
import builtins
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("dialogue_score_nr", ROOT / "tools" / "forge_dialogue_score_session.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_un_scoreur_illisible_est_dit_pas_tu(tmp_path, monkeypatch, capsys):
    m = _module()
    wm = tmp_path / "wm.json"
    monkeypatch.setattr(m, "_load_wm", lambda: json.loads(wm.read_text(encoding="utf-8")) if wm.exists() else {})
    monkeypatch.setattr(m, "_save_wm", lambda d: wm.write_text(json.dumps(d), encoding="utf-8"))
    vrai_import = builtins.__import__

    def faux_import(nom, *a, **k):
        if nom.endswith("forge_dialogue_outcome"):
            raise ImportError("scoreur retire")
        return vrai_import(nom, *a, **k)

    monkeypatch.setattr(builtins, "__import__", faux_import)
    monkeypatch.setattr("sys.argv", ["forge_dialogue_score_session.py", "--agent", "claude"])
    assert m.main() == 0                                   # un hook Stop ne bloque jamais
    assert "scoreur ILLISIBLE" in capsys.readouterr().err
    assert "retire" in json.loads(wm.read_text(encoding="utf-8"))["_scoreur_illisible"]["motif"]
