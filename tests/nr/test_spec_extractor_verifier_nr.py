# -*- coding: utf-8 -*-
"""NR (31/10, choix owner « gate qui signale + nuit ») : les specs produit se COMPARENT au code, sans rien ecrire.

Mesure 31/10 : docs/specs/01_SCHEMA..06_PLAN (schema, TRD, app flow, PRD, UX, plan) suivis, figes au 26/10 23:05
(2e9a0725b) ; aucun hook ni gate ne les cite ; forge_spec_extractor ne tournait qu'a la main (--ecrire). Le mode
--verifier rend, pour chaque spec GENEREE (01, 02, 06), FRAIS / PERIME (lignes changees) / ABSENT -- la ligne d'en-tete
« Genere par ... commit, date » est ignoree -- et pour chaque spec REDIGEE par un agent (03, 04, 05) NON_COUVERT avec
son age : l'extracteur ne sait pas les produire, il le DIT au lieu de les juger. Rien n'est ecrit ; rc 1 si une spec
GENEREE est perimee/absente (signal), 0 sinon -- le gate de ci_local est NON BLOQUANT (blocking=False).
"""
# pylint: disable=missing-function-docstring,protected-access
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_spec_extractor as S  # noqa: E402


def _specs(tmp_path):
    d = tmp_path / "docs" / "specs"
    d.mkdir(parents=True)
    return d


def test_frais_perime_absent_en_ignorant_l_entete(tmp_path):
    d = _specs(tmp_path)
    (d / "01_SCHEMA.md").write_text(S._entete("Schema", "abc", "2026-10-26 23:05") + "corps A\n", encoding="utf-8")
    (d / "02_TRD.md").write_text(S._entete("TRD", "abc", "2026-10-26 23:05") + "ancien\n", encoding="utf-8")
    rendus = {"01_SCHEMA.md": S._entete("Schema", "def", "2026-10-31 13:00") + "corps A\n",
              "02_TRD.md": S._entete("TRD", "def", "2026-10-31 13:00") + "nouveau\nplus\n",
              "06_PLAN.md": "plan\n"}
    v = S.verifier(rendus, d)
    assert v["01_SCHEMA.md"]["etat"] == "FRAIS"
    assert v["02_TRD.md"]["etat"] == "PERIME" and v["02_TRD.md"]["lignes_changees"] >= 2
    assert v["06_PLAN.md"]["etat"] == "ABSENT"


def test_specs_redigees_par_agent_dites_non_couvertes(tmp_path):
    d = _specs(tmp_path)
    (d / "04_PRD.md").write_text("PRD\n", encoding="utf-8")
    v = S.verifier({}, d)
    assert v["04_PRD.md"]["etat"] == "NON_COUVERT" and v["04_PRD.md"]["age_j"] >= 0
    assert v["03_APPFLOW.md"]["etat"] == "ABSENT" and v["05_UX_AX.md"]["etat"] == "ABSENT"


def test_le_drapeau_cli_verifier_signale_et_n_ecrit_rien(tmp_path, monkeypatch, capsys):
    d = _specs(tmp_path)
    monkeypatch.setattr(S, "ROOT", tmp_path)
    rendus = {"01_SCHEMA.md": "s\n", "02_TRD.md": "t\n", "06_PLAN.md": "p\n"}
    monkeypatch.setattr(S, "rendre_tout", lambda: dict(rendus))
    assert S.main(["--verifier"]) == 1  # specs generees absentes : signal
    sortie = capsys.readouterr().out
    assert "01_SCHEMA.md" in sortie and "ABSENT" in sortie and "BILAN" in sortie
    assert sorted(x.name for x in d.iterdir()) == []  # rien d'ecrit
    for nom, txt in rendus.items():
        (d / nom).write_text(txt, encoding="utf-8")
    assert S.main(["--verifier"]) == 0  # toutes FRAICHES ; les redigees absentes ne font pas rougir


def test_le_gate_est_branche_non_bloquant_dans_ci_local():
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    i = src.find('"tools/forge_spec_extractor.py", "--verifier"')
    assert i > 0, "gate specs absent de ci_local"
    assert "blocking=False" in src[i:i + 200]
