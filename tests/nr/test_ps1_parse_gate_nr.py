"""NR — un .ps1 casse doit BLOQUER le commit, comme un .ts casse.

Symetrie d'organe : un .ts casse tue le SUPERVISEUR (d'ou _ts_parse_gate), un .ps1
casse tue le DEMARRAGE — `tools/nokido_start.ps1` amorce les 55 services, et rien ne
le parse-checkait. Mesure 2026-08-26 : un tiret cadratin et des guillemets
typographiques introduits dans ce fichier ASCII PUR le rendaient non parsable sous
PS 5.1. Le commit serait passe ; la panne serait apparue au demarrage suivant.

Un garde qui n'attrape pas le defaut qui l'a motive est un garde decoratif. On lui
donne donc les deux cas, et on verifie aussi le troisieme etat : quand l'analyseur
n'est pas joignable, il SKIPPE en le disant — il ne rend jamais un vert par defaut.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus powershell (code appele, Windows)
#   (l.87)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

gate = pytest.importorskip("forge_git_gate")

_PS = shutil.which("powershell") or shutil.which("pwsh")
besoin_ps = pytest.mark.skipif(not _PS, reason="powershell absent de cette machine")

SAIN = """# script sain, ASCII pur
$x = 1
if ($x -eq 1) { Write-Host "ok" } else { Write-Host "non" }
"""

# Exactement le defaut paye : un `try` dont le `catch` devient inatteignable parce
# qu'un caractere non-ASCII casse le parse sous PS 5.1.
CASSE = """try {
    Write-Host "debut"
    if ($true) {
        Write-Host "sans accolade fermante"
} catch {
    Write-Host "jamais atteint"
}
"""


@pytest.fixture
def faux_depot(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    return tmp_path


@besoin_ps
def test_un_ps1_casse_bloque(faux_depot):
    (faux_depot / "casse.ps1").write_text(CASSE, encoding="utf-8")
    assert gate._ps1_parse_gate(["casse.ps1"]) == 1


@besoin_ps
def test_un_ps1_sain_passe(faux_depot):
    (faux_depot / "sain.ps1").write_text(SAIN, encoding="utf-8")
    assert gate._ps1_parse_gate(["sain.ps1"]) == 0


def test_aucun_ps1_stage_ne_bloque_rien(faux_depot):
    assert gate._ps1_parse_gate(["app/forge_x.py", "docs/a.md"]) == 0


def test_analyseur_absent_skippe_en_le_disant(faux_depot, monkeypatch, capsys):
    """« Je ne peux pas voir » n'est pas « c'est bon » — mais ne bloque pas non plus."""
    (faux_depot / "casse.ps1").write_text(CASSE, encoding="utf-8")
    monkeypatch.setattr(gate.shutil if hasattr(gate, "shutil") else shutil, "which",
                        lambda _n: None, raising=False)
    import shutil as _sh
    monkeypatch.setattr(_sh, "which", lambda _n: None)
    assert gate._ps1_parse_gate(["casse.ps1"]) == 0
    sortie = capsys.readouterr().out
    assert "NON verifie" in sortie, "le skip doit etre ANNONCE, pas silencieux"


@besoin_ps
def test_le_lanceur_reel_de_la_flotte_parse():
    """Contre-epreuve sur la cible : si nokido_start.ps1 ne parse pas, rien ne demarre."""
    assert (ROOT / "tools" / "nokido_start.ps1").exists()
    assert gate._ps1_parse_gate(["tools/nokido_start.ps1"]) == 0
