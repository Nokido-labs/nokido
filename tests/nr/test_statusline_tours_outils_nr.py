# -*- coding: utf-8 -*-
"""NR -- P0 economie de contexte (decision owner 20/10, reprise 1/11) : la statusline montre les 4 compteurs bruts
mais ni le nombre de TOURS ni celui des APPELS D'OUTILS. Le .jsonl ecrit UNE ligne par bloc : un tour = un
message.id assistant DISTINCT (dedoublonne), un appel = un bloc tool_use. Lecture INCREMENTALE (offset memorise) :
un rafraichissement ne relit pas le transcript entier ; changer de transcript ou un fichier raccourci repart de zero ;
une ligne partielle (en cours d'ecriture) n'est pas comptee avant d'etre complete."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import nokido_statusline as S  # noqa: E402


def _l(mid, *types):
    return json.dumps({"message": {"role": "assistant", "id": mid,
                                   "content": [{"type": t} for t in types]}}) + "\n"


def test_tours_dedoublonnes_et_outils_comptes(tmp_path):
    tr = tmp_path / "s.jsonl"
    tr.write_text(_l("m1", "text") + _l("m1", "tool_use") + json.dumps({"message": {"role": "user"}}) + "\n"
                  + _l("m2", "tool_use", "tool_use") + _l("m3", "text"), encoding="utf-8")
    etat = tmp_path / "etat.json"
    assert S._tours({"transcript_path": str(tr)}, etat=etat) == (3, 3)


def test_incremental_et_ligne_partielle(tmp_path):
    tr = tmp_path / "s.jsonl"
    etat = tmp_path / "etat.json"
    tr.write_text(_l("m1", "tool_use"), encoding="utf-8")
    assert S._tours({"transcript_path": str(tr)}, etat=etat) == (1, 1)
    with tr.open("a", encoding="utf-8") as f:
        f.write(_l("m1", "text") + _l("m2", "tool_use") + '{"message": {"role": "assis')
    assert S._tours({"transcript_path": str(tr)}, etat=etat) == (2, 2)
    with tr.open("a", encoding="utf-8") as f:
        f.write('tant", "id": "m3", "content": [{"type": "tool_use"}]}}\n')
    assert S._tours({"transcript_path": str(tr)}, etat=etat) == (3, 3)
    assert json.loads(etat.read_text(encoding="utf-8"))["offset"] == tr.stat().st_size


def test_autre_transcript_repart_de_zero_et_absent_rend_none(tmp_path):
    etat = tmp_path / "etat.json"
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text(_l("m1", "text") + _l("m2", "text"), encoding="utf-8")
    b.write_text(_l("x1", "tool_use"), encoding="utf-8")
    assert S._tours({"transcript_path": str(a)}, etat=etat) == (2, 0)
    assert S._tours({"transcript_path": str(b)}, etat=etat) == (1, 1)
    assert S._tours({}, etat=etat) is None
    assert S._tours({"transcript_path": str(tmp_path / "absent.jsonl")}, etat=etat) is None


def test_la_ligne_affiche_tours_et_outils():
    src = Path(S.__file__).read_text(encoding="utf-8")
    assert "_tours(charge)" in src and '"TOURS %d' in src
