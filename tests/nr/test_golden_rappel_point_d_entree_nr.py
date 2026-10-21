"""NR -- le point d'entree de forge_golden_rappel (main) mesure et ecrit son rapport (chemin reel, pas la seule fonction).

Reflexe du corps (RULES_SHARED) : « un NR emprunte le chemin REEL (point d'entree, __main__, drapeau CLI) ». main lit le
jeu et les verdicts, demande la source des ids attendus a la base (cle primaire), interroge le retriever du corps,
ecrit sandbox/workspace/golden_rappel_<horodatage>.json et une ligne BILAN qui NOMME le retriever.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_golden_rappel as GR  # noqa: E402


def test_main_ecrit_le_rapport_et_nomme_le_retriever(tmp_path, monkeypatch, capsys):
    jeu = tmp_path / "jeu.json"
    jeu.write_text(json.dumps({"questions": [
        {"id": "q1", "question": "a ?", "sources_attendues": ["c1"]},
        {"id": "q2", "question": "b ?", "sources_attendues": ["c2"]}]}), encoding="utf-8")
    verdicts = tmp_path / "verdicts.json"
    verdicts.write_text(json.dumps({"q1": {"verdict": "VALIDE"}, "q2": {"verdict": "VALIDE"}}), encoding="utf-8")
    monkeypatch.setattr(GR, "_preflight", lambda: (lambda q, c="", limit=5: {
        "tier": "fts5", "results": [{"source": "docs/A.md"}] if q == "a ?" else []}))
    monkeypatch.setattr(GR, "_sources_attendues", lambda ids: {"c1": "docs/A.md", "c2": "docs/B.md"})
    sortie = tmp_path / "rapport.json"
    assert GR.main(["--jeu", str(jeu), "--verdicts", str(verdicts), "--k", "10", "--sortie", str(sortie)]) == 0
    r = json.loads(sortie.read_text(encoding="utf-8"))
    assert r["rappel_source"] == 0.5 and r["rappel_id"] is None and r["mesurees"] == 2
    assert r["retriever"] == "forge_self_correction.preflight_check_verbose"
    assert r["sources_attendues_resolues"] == 2
    bilan = [l for l in capsys.readouterr().out.splitlines() if l.startswith("BILAN")]
    assert bilan and "preflight_check_verbose" in bilan[0] and "rappel_source=0.50" in bilan[0]
