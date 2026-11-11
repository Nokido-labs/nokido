"""NR : le hook UserPromptSubmit signale un CLI installe plus recent que celui de la session.

La banniere « Update installed · Restart to update » n'atteint pas le modele (owner 4/11) :
le signal se mesure par le dossier des versions face au champ `version` du transcript.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import claude_inbox_tick as tick


def _transcript(tmp_path, version):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"type": "user", "version": version}) + "\n", encoding="utf-8")
    return str(p)


def _versions(tmp_path, *noms):
    d = tmp_path / "versions"
    d.mkdir()
    for n in noms:
        (d / n).write_bytes(b"")
    return d


def test_version_plus_recente_installee_alerte(tmp_path):
    a = tick._alerte_maj_cli(_transcript(tmp_path, "2.1.317"), _versions(tmp_path, "2.1.316", "2.1.317", "2.1.318"))
    assert a.startswith("[maj-cli]")
    assert "2.1.318" in a and "2.1.317" in a
    assert "AskUserQuestion" in a and "reprise" in a


def test_comparaison_numerique_et_non_textuelle(tmp_path):
    a = tick._alerte_maj_cli(_transcript(tmp_path, "2.1.99"), _versions(tmp_path, "2.1.99", "2.1.100"))
    assert "2.1.100" in a


def test_session_a_jour_ne_dit_rien(tmp_path):
    assert tick._alerte_maj_cli(_transcript(tmp_path, "2.1.318"), _versions(tmp_path, "2.1.317", "2.1.318")) == ""


def test_transcript_illisible_ne_conclut_pas(tmp_path):
    d = _versions(tmp_path, "2.1.318")
    assert tick._alerte_maj_cli(str(tmp_path / "absent.jsonl"), d) == ""
    assert tick._alerte_maj_cli("", d) == ""


def test_dossier_illisible_ne_conclut_pas(tmp_path):
    assert tick._alerte_maj_cli(_transcript(tmp_path, "2.1.317"), tmp_path / "absent") == ""


def test_entrees_etrangeres_ignorees(tmp_path):
    d = _versions(tmp_path, "2.1.317", "9.9.9.tmp", "notes")
    assert tick._alerte_maj_cli(_transcript(tmp_path, "2.1.317"), d) == ""


def test_intention_capture_le_transcript(monkeypatch):
    import io

    evt = {"session_id": "s", "prompt": "p", "transcript_path": "C:/x/t.jsonl"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(evt)))
    tick._intention()
    assert tick._TRANSCRIPT == "C:/x/t.jsonl"
