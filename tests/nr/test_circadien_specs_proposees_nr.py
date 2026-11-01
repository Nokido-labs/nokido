# -*- coding: utf-8 -*-
"""NR (31/10, choix owner « gate qui signale + nuit ») : la nuit, les specs perimees sont PROPOSEES, jamais ecrites.

docs/specs etait fige au 26/10 sans signal. Le gate de jour (ci_local, forge_spec_extractor --verifier) signale ;
la nuit, une action de phase REM rend les specs generees, les compare, et DEPOSE les perimees ou absentes dans
sandbox/workspace/specs_proposees/ (+ verdict.json) : docs/specs n'est jamais touche -- le commit reste un geste
relu. Comme toute action lourde de phase : jamais depuis pytest, jamais hors de sa phase.
"""
# pylint: disable=missing-function-docstring,protected-access
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_circadian as fc  # noqa: E402


def _extracteur(rendus, verdict):
    return types.SimpleNamespace(rendre_tout=lambda: dict(rendus), verifier=lambda r, d: dict(verdict))


def test_les_perimees_sont_proposees_docs_specs_intact(tmp_path):
    specs = tmp_path / "docs" / "specs"
    specs.mkdir(parents=True)
    (specs / "02_TRD.md").write_text("ancien\n", encoding="utf-8")
    ext = _extracteur({"01_SCHEMA.md": "s\n", "02_TRD.md": "nouveau\n", "06_PLAN.md": "p\n"},
                      {"01_SCHEMA.md": {"etat": "FRAIS"}, "02_TRD.md": {"etat": "PERIME", "lignes_changees": 2},
                       "06_PLAN.md": {"etat": "ABSENT"}, "04_PRD.md": {"etat": "NON_COUVERT", "age_j": 5.0}})
    r = fc._proposer_specs(tmp_path, ext)
    prop = tmp_path / "sandbox" / "workspace" / "specs_proposees"
    assert sorted(r["proposees"]) == ["02_TRD.md", "06_PLAN.md"]
    assert (prop / "02_TRD.md").read_text(encoding="utf-8") == "nouveau\n"
    assert not (prop / "01_SCHEMA.md").exists() and not (prop / "04_PRD.md").exists()
    assert json.loads((prop / "verdict.json").read_text(encoding="utf-8"))["04_PRD.md"]["etat"] == "NON_COUVERT"
    assert (specs / "02_TRD.md").read_text(encoding="utf-8") == "ancien\n"  # jamais ecrit


def test_action_de_phase_presente_et_gardee():
    acts = [a for a in fc.PHASE_PROGRAM[fc.Phase.REM] if a.name == "specs_produit"]
    assert acts and acts[0].handler is fc._regenerer_specs and acts[0].service is None
    assert fc._regenerer_specs()["specs"] == "sous pytest"  # jamais depuis un test
