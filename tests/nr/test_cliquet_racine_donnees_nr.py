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
# app 245 -> 244 le 31/10 (acp_harness, acp_views migres) ; tools 420 -> 419 le 31/10 (compte sur les fichiers SUIVIS),
# puis 419 -> 405 (14 modules apparus apres le 19/10 migres ; restent les 3 services ACP et 2 modules de banc)
PLAFOND = {"app": 244, "tools": 405}


def derive_de_file(src: str) -> bool:
    noms = {m.group(1) for m in AFFECTATION.finditer(src)}
    motif = r"\b%s\s*/\s*[\"'](?:" + "|".join(DOSSIERS) + r")\b"
    return any(re.search(motif % re.escape(n), src) for n in noms)


def _suivis(dossier: str):
    """Fichiers SUIVIS par git (vue de la CI, arbre propre). None = git illisible -> repli sur le disque, dit.

    31/10 : le disque comptait 439 pour `tools` (plafond 420) quand la CI en voyait 419 -- 20 fichiers NON suivis
    (`tmp_*.py` laisses par d'autres agents dans l'arbre partage). Un cliquet qui ne mesure pas ce que la CI
    mesure rougit en local pour du jetable et ment dans les deux sens."""
    import subprocess
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "ls-files", "--", dossier],
                           capture_output=True, text=True, errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return set(r.stdout.split()) if r.returncode == 0 and r.stdout.strip() else None


def _derivants(dossier: str) -> list[str]:
    out = []
    suivis = _suivis(dossier)
    if suivis is None:
        print("[cliquet racine] git ILLISIBLE : compte sur le DISQUE (fichiers non suivis inclus)")
    for f in sorted((ROOT / dossier).rglob("*.py")):
        if suivis is not None and f.relative_to(ROOT).as_posix() not in suivis:
            continue
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


def test_un_fichier_non_suivi_n_est_pas_compte_et_git_illisible_compte_le_disque(tmp_path, monkeypatch):
    """31/10, dans les deux sens : un `tmp_*.py` non suivi ne fait pas rougir le cliquet ; sans git, on ne
    conclut pas a zero -- on compte le disque."""
    (tmp_path / "tools").mkdir()
    src = 'ROOT = Path(__file__).resolve().parent.parent\nLOG = ROOT / "logs" / "x.log"\n'
    for nom in ("forge_suivi.py", "tmp_jetable.py"):
        (tmp_path / "tools" / nom).write_text(src, encoding="utf-8")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    monkeypatch.setitem(globals(), "_suivis", lambda d: {"tools/forge_suivi.py"})
    assert _derivants("tools") == ["tools/forge_suivi.py"]
    monkeypatch.setitem(globals(), "_suivis", lambda d: None)
    assert len(_derivants("tools")) == 2


def test_aucun_nouveau_module_ne_derive_ses_donnees_de_file():
    for dossier, plafond in PLAFOND.items():
        n = len(_derivants(dossier))
        assert n <= plafond, ("%s : %d modules derivent leur racine de DONNEES de __file__ (plafond %d) -- un "
                              "nouveau module passe par forge_db_path.racine_donnees()" % (dossier, n, plafond))
        assert n >= plafond - 50, ("%s : %d < %d - 50 -- migration ? abaisser PLAFOND a %d (sinon l'instrument "
                                   "est casse)" % (dossier, n, plafond, n))
