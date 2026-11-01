"""NR -- les traductions du README portent la RAM et le disque MESURES de la page anglaise.

Owner 24/10 : « la page anglaise semble a jour mais pas ses traductions, par exemple la RAM a prevoir a
l'installation ». Mesure : README.md (17016c93e, 19/10) = hote de 24 GB recommande, ~12 GB prives, ~50 GB de disque
dont ~47 GB de RAG ; les 7 traductions (15-16/10) disaient encore 8 GB de RAM / 2 GB de disque et « 16+ GB »
recommandes. Les nombres de reference sont LUS dans README.md : la garde suit l'anglais au lieu de le recopier.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
I18N = sorted((ROOT / "docs" / "i18n").glob("README.*.md"))


def _nombres(ligne: str) -> set:
    return set(re.findall(r"\d+(?:[.,]\d+)?", ligne))


def _reference() -> set:
    en = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    ram = next(l for l in en if l.startswith("| **RAM"))
    disque = next(l for l in en if l.startswith("| **Disk"))
    tete = re.search(r"\*\*RAM[^*]*?(\d+)\s*GB", ram).group(1)
    prive = re.search(r"~(\d+)\s*GB of private", ram).group(1)
    libre = re.search(r"~(\d+)\s*GB free", disque).group(1)
    rag = re.search(r"~(\d+)\s*GB\*\*", disque).group(1)
    return {tete, prive, libre, rag}


def _prerequis(texte: str) -> str:
    lignes = texte.splitlines()
    i = next(k for k, l in enumerate(lignes) if "Python 3.12+" in l)
    j = next((k for k in range(i, len(lignes)) if lignes[k].strip() == "---"), len(lignes))
    return "\n".join(lignes[i:j])


def test_il_y_a_des_traductions():
    assert len(I18N) >= 7, I18N


@pytest.mark.parametrize("chemin", I18N, ids=lambda p: p.name)
def test_ram_et_disque_alignes_sur_l_anglais(chemin):
    bloc = _prerequis(chemin.read_text(encoding="utf-8"))
    manquants = _reference() - _nombres(bloc)
    assert not manquants, "%s : valeurs de l'anglais absentes du bloc prerequis : %s" % (chemin.name, manquants)
    assert not re.search(r"\*\*8\s?(GB|Go)\b", bloc), "%s : ancienne RAM minimale (8 GB) encore citee" % chemin.name
    assert not re.search(r"16\+\s?(GB|Go)", bloc), "%s : ancien « 16+ GB » recommande encore cite" % chemin.name
