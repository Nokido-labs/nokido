"""NR : un CLI qui ecrit du cp1252 (0xe9) ne doit pas faire lever le lecteur ; remplacement signale."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import forge_free_tier_census as C  # noqa: E402


def _faux_vibe(tmp_path):
    py = tmp_path / "fake.py"
    py.write_bytes(b"import sys\nsys.stdout.buffer.write(b'caf\\xe9 ok')\n")
    if os.name == "nt":
        b = tmp_path / "vibe.cmd"
        b.write_text('@"%s" "%s" %%*\r\n' % (sys.executable, py))
    else:
        b = tmp_path / "vibe"
        b.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, py))
        b.chmod(0o755)
    return b


def test_cli_cp1252_lu_et_remplacement_note(tmp_path, monkeypatch):
    b = _faux_vibe(tmp_path)
    monkeypatch.setenv("LAFORGE_VIBE_BIN", str(b))
    r = C._appel_cli("cli:vibe", "m", {"prompt": "x"})
    assert "caf" in r["texte"] and "�" in r["texte"]
    assert r.get("decodage_remplace") is True
