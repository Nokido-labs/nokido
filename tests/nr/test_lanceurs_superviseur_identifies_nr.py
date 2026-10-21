# -*- coding: utf-8 -*-
"""NR -- les lanceurs de la pile parlent au superviseur sous leur NOM, et le demarrage ne reveille plus LlamaNative.

Audit RAM owner 18/10 (enquete AGY job_c1c29136, verifiee dans le code) : a CHAQUE relance de pile, un appelant
ANONYME (`agent_declare "?"` dans sandbox/supervisor_ordres.jsonl) activait NokidoLlamaNative puis demarrait
NokidoEmbedTrigger ; c'etait tools/nokido_start.ps1. Son commentaire disait l'activation sans effet (404 « not in
llm pool ») -- vrai jusqu'au 15/10 ; depuis, `llm/activate` reveille un `disabled` et le demarrage chargeait ~7 Go
(mlock) que la regulation rendormait aussitot. Decisions owner : retirer l'activation ; nommer les appelants
(l'en-tete n'est que journalise par le superviseur, il ne change aucune autorisation).

Contrats (lecture statique des scripts) :
  1. tout `Invoke-RestMethod` vers :8765/supervisor/ porte un en-tete `LaForge-Agent-Name` ;
  2. nokido_start.ps1 n'adresse plus aucune requete a `llm/activate/NokidoLlamaNative`.
"""
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
LANCEURS = ("tools/nokido_start.ps1", "tools/nokido_stop.ps1")


def _appels_superviseur(texte: str) -> list:
    """Chaque instruction Invoke-RestMethod (lignes de continuation ``` jointes) qui vise :8765/supervisor/."""
    lignes = texte.splitlines()
    out, i = [], 0
    while i < len(lignes):
        if "Invoke-RestMethod" in lignes[i] and not lignes[i].lstrip().startswith("#"):
            bloc = [lignes[i]]
            while bloc[-1].rstrip().endswith("`") and i + 1 < len(lignes):
                i += 1
                bloc.append(lignes[i])
            instr = " ".join(bloc)
            if ":8765/supervisor/" in instr:
                out.append(instr)
        i += 1
    return out


@pytest.mark.parametrize("chemin", LANCEURS)
def test_chaque_appel_au_superviseur_porte_un_nom(chemin):
    appels = _appels_superviseur((RACINE / chemin).read_text(encoding="utf-8", errors="replace"))
    assert appels, "aucun appel au superviseur trouve dans %s : le NR ne mesurerait rien" % chemin
    anonymes = [a.strip()[:120] for a in appels if "LaForge-Agent-Name" not in a]
    assert not anonymes, anonymes


def test_le_demarrage_ne_reveille_plus_llamanative():
    appels = _appels_superviseur((RACINE / "tools/nokido_start.ps1").read_text(encoding="utf-8", errors="replace"))
    assert not [a for a in appels if re.search(r"llm/activate/NokidoLlamaNative", a)]
