# -*- coding: utf-8 -*-
"""NR — deux bornes qui jetaient du contenu legitime dans la veille.

Owner, 2026-09-05 : « beaucoup ont ete mal ingere, limite en caracteres ». Deux
defauts distincts, tous deux mesures avant correction :

1. `_is_reference_list` rejetait la SOURCE ENTIERE sur la seule densite de `[N]`,
   seuil 1,0 pour 1000 caracteres. Sur 38 213 chunks web, **4 533 depassaient ce
   seuil (un sur huit)** -- des corps d'articles scientifiques, qui citent en
   permanence. Apres correction : 334 rejets (0,87 %), et verification faite,
   ce sont de VRAIES bibliographies.

2. `_INGEST_MAX_CHUNKS = 80` ecretait a 160 000 caracteres. Le PDF arxiv
   2401.05566v3 rendait 135 morceaux : **41 % du papier jetes** apres avoir ete
   crawles, extraits et payes. Le p99 des documents web tombait PILE sur 80,
   signature de l'ecretage.

⚠️ CE QUE CE GARDE NE PROUVE PAS. Les temoins bibliographiques sont FABRIQUES :
le corpus n'en contenait aucune que l'ancien garde sache reconnaitre. Un materiau
fabrique ne mesure pas le monde -- ces seuils sont conservateurs par choix, et le
NR verrouille la FORME du critere (structurel, pas densitaire), pas sa calibration
fine.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

wa = pytest.importorskip("forge_watch_agent")

CORPS = ("Nous montrons que la borne inferieure [12] est atteinte sous les hypotheses "
         "de [3] et [7]. Les travaux recents [21, 22] etendent ce resultat au cas non "
         "convexe, tandis que [8] propose une approche duale. La preuve suit celle de "
         "[15], en remplacant l'argument de compacite par un schema de discretisation "
         "emprunte a [19]. Nos experiences reprennent le protocole de [4].\n"
         "La section suivante detaille l'algorithme et sa complexite, en comparant "
         "aux bornes de [12] et [21].") * 2

BIBLIO_1L = "\n".join(
    f"[{i}] A. Author{i}, B. Coauthor. Titre numero {i}. In Proc., pp {i * 10}-{i * 10 + 8}, 2019."
    for i in range(1, 26))

BIBLIO_PDF = "\n".join(
    f"[{i}] A. Author{i}, B. Coauthor.\nTitre du papier numero {i}.\nIn Proceedings, 2019."
    for i in range(1, 26))


def test_un_corps_qui_CITE_n_est_pas_une_bibliographie():
    """Le faux positif paye : 4 533 chunks, un sur huit, tous des articles."""
    assert wa._is_reference_list(CORPS) is False


def test_une_bibliographie_une_ligne_par_reference_est_reconnue():
    assert wa._is_reference_list(BIBLIO_1L) is True


def test_une_bibliographie_de_PDF_multi_lignes_est_reconnue():
    """Dans un PDF une reference tient souvent sur trois lignes : le ratio tombe
    vers 0,33. Un seuil a 0,5 les aurait toutes ratees."""
    assert wa._is_reference_list(BIBLIO_PDF) is True


def test_le_critere_est_STRUCTUREL_et_pas_seulement_densitaire():
    """LA lecon. J'avais annonce un temoin a 160,5 de densite : ARTEFACT DE CALCUL.
    Une vraie bibliographie tient entre 7 et 13, les corps montent a 11,2 au p99 --
    les deux populations se CHEVAUCHENT. Exiger la densite seule, quel que soit le
    seuil, revient a trancher dans le bruit."""
    import re

    dens = 1000.0 * len(re.findall(r"\[\d{1,3}\]", CORPS)) / len(CORPS)
    assert dens >= wa._REFLIST_DENSITY_MAX, (
        "temoin mal choisi : ce corps ne franchit meme pas le seuil de densite, "
        "il ne prouve donc rien sur le role du critere structurel (densite=%.2f)" % dens)
    assert wa._is_reference_list(CORPS) is False, \
        "densite franchie ET pourtant rejete : le critere structurel ne joue pas"


def test_un_texte_court_n_est_jamais_une_bibliographie():
    assert wa._is_reference_list("[1] Un seul titre.") is False


def test_le_cap_de_chunks_laisse_passer_un_gros_papier():
    """135 morceaux mesures sur un vrai PDF ; le cap doit etre trois fois au-dessus,
    sinon on re-ingere ampute -- ce qui serait pire que ne pas rattraper."""
    assert wa._INGEST_MAX_CHUNKS >= 400


def test_le_cap_existe_encore_et_DIT_ce_qu_il_ecarte():
    """« Une borne doit dire COMBIEN, pas seulement TROP » : sans le journal,
    aucun rattrapage n'est possible puisque personne ne sait ce qui manque."""
    src = (ROOT / "app" / "forge_watch_agent.py").read_text(
        encoding="utf-8", errors="replace")
    assert "_INGEST_MAX_CHUNKS" in src
    assert "n'est PAS ingere" in src, "l'ecretage ne se journalise plus"


def test_les_seuils_restent_reglables_sans_toucher_au_code():
    """Un seuil calibre sur du materiau FABRIQUE doit pouvoir bouger le jour ou une
    vraie bibliographie apparait dans le corpus."""
    import os

    for var in ("LAFORGE_VEILLE_REFLIST_MAX", "LAFORGE_VEILLE_REFLIST_RATIO",
                "LAFORGE_VEILLE_MAX_CHUNKS"):
        src = (ROOT / "app" / "forge_watch_agent.py").read_text(
            encoding="utf-8", errors="replace")
        assert var in src, "seuil fige en dur : %s" % var
    assert os.environ is not None
