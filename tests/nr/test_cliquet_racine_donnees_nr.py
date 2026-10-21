"""NR 19/10 -- cliquet de la RACINE DES DONNEES (item p1_racine_donnees_hors_paquet_2026-10-13).

Decision owner du 13/10 (forge_db_path.DOSSIERS_DE_DONNEES) : les modules qui construisent RAG/data/logs/sandbox/
runtime a partir de `__file__` sont trop nombreux pour etre migres un a un -- REDIRECTION A LA SOURCE. Ce qui manquait :
empecher qu'il en NAISSE de nouveaux. Un nouveau module ecrit ses donnees par `forge_db_path.racine_donnees()`.

Instrument : un nom lie a `Path(__file__)` puis utilise comme `<nom> / "<dossier de donnees>"`. Mesure du 19/10 PAR CET
INSTRUMENT : app 245/1248, tools 420/1325. Le compte ne fait que DESCENDRE : apres une migration, abaisser PLAFOND a
la valeur mesuree (le message d'echec la donne). tests/ n'est pas scanne : un instrument ne lit pas son vocabulaire.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOSSIERS = ("RAG", "data", "logs", "sandbox", "runtime")
AFFECTATION = re.compile(r"^\s*(\w+)\s*=\s*[^\n]*Path\(\s*__file__\s*\)", re.M)
PLAFOND = {"app": 245, "tools": 420}


def derive_de_file(src: str) -> bool:
    noms = {m.group(1) for m in AFFECTATION.finditer(src)}
    motif = r"\b%s\s*/\s*[\"'](?:" + "|".join(DOSSIERS) + r")\b"
    return any(re.search(motif % re.escape(n), src) for n in noms)


def _derivants(dossier: str) -> list[str]:
    out = []
    for f in sorted((ROOT / dossier).rglob("*.py")):
        if "_attic" in f.parts or "__pycache__" in f.parts:
            continue
        if derive_de_file(f.read_text(encoding="utf-8", errors="replace")):
            out.append(f.relative_to(ROOT).as_posix())
    return out


def test_temoin_positif_et_negatif():
    assert derive_de_file('ROOT = Path(__file__).resolve().parent.parent\nLOG = ROOT / "logs" / "x.log"\n')
    assert derive_de_file("BASE = Path(__file__).parents[1]\nDB = BASE / 'sandbox' / 'y.db'\n")
    assert not derive_de_file("from forge_db_path import racine_donnees\nLOG = racine_donnees() / 'logs'\n")
    assert not derive_de_file('ROOT = Path(__file__).resolve().parent\nsys.path.insert(0, str(ROOT / "app"))\n')


def test_aucun_nouveau_module_ne_derive_ses_donnees_de_file():
    for dossier, plafond in PLAFOND.items():
        n = len(_derivants(dossier))
        assert n <= plafond, ("%s : %d modules derivent leur racine de DONNEES de __file__ (plafond %d) -- un "
                              "nouveau module passe par forge_db_path.racine_donnees()" % (dossier, n, plafond))
        assert n >= plafond - 50, ("%s : %d < %d - 50 -- migration ? abaisser PLAFOND a %d (sinon l'instrument "
                                   "est casse)" % (dossier, n, plafond, n))
