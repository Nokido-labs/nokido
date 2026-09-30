"""NR — capacites_touchees ne fait jamais rejouer un test disparu, et le DIT.

Vecu le 2026-09-27 : l'avertissement d'invariant de governed_edit demandait de rejouer
tests/nr/test_forge_veille_campagne_nr.py, cite par le commit qui avait PROUVE la capacite,
mais absent du depot depuis. pytest rendait rc=4 (fichier introuvable) sur tout le lot.

Invariants :
- `tests` ne porte que les fichiers PRESENTS sous la racine ;
- les cites-mais-absents sont DITS dans `tests_absents`, jamais ecartes en silence ;
- une capacite dont tous les tests existent a `tests_absents` vide.
Hermetique : journal jsonl et racine dans tmp_path.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_success_oplog as oplog  # noqa: E402


def _journal(tmp_path, tests):
    log = tmp_path / "success_oplog.jsonl"
    entree = {"commit": "abc123", "date": "2026-08-30", "symptome": "capacite prouvee",
              "etat": oplog.PROUVE,
              "procedure": {"fichiers": ["tools/ci_local.py"], "tests_dans_le_commit": tests}}
    log.write_text(json.dumps(entree) + "\n", encoding="utf-8")
    return log


def test_test_disparu_dit_et_jamais_a_rejouer(tmp_path):
    (tmp_path / "tests" / "nr").mkdir(parents=True)
    (tmp_path / "tests" / "nr" / "test_present_nr.py").write_text("", encoding="utf-8")
    log = _journal(tmp_path, ["tests/nr/test_present_nr.py", "tests/nr/test_disparu_nr.py"])
    cap = oplog.capacites_touchees(["tools/ci_local.py"], log=log, root=tmp_path)
    assert len(cap) == 1
    assert cap[0]["tests"] == ["tests/nr/test_present_nr.py"]
    assert cap[0]["tests_absents"] == ["tests/nr/test_disparu_nr.py"]


def test_tous_presents_absents_vide(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("", encoding="utf-8")
    log = _journal(tmp_path, ["tests/test_a.py"])
    cap = oplog.capacites_touchees(["tools/ci_local.py"], log=log, root=tmp_path)
    assert cap[0]["tests"] == ["tests/test_a.py"]
    assert cap[0]["tests_absents"] == []


def test_racine_par_defaut_est_le_depot(tmp_path):
    # Chemin reel : sans `root`, la racine est le depot ; un test versionne y est vu present.
    log = _journal(tmp_path, ["tests/nr/test_capacites_touchees_tests_absents_nr.py",
                              "tests/nr/test_qui_n_existe_pas_nr.py"])
    cap = oplog.capacites_touchees(["tools/ci_local.py"], log=log)
    assert cap[0]["tests"] == ["tests/nr/test_capacites_touchees_tests_absents_nr.py"]
    assert cap[0]["tests_absents"] == ["tests/nr/test_qui_n_existe_pas_nr.py"]
