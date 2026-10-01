# -*- coding: utf-8 -*-
"""NR — forge_docs_relink : on teste l'EFFET, pas l'import.

Un lien mort ne casse aucun test et ne leve aucune erreur : la page s'affiche,
le lecteur clique, il tombe sur une 404. Ces tests verrouillent les quatre
comportements dont depend cette garantie :

1. un lien VERIFIE est reprefixe (l'outil ne reecrit que ce qu'il a pu resoudre) ;
2. un lien introuvable est SIGNALE mais LAISSE INTACT (on ne casse pas plus) ;
3. `verifier` ignore les blocs de code (un verificateur qui crie a faux se fait
   desarmer, et c'est alors le vrai lien mort qu'on ne verra plus) ;
4. `verifier` survit a un dossier HORS depot -- basetemp du runner CI comprise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from forge_docs_relink import reprefixer, verifier  # noqa: E402


def _doc(base: Path, rel: str, texte: str = "x") -> Path:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texte, encoding="utf-8")
    return p


def _base_i18n(tmp_path: Path) -> Path:
    """Reproduit la geometrie reelle : la page vit dans docs/i18n/, deux niveaux
    sous la racine, et `../..` doit donc retomber sur cette racine."""
    b = tmp_path / "docs" / "i18n"
    b.mkdir(parents=True, exist_ok=True)
    return b


def test_lien_resolu_est_reprefixe(tmp_path):
    _doc(tmp_path, "docs/ARCHITECTURE.md")
    texte, faits, manquants = reprefixer(
        "voir [l archi](docs/ARCHITECTURE.md) pour la suite", "../..", _base_i18n(tmp_path)
    )
    assert "](../../docs/ARCHITECTURE.md)" in texte
    assert faits == [("docs/ARCHITECTURE.md", "../../docs/ARCHITECTURE.md")]
    assert manquants == []


def test_ancre_conservee_sur_lien_reprefixe(tmp_path):
    _doc(tmp_path, "docs/ARCHITECTURE.md")
    texte, faits, _ = reprefixer(
        "[a](docs/ARCHITECTURE.md#providers)", "../..", _base_i18n(tmp_path)
    )
    assert "](../../docs/ARCHITECTURE.md#providers)" in texte
    assert len(faits) == 1


def test_cible_introuvable_signalee_mais_texte_intact(tmp_path):
    origine = "[a](docs/ABSENT.md)"
    texte, faits, manquants = reprefixer(origine, "../..", _base_i18n(tmp_path))
    assert texte == origine, "un lien non resolu ne doit PAS etre reecrit"
    assert faits == []
    assert manquants == ["docs/ABSENT.md"]


@pytest.mark.parametrize(
    "cible",
    [
        "https://example.org/x.md",  # absolu
        "/docs/x.md",               # racine
        "#section",                 # ancre pure
        "../../docs/x.md",          # deja prefixe
    ],
)
def test_liens_hors_perimetre_intacts(tmp_path, cible):
    origine = "[a](%s)" % cible
    texte, faits, manquants = reprefixer(origine, "../..", _base_i18n(tmp_path))
    assert texte == origine
    assert faits == [] and manquants == []


def test_verifier_ignore_les_blocs_de_code(tmp_path, capsys):
    _doc(
        tmp_path,
        "page.md",
        "un exemple :\n\n```\n[a](rien/du/tout.md)\n```\n\net `[b](autre/absent.md)` inline\n",
    )
    assert verifier(tmp_path) == 0, "un lien DANS du code n'est pas un lien mort"
    assert "0 MORT" in capsys.readouterr().out


def test_verifier_signale_un_vrai_lien_mort_hors_depot(tmp_path, capsys):
    # tmp_path est HORS du depot : c'est la configuration qui faisait lever
    # ValueError a relative_to(ROOT) et rougir la CI (mesure 2026-08-28).
    _doc(tmp_path, "page.md", "voir [la suite](voisine.md)\n")
    code = verifier(tmp_path)
    sortie = capsys.readouterr().out
    assert code == 1
    assert "MORT" in sortie and "voisine.md" in sortie


def test_les_traductions_du_README_n_ont_AUCUN_lien_relatif_mort(capsys):
    """Le chemin reel, pas une doublure. Mesure 2026-10-01 : 231 liens relatifs
    des 7 traductions (`(LICENSE)`, `(SECURITY.md)`...) etaient ecrits comme depuis
    la racine alors qu'elles vivent dans docs/i18n/ -- 0 mort le 2026-08-30, 231 un
    mois plus tard, sans qu'aucun test ne crie. Le verificateur existait ; il
    n'etait branche sur rien."""
    racine = Path(__file__).resolve().parents[2]
    rc = verifier(racine / "docs" / "i18n")
    sortie = capsys.readouterr().out
    assert rc == 0 and " 0 MORT(S)" in sortie, sortie[-2000:]


def test_verifier_compte_les_liens_vus(tmp_path, capsys):
    _doc(tmp_path, "cible.md")
    _doc(tmp_path, "page.md", "[ok](cible.md) et [ko](perdu.md)\n")
    verifier(tmp_path)
    sortie = capsys.readouterr().out
    # Le denominateur doit etre imprime : sans lui, "0 mort" ne se distingue pas
    # de "je n'ai rien pu regarder".
    assert "2 lien(s) relatif(s) verifie(s), 1 MORT(S)" in sortie
