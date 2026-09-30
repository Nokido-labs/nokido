"""NR — cliquet de couverture : aucun module NOUVEAU sans test.

Rappel owner du 2026-08-14 : « a un moment, des tests NR etaient faits a chaque
ajout ». La pratique s'est perdue — 73 modules testes sur 1127, soit 6,5 %, et
les sept outils ajoutes ce jour-la n'en avaient aucun.

Ce test ne tente pas de rattraper la dette : exiger 1054 tests d'un coup
laisserait un garde rouge en permanence, donc un garde que plus personne ne
lit. Il pose un CLIQUET — l'existant est gele dans `_socle_modules.json`, et
tout module apparu depuis doit etre couvert.

« Couvert » veut dire : cite par un test du repertoire. C'est volontairement
peu exigeant — la barre est qu'un test EXISTE et nomme le module, pas qu'il
soit exhaustif. Un module qu'aucun test ne nomme n'a, lui, aucune chance
d'echouer le jour ou il regresse.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : glob tests/nr + lecture
#   (l.38)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
NR = Path(__file__).resolve().parent
SOCLE = NR / "_socle_modules.json"


def _modules_actuels() -> set[str]:
    return {p.stem for zone in ("app", "tools")
            for p in (ROOT / zone).glob("*.py") if p.stem.startswith("forge_")}


def _modules_cites() -> set[str]:
    cites: set[str] = set()
    for t in NR.glob("*.py"):
        if t.name == Path(__file__).name:
            continue          # ne pas se citer soi-meme comme preuve
        cites |= set(re.findall(r"\bforge_\w+",
                                t.read_text(encoding="utf-8", errors="replace")))
    return cites


def test_socle_present():
    """Sans photo de reference, le cliquet ne cliquette pas."""
    assert SOCLE.exists(), (
        "socle absent — poser la photo une fois : "
        "run trusted_script tools/forge_nr_socle.py"
    )


def test_aucun_module_nouveau_sans_test():
    if not SOCLE.exists():
        pytest.skip("socle absent (voir test_socle_present)")
    socle = set(json.loads(SOCLE.read_text(encoding="utf-8"))["modules"])
    nouveaux = _modules_actuels() - socle
    orphelins = sorted(nouveaux - _modules_cites())
    assert not orphelins, (
        f"{len(orphelins)} module(s) ajoute(s) apres le cliquet sans aucun test NR :\n"
        + "\n".join(f"  - {m}" for m in orphelins)
        + "\n\nEcrire un test qui verifie son EFFET (pas son import) dans tests/nr/."
    )


def test_le_cliquet_sait_mordre():
    """Un garde qui ne peut pas echouer ne garde rien.

    On simule un module absent du socle et jamais cite : la logique doit le
    designer. Sans cette contre-epreuve, un `_modules_cites()` qui renverrait
    tout par accident rendrait le test vert a jamais.
    """
    socle = {"forge_ancien"}
    actuels = {"forge_ancien", "forge_tout_neuf"}
    cites = {"forge_ancien"}
    assert sorted(actuels - socle - cites) == ["forge_tout_neuf"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
