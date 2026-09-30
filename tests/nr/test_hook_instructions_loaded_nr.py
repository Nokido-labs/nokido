"""NR — capteur InstructionsLoaded (26/09).

Contrat, par le POINT D'ENTREE reel (le hook est lance par Claude Code avec le JSON sur stdin) :
  - un chargement ajoute une ligne : fichier, raison, type, taille, champs non communs ;
  - une taille illisible vaut ILLISIBLE, jamais 0 ;
  - stdin invalide : sortie 0, rien sur stdout (la session ne se bloque jamais), la cause sur stderr ;
  - `--bilan` agrege par fichier et COMPTE les lignes illisibles au lieu de les taire.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.26)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
SCRIPT = RACINE / "tools" / "hook_instructions_loaded.py"
sys.path.insert(0, str(RACINE / "tools"))


def _lancer(journal: Path, stdin: str, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["NOKIDO_INSTRUCTIONS_JOURNAL"] = str(journal)
    env["PYTHONNOUSERSITE"] = "1"
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env, timeout=60)


def _evt(fichier, raison="session_start", **autres):
    return json.dumps({"session_id": "s1", "transcript_path": "t.jsonl", "cwd": "c",
                       "hook_event_name": "InstructionsLoaded", "file_path": str(fichier),
                       "memory_type": "Project", "load_reason": raison, **autres})


def test_un_chargement_ajoute_une_ligne(tmp_path):
    regle = tmp_path / "CLAUDE.md"
    regle.write_text("x" * 1234, encoding="utf-8")
    journal = tmp_path / "j.jsonl"
    r = _lancer(journal, _evt(regle, "path_glob_match", globs=["app/**"]))
    assert r.returncode == 0 and r.stdout == ""
    [ligne] = [json.loads(x) for x in journal.read_text(encoding="utf-8").splitlines()]
    assert ligne["file_path"] == str(regle) and ligne["octets"] == 1234
    assert ligne["load_reason"] == "path_glob_match" and ligne["memory_type"] == "Project"
    assert ligne["autres"] == {"globs": ["app/**"]}


def test_taille_illisible_n_est_pas_zero(tmp_path):
    journal = tmp_path / "j.jsonl"
    assert _lancer(journal, _evt(tmp_path / "absent.md")).returncode == 0
    ligne = json.loads(journal.read_text(encoding="utf-8"))
    assert str(ligne["octets"]).startswith("ILLISIBLE")


def test_stdin_invalide_ne_bloque_rien_et_le_dit(tmp_path):
    journal = tmp_path / "j.jsonl"
    r = _lancer(journal, "{pas du json")
    assert r.returncode == 0 and r.stdout == ""
    assert "non consigne" in r.stderr
    assert not journal.exists()


def test_bilan_agrege_et_compte_l_illisible(tmp_path):
    regle = tmp_path / "RULES.md"
    regle.write_text("y" * 10, encoding="utf-8")
    journal = tmp_path / "j.jsonl"
    _lancer(journal, _evt(regle, "session_start"))
    _lancer(journal, _evt(regle, "compact"))
    with open(journal, "a", encoding="utf-8") as h:
        h.write("ligne cassee\n")
    r = _lancer(journal, "", "--bilan")
    b = json.loads(r.stdout)
    assert b["lignes_illisibles"] == 1 and b["lignes_lues"] == 2
    [f] = b["fichiers"]
    assert f["chargements"] == 2 and f["raisons"] == {"session_start": 1, "compact": 1}
    assert f["octets"] == 10 and f["sessions"] == 1


def test_bilan_sans_journal_dit_absent(tmp_path):
    b = json.loads(_lancer(tmp_path / "rien.jsonl", "", "--bilan").stdout)
    assert b["etat"].startswith("ABSENT")
