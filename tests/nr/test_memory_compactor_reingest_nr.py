# -*- coding: utf-8 -*-
"""NR — le hook SessionStart REINGERE l'index apres l'avoir reecrit.

Sans ce cablage, le chemin volatil repare le 2026-09-04 se re-perime a chaque
session : le compacteur reecrit MEMORY.md, personne ne le repasse au RAG, et le
lexical sert la version d'avant. Le defaut serait MUET — c'est sa signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

mc = pytest.importorskip("forge_memory_compactor")


def _memoire(tmp_path: Path, taille_ko: float) -> Path:
    d = tmp_path / "memory"
    d.mkdir()
    corps = "- [une entree](feedback_x_2026-01-01.md) remplissage\n"
    n = max(1, int(taille_ko * 1024 / len(corps)))
    (d / "MEMORY.md").write_text("# MEMORY\n" + corps * n, encoding="utf-8")
    return d


def _brancher(monkeypatch, appels: list):
    """Substitue l'ingesteur ET le ledger, pour n'observer que le cablage."""
    import types

    faux = types.ModuleType("forge_memory_ingest")
    faux.ingerer = lambda appliquer=False, limite=0, fichier="": appels.append(fichier) or 0
    monkeypatch.setitem(sys.modules, "forge_memory_ingest", faux)
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_memory_ingest", faux)

    faux_ledger = types.ModuleType("forge_memory_ledger")
    faux_ledger.sync = lambda *_a, **_k: {"appended": 0}
    faux_ledger.prune = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "forge_memory_ledger", faux_ledger)
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_memory_ledger", faux_ledger)


def _lancer(monkeypatch, d: Path):
    monkeypatch.setattr(sys, "argv", ["x", "--auto", "--memory-dir", str(d)])
    mc.main()


def test_l_index_est_reingere_meme_SANS_compaction(tmp_path, monkeypatch):
    """Le cas le PLUS FREQUENT : l'index a change mais ne franchit pas le seuil.

    Placer la reingestion apres la compaction la rendrait inatteignable dans ce
    cas — donc perimee la plupart du temps, et silencieusement.
    """
    d = _memoire(tmp_path, taille_ko=2.0)  # tres en dessous du seuil de 17 Ko
    appels: list = []
    _brancher(monkeypatch, appels)
    _lancer(monkeypatch, d)
    assert appels == ["MEMORY.md"], (
        "sous le seuil, l'index doit quand meme etre reingere (appels=%r)" % appels
    )


def test_au_dessus_du_seuil_auto_SIGNALE_sans_compacter_ni_reingerer_deux_fois(
        tmp_path, monkeypatch, capsys):
    """REQUALIFIE le 2026-09-11 — l'ancien contrat n'a plus d'objet, il n'est pas abandonne.

    Ce test exigeait DEUX reingestions : une avant, une apres la compaction
    automatique. Par arbitrage owner, `--auto` ne compacte plus (il mesure et
    signale) : il n'y a donc plus de seconde reecriture a rattraper, et exiger deux
    appels ferait echouer la CI sur un comportement VOULU.

    Ce que le contrat devient, et qu'on verrouille ici :
      - au-dessus du seuil, l'index n'est PAS reecrit ;
      - le signal est emis, avec la taille — un index qui grossit ne doit pas se
        confondre avec un compacteur en panne ;
      - une SEULE reingestion, celle du debut, qui reste le cas frequent couvert par
        le test precedent.

    BORNE CONNUE, a ne pas perdre de vue : une compaction MANUELLE reecrit l'index
    sans repasser par ce chemin, donc le lexical sert la version d'avant JUSQU'AU
    prochain SessionStart, qui reingere en premiere action. L'ecart est borne a une
    session ; il serait non borne si la reingestion d'ouverture disparaissait, d'ou
    l'assertion sur l'appel unique plutot que sur zero appel.
    """
    d = _memoire(tmp_path, taille_ko=30.0)  # au-dessus du seuil ET du cap de load
    avant = (d / "MEMORY.md").read_bytes()
    appels: list = []
    _brancher(monkeypatch, appels)
    _lancer(monkeypatch, d)

    assert (d / "MEMORY.md").read_bytes() == avant, "--auto a reecrit l'index"
    assert not (d / "MEMORY_ARCHIVE.md").exists(), "--auto a cree une archive froide"
    assert appels.count("MEMORY.md") == 1, (
        "une seule reingestion attendue depuis que --auto ne compacte plus (appels=%r)"
        % appels
    )
    assert "CAP" in capsys.readouterr().out.upper(), "le depassement du cap n'est pas signale"


def test_un_echec_de_reingestion_est_DIT_et_non_fatal(tmp_path, monkeypatch, capsys):
    """Un lexical perime qui se tait est exactement ce qu'on corrige."""
    import types

    d = _memoire(tmp_path, taille_ko=2.0)
    casse = types.ModuleType("forge_memory_ingest")

    def _boum(**_k):
        raise RuntimeError("base verrouillee")

    casse.ingerer = _boum
    monkeypatch.setitem(sys.modules, "forge_memory_ingest", casse)
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_memory_ingest", casse)
    faux_ledger = types.ModuleType("forge_memory_ledger")
    faux_ledger.sync = lambda *_a, **_k: {"appended": 0}
    faux_ledger.prune = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "forge_memory_ledger", faux_ledger)
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_memory_ledger", faux_ledger)

    _lancer(monkeypatch, d)  # ne doit PAS lever
    sortie = capsys.readouterr().out
    assert "IMPOSSIBLE" in sortie and "base verrouillee" in sortie, (
        "l'echec doit nommer sa cause, pas disparaitre : %r" % sortie
    )
