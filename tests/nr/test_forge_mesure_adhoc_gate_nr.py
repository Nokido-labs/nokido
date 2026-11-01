"""NR -- effet de forge_mesure_adhoc_gate (cliquet couverture : module ajoute sans test, CI 50221f9ca).

Verifie le COMPTAGE (pas l'import seul) sur une racine temporaire, et que le point d'entree reste informatif (rc 0).
Repris de la livraison OPENCODE_GLM (job_36e92038), marqueur pytest inconnu retire.
"""
from __future__ import annotations

from pathlib import Path

from nokido_agent.tools import forge_mesure_adhoc_gate as gate


def test_forge_mesure_adhoc_gate_compte_sans_crash(tmp_path: Path):
    rac = tmp_path
    (rac / "app").mkdir()
    (rac / "tools").mkdir()
    (rac / "app" / "forge_x.py").write_text('x = "ILLISIBLE"\n', encoding="utf-8")
    (rac / "tools" / "forge_y.py").write_text("def verdict():\n    return 1\n", encoding="utf-8")
    res = gate.compter(rac)
    assert res["litteraux"] >= 1
    assert res["verdict_locaux"] >= 1
    assert res["total"] == res["litteraux"] + res["verdict_locaux"]
    assert res["fichiers"] >= 1


def test_l_instrument_ne_se_compte_pas_lui_meme(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "forge_mesure_adhoc_gate.py").write_text('X = "ILLISIBLE"\n', encoding="utf-8")
    assert gate.compter(tmp_path)["total"] == 0


def test_un_fichier_illisible_est_compte_jamais_saute(tmp_path: Path, monkeypatch):
    """Un fichier NON LU n'est pas un fichier sans mesure ad hoc : le taire sous-estimerait la base."""
    (tmp_path / "app").mkdir()
    (tmp_path / "tools").mkdir()
    cible = tmp_path / "app" / "forge_z.py"
    cible.write_text('x = "UNKNOWN"\n', encoding="utf-8")
    lire = Path.read_text

    def _lire(self, *a, **k):
        if self == cible:
            raise PermissionError("refuse")
        return lire(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", _lire)
    res = gate.compter(tmp_path)
    assert res["illisibles"] == 1
    assert res["total"] == 0


def test_forge_mesure_adhoc_gate_main_retourne_0(capsys):
    assert gate.main() == 0
    assert "mesures ad hoc" in capsys.readouterr().out
