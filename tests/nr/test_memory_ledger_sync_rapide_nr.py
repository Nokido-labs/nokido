# -*- coding: utf-8 -*-
"""NR — au SessionStart, le ledger memoire n'ouvre plus les fiches qui n'ont pas bouge.

Mesure du 2026-09-26, APRES l'index (fname, seq) : le hook
`forge_memory_compactor.py --auto` etait ENCORE tue a 8 s au demarrage de Claude Code.
Chrono par phase, meme machine, a deux heures d'ecart :
  - cache chaud : lecture + sha256 des 975 fiches .md = 0,26 s ;
  - a froid     : la meme lecture = 6,0 s (~6 ms par fiche ouverte).
Le reste du chemin (index, ajout de version, prune, reingestion) tenait en 0,5 s.
`sync()` ouvrait et hachait TOUTES les fiches pour en trouver une a trois changees.

Contrat verrouille ici :
  - `sync(rapide=True)` n'ouvre pas une fiche dont la taille et la date de
    modification n'ont pas bouge depuis sa derniere entree ;
  - il voit une fiche dont la taille OU la date a change, et une fiche recreee ;
  - la limite du filtre (contenu change a taille et date identiques) est couverte
    par une tranche tournante, hachee quoi qu'il arrive, qui passe sur TOUTES les
    fiches sans jamais les prendre toutes le meme jour ;
  - `sync()` sans drapeau hache TOUT : c'est le filet des appelants qui ecrivent ;
  - le hook `--auto` emprunte bien le chemin rapide (point d'entree reel).
"""
# pylint: disable=protected-access
#   `_TRANCHES` / `_dans_la_tranche_du_jour` sont le mecanisme meme que ce NR verrouille.
import os
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import nokido_agent.tools as paquet  # noqa: E402
from nokido_agent.tools import forge_memory_ledger as ml  # noqa: E402

_PASSE = time.time() - 3600  # date de modification anterieure a toute entree du ledger


def _dossier(tmp_path: Path) -> Path:
    """Trois fiches datees d'une heure, deja enregistrees par une passe complete."""
    d = tmp_path / "memory"
    d.mkdir()
    for nom in ("a.md", "b.md", "c.md"):
        f = d / nom
        f.write_text("---\nname: %s\n---\ncorps\n" % nom, encoding="utf-8")
        os.utime(f, (_PASSE, _PASSE))
    ml.sync(d)
    return d


@pytest.fixture
def lus(monkeypatch):
    """Noms des fiches OUVERTES (Path.read_bytes) : c'est ce qui coute a froid."""
    noms = []
    vrai = Path.read_bytes

    def espion(self):
        noms.append(self.name)
        return vrai(self)

    monkeypatch.setattr(Path, "read_bytes", espion)
    return noms


@pytest.fixture
def hors_tranche(monkeypatch):
    monkeypatch.setattr(ml, "_dans_la_tranche_du_jour", lambda _nom: False)


def test_rapide_n_ouvre_pas_une_fiche_inchangee(tmp_path, lus, hors_tranche):
    d = _dossier(tmp_path)
    lus.clear()
    assert ml.sync(d, rapide=True)["appended"] == 0
    assert lus == [], "fiches inchangees ouvertes : %s" % lus


def test_rapide_voit_une_taille_changee(tmp_path, lus, hors_tranche):
    d = _dossier(tmp_path)
    f = d / "b.md"
    f.write_text("---\nname: b.md\n---\ncorps plus long\n", encoding="utf-8")
    os.utime(f, (_PASSE, _PASSE))  # date remise dans le passe : seule la taille parle
    lus.clear()
    assert ml.sync(d, rapide=True)["appended"] == 1
    assert lus == ["b.md"]


def test_rapide_voit_une_date_changee_a_taille_egale(tmp_path, lus, hors_tranche):
    d = _dossier(tmp_path)
    f = d / "b.md"
    f.write_text("---\nname: b.md\n---\nCORPS\n", encoding="utf-8")  # meme longueur
    futur = time.time() + 60
    os.utime(f, (futur, futur))
    lus.clear()
    assert ml.sync(d, rapide=True)["appended"] == 1
    assert lus == ["b.md"]


def test_rapide_voit_une_fiche_supprimee_puis_recreee(tmp_path, hors_tranche):
    d = _dossier(tmp_path)
    f = d / "b.md"
    contenu = f.read_bytes()
    f.unlink()
    assert ml.sync(d, rapide=True)["appended"] == 1  # deleted
    f.write_bytes(contenu)
    os.utime(f, (_PASSE, _PASSE))  # meme taille, date ancienne : seul l'evenement parle
    assert ml.sync(d, rapide=True)["appended"] == 1  # recreated


def test_la_tranche_du_jour_rattrape_ce_que_taille_et_date_cachent(tmp_path, lus, monkeypatch):
    """Limite assumee du filtre : contenu change, taille ET date identiques."""
    monkeypatch.setattr(ml, "_dans_la_tranche_du_jour", lambda _nom: False)
    d = _dossier(tmp_path)
    f = d / "b.md"
    f.write_text("---\nname: b.md\n---\nCORPS\n", encoding="utf-8")
    os.utime(f, (_PASSE, _PASSE))
    assert ml.sync(d, rapide=True)["appended"] == 0  # hors tranche : invisible
    monkeypatch.setattr(ml, "_dans_la_tranche_du_jour", lambda nom: nom == "b.md")
    lus.clear()
    assert ml.sync(d, rapide=True)["appended"] == 1
    assert lus == ["b.md"]


def test_la_tranche_passe_sur_toutes_les_fiches_sans_les_prendre_toutes():
    noms = ["f%03d.md" % i for i in range(300)]
    par_jour = [{n for n in noms if ml._dans_la_tranche_du_jour(n, jour)}
                for jour in range(ml._TRANCHES)]
    assert set().union(*par_jour) == set(noms), "des fiches ne sont JAMAIS rehachees"
    assert max(len(t) for t in par_jour) < len(noms) / 2, "la tranche annule le gain"


def test_sans_drapeau_sync_hache_tout(tmp_path, lus):
    d = _dossier(tmp_path)
    lus.clear()
    ml.sync(d)
    assert sorted(lus) == ["a.md", "b.md", "c.md"]


def test_le_hook_auto_emprunte_le_chemin_rapide(tmp_path, monkeypatch):
    """Point d'entree reel : `forge_memory_compactor.py --auto` (SessionStart)."""
    from nokido_agent.tools import forge_memory_compactor as mc  # noqa: PLC0415

    d = tmp_path / "memory"
    d.mkdir()
    (d / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
    appels = []
    monkeypatch.setattr(ml, "sync", lambda *_a, **k: appels.append(k) or {"appended": 0})
    monkeypatch.setattr(ml, "prune", lambda *_a, **_k: None)
    faux = types.ModuleType("forge_memory_ingest")
    faux.ingerer = lambda **_k: 0
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_memory_ingest", faux)
    monkeypatch.setattr(paquet, "forge_memory_ingest", faux, raising=False)
    monkeypatch.setattr(sys, "argv", ["x", "--auto", "--memory-dir", str(d)])
    mc.main()
    assert appels == [{"rapide": True}], appels
