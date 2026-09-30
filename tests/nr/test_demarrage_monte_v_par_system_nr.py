"""NR -- au demarrage, V: se monte par la tache SYSTEM, jamais avec la cle lue dans la session owner.

Decision owner du 2026-09-28 (apres l'incident V:) : la cle de V: ne vit plus qu'au coffre
RESERVE, lisible par SYSTEM seul. `nokido_start.ps1` tourne dans la session de l'owner : il
lisait la cle au guichet (copie du magasin personnel) et appelait `--mount` lui-meme. Apres un
changement de cle fait sous SYSTEM, cette copie serait perimee -- et elle mettait la cle dans la
session. Desormais le lanceur DECLENCHE la tache SYSTEM `LaForge-VC-Boot` (qui fait le meme
`--mount`, sous SYSTEM) et attend le volume ; un echec est DIT avec le dernier resultat de la tache.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PS1 = (ROOT / "tools" / "nokido_start.ps1").read_text(encoding="utf-8", errors="replace")


def _bloc_preflight_v():
    debut = PS1.index('Write-Step "Preflight volume RAG (V:)..."')
    fin = PS1.index('if (Test-Path -LiteralPath "%NOKIDO_DATA%\\embeddings.db")', debut)
    return PS1[debut:fin]


def test_le_lanceur_declenche_la_tache_system():
    bloc = _bloc_preflight_v()
    assert re.search(r'schtasks\s+/run\s+/tn\s+"LaForge-VC-Boot"', bloc), bloc


def test_le_lanceur_ne_lit_plus_la_cle_dans_la_session_owner():
    bloc = _bloc_preflight_v()
    assert "forge_at_rest_veracrypt.py" not in bloc or "--mount" not in bloc, bloc


def test_le_lanceur_attend_le_volume_et_dit_l_echec():
    bloc = _bloc_preflight_v()
    assert "%NOKIDO_DATA%\\embeddings.db" in bloc and "Dernier" in bloc, bloc
