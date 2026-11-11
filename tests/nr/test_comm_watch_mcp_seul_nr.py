"""NR : la brique claude_code.mcp n'alerte que si la configuration MCP change.

~/.claude.json porte aussi des compteurs réécrits à chaque session (numStartups, astuces, coûts) : son empreinte
entière changeait sans qu'aucun serveur MCP ne bouge. Un JSON illisible reste un changement visible, jamais un silence.
"""
import importlib.util
import json
import pathlib

_CHEMIN = pathlib.Path(__file__).resolve().parents[2] / "tools" / "forge_comm_watch.py"
_spec = importlib.util.spec_from_file_location("fcw_nr", _CHEMIN)
fcw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fcw)


def _ecrire(chemin, **champs):
    base = {"numStartups": 1, "mcpServers": {"hub": {"url": "http://x"}},
            "projects": {"C:/p": {"mcpServers": {"local": {"command": "a"}}, "lastCost": 1}}}
    base.update(champs)
    chemin.write_text(json.dumps(base), encoding="utf-8")


def _empreinte(chemin):
    return fcw._fingerprint(chemin, "json_mcp")["hash"]


def test_compteurs_ne_changent_pas_l_empreinte(tmp_path):
    f = tmp_path / ".claude.json"
    _ecrire(f)
    avant = _empreinte(f)
    _ecrire(f, numStartups=99, tipsHistory={"a": 3},
            projects={"C:/p": {"mcpServers": {"local": {"command": "a"}}, "lastCost": 42}})
    assert _empreinte(f) == avant


def test_serveur_global_change_l_empreinte(tmp_path):
    f = tmp_path / ".claude.json"
    _ecrire(f)
    avant = _empreinte(f)
    _ecrire(f, mcpServers={"hub": {"url": "http://y"}})
    assert _empreinte(f) != avant


def test_serveur_de_projet_change_l_empreinte(tmp_path):
    f = tmp_path / ".claude.json"
    _ecrire(f)
    avant = _empreinte(f)
    _ecrire(f, projects={"C:/p": {"mcpServers": {"local": {"command": "b"}}}})
    assert _empreinte(f) != avant


def test_ordre_des_cles_sans_effet(tmp_path):
    f = tmp_path / ".claude.json"
    _ecrire(f, mcpServers={"a": {"url": "1"}, "b": {"url": "2"}})
    avant = _empreinte(f)
    _ecrire(f, mcpServers={"b": {"url": "2"}, "a": {"url": "1"}})
    assert _empreinte(f) == avant


def test_json_illisible_se_voit(tmp_path):
    f = tmp_path / ".claude.json"
    _ecrire(f)
    avant = _empreinte(f)
    f.write_text("{ tronqué", encoding="utf-8")
    apres = fcw._fingerprint(f, "json_mcp")
    assert apres["exists"] is True and apres["hash"] != avant and apres["hash"].startswith("ILLISIBLE:")


def test_fichier_absent_reste_absent(tmp_path):
    assert fcw._fingerprint(tmp_path / "absent.json", "json_mcp")["exists"] is False


def test_brique_claude_utilise_le_mode_mcp():
    assert [b[2] for b in fcw.WATCHED if b[0] == "claude_code.mcp"] == ["json_mcp"]


def test_mode_file_inchange(tmp_path):
    f = tmp_path / "c.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    avant = fcw._fingerprint(f, "file")["hash"]
    f.write_text('{"a": 2}', encoding="utf-8")
    assert fcw._fingerprint(f, "file")["hash"] != avant
