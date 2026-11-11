"""NR 3/11 -- forge_mcp_json_sync --check sur un fichier ILLISIBLE : le DIRE (code 4), pas planter.

Mesure : lance sous le compte de confiance, l'outil a leve PermissionError sur %NOKIDO_WORKSPACE%\\.mcp.json
(fichier du profil owner) au lieu de rendre un verdict. Trois etats, jamais deux : trouve / absent / ILLISIBLE.
"""
import sys
from pathlib import Path

from nokido_agent.tools import forge_mcp_json_sync as S


def test_fichier_illisible_dit_illisible(tmp_path, monkeypatch, capsys):
    f = tmp_path / ".mcp.json"
    f.write_text("{}", encoding="utf-8")
    orig = Path.read_text

    def lecture(self, *a, **k):
        if Path(self) == f:
            raise PermissionError(13, "Permission denied")
        return orig(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", lecture)
    monkeypatch.setattr(sys, "argv", ["forge_mcp_json_sync.py", "--check", "--path", str(f)])
    rc = S.main()
    sortie = capsys.readouterr()
    assert rc == 4, rc
    assert "ILLISIBLE" in (sortie.out + sortie.err)
