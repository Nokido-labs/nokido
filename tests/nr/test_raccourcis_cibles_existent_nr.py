"""NR — l'installateur de raccourcis ne pointe que vers des cibles qui EXISTENT.

Mesure 2026-09-06 : `tools/install_shortcuts.ps1` creait quatre raccourcis dont TROIS
visaient `LaForge Control Panel.bat` et `LaForge Tray.bat`, renommes en `Nokido ...`
depuis. Windows cree un raccourci mort sans broncher : l'echec n'apparait qu'au
double-clic, des mois plus tard. Le Control Panel avait ainsi disparu du Bureau.

Le test lit le script REEL et verifie, pour chaque `TargetPath` qui designe un fichier
du depot, que ce fichier existe. Les cibles URL (http://) sont ignorees : rien a
verifier sur disque.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PS1 = ROOT / "tools" / "install_shortcuts.ps1"
CIBLE = re.compile(r'"\$ROOT\\([^"]+)"')


def test_toutes_les_cibles_fichier_existent():
    src = PS1.read_text(encoding="utf-8", errors="replace")
    cibles = sorted(set(CIBLE.findall(src)))
    assert cibles, "aucune cible \\$ROOT trouvee : le script a change de forme"
    absentes = [c for c in cibles if not (ROOT / c.replace("\\", "/")).exists()]
    assert not absentes, (
        "cible(s) de raccourci absente(s) du depot :\n"
        + "\n".join(f"  - {c}" for c in absentes)
        + "\n\nUn raccourci vers un fichier absent est cree sans erreur par Windows."
    )


def test_le_script_verifie_lui_meme_l_existence_avant_de_creer():
    src = PS1.read_text(encoding="utf-8", errors="replace")
    assert "Test-Path $Cible" in src, "le script doit refuser de creer un raccourci mort"
    assert "SAUTE" in src and "ABSENTE" in src, "un saut doit etre DIT, pas silencieux"


def test_le_script_reste_ascii():
    # Un .ps1 non-ASCII casse le demarrage sous PowerShell 5.1 (gate .ps1 du depot).
    brut = PS1.read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(brut) if b > 0x7F]
    assert not non_ascii, f"{len(non_ascii)} octet(s) non-ASCII, premier a l'offset {non_ascii[0][0]}"
