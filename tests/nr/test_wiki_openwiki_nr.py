# -*- coding: utf-8 -*-
"""NR — Wiki Nokido selon le modèle OpenWiki (frontmatter OKF et empreinte).

Ce NR vérifie :
1. Que L1 est tenu : Les pages de docs/wiki/ portent toutes un frontmatter OKF valide.
2. Qu'un contrôle négatif mord : une page sans frontmatter lève une erreur.
3. Que L2 est tenu : `forge_card_summaries.json` persiste `docstring_vue`, `empreinte_vue`, et `vu_le`.
"""

import sys
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_wiki_modules as W

WIKI_DIR = ROOT / "docs" / "wiki"
CARDS_FILE = ROOT / "tools" / "forge_card_summaries.json"

def test_L1_controle_negatif_une_page_sans_frontmatter_echoue():
    # Un NR qui mord : vérifier que `valider_frontmatter_okf` détecte bien l'absence
    texte = "# Titre\n\nPas de frontmatter ici."
    issues = W.valider_frontmatter_okf(texte)
    assert any(i["code"] == "missing_frontmatter" for i in issues), "Le validateur n'a pas vu qu'il manquait le frontmatter"

def test_L1_toutes_les_pages_wiki_ont_un_frontmatter_okf_valide():
    # On valide TOUTES les pages de docs/wiki/ (0 missing_frontmatter attendu)
    pages = list(WIKI_DIR.glob("*.md"))
    assert pages, "Aucune page trouvée dans docs/wiki/"
    
    erreurs = []
    missing_count = 0
    for p in pages:
        texte = p.read_text(encoding="utf-8", errors="replace")
        issues = W.valider_frontmatter_okf(texte)
        if issues:
            erreurs.append(f"{p.name} : {issues}")
            if any(i["code"] == "missing_frontmatter" for i in issues):
                missing_count += 1
                
    # Le message DOIT dire sur combien de pages il a porté
    assert not erreurs, f"{len(pages)} pages scannées, {missing_count} missing_frontmatter, {len(erreurs)} pages avec erreurs: {erreurs}"

# Cliquet MESURE le 2026-09-22 : 2424 fiches sur 2426 portent les trois champs.
# Le plancher est posé LEGEREMENT en dessous de la mesure, pas sur une intuition —
# il interdit l'effondrement, pas la variation normale du recensement.
PLANCHER_FICHES_PERSISTEES = 2400

# `docstring_vue` VIDE N'EST PAS UNE DONNÉE MANQUANTE.
# Première version de ce prédicat : `all(fiche.get(c) for c in les_trois)`. Elle a
# accusé 880 fiches. Vérification sur le DISQUE : ces 880 modules n'ont réellement
# AUCUNE docstring (≈ les 878 recensés le matin même). La chaîne vide était la valeur
# JUSTE, et le test fabriquait 880 faux positifs en rangeant une donnée correcte du
# côté du défaut.
#     ABSENCE_DE_DONNÉE  !=  DONNÉE_VIDE_LÉGITIME
# Ce qui ne peut PAS être vide, parce que ce sont des faits mesurés : `empreinte_vue`
# (un sha256 existe toujours si le corps est parsable) et `vu_le` (un instant).
_CHAMPS_NON_VIDES = ("empreinte_vue", "vu_le")
_CHAMPS_REQUIS = ("docstring_vue", "empreinte_vue", "vu_le")


def _fiche_complete(fiche):
    """Une fiche porte l'empreinte du corps SSI les trois CLÉS sont là,
    et si les deux champs qui portent un FAIT MESURÉ ne sont pas vides.

    Prédicat isolé pour qu'il soit testable sur un cas négatif : un test qui ne
    peut pas échouer ne protège rien.
    """
    if not isinstance(fiche, dict):
        return False
    if any(c not in fiche for c in _CHAMPS_REQUIS):
        return False
    return all(fiche.get(c) for c in _CHAMPS_NON_VIDES)


def test_L2_le_predicat_mord_sur_une_fiche_amputee():
    # CONTRÔLE NÉGATIF : sans lui, le test positif serait vrai par impuissance.
    complete = {"docstring_vue": "doc", "empreinte_vue": "abc123", "vu_le": "2026-09-22"}
    assert _fiche_complete(complete)
    for champ in _CHAMPS_REQUIS:
        ampute = dict(complete)
        del ampute[champ]
        assert not _fiche_complete(ampute), f"le prédicat accepte une fiche sans clé {champ}"
    for champ in _CHAMPS_NON_VIDES:
        vide = dict(complete, **{champ: ""})
        assert not _fiche_complete(vide), f"le prédicat accepte un {champ} VIDE"


def test_L2_une_docstring_vide_est_une_donnee_juste_pas_un_trou():
    """CONTRE-ÉPREUVE de la correction ci-dessus : le prédicat ne doit PAS accuser
    un module qui n'a légitimement aucune docstring. 880 faux positifs, mesurés."""
    sans_docstring = {"docstring_vue": "", "empreinte_vue": "abc123", "vu_le": "2026-09-22"}
    assert _fiche_complete(sans_docstring), (
        "le prédicat accuse un module sans docstring : il fabrique un défaut là où la "
        "donnée est juste, et un garde qui crie à faux se fait désarmer"
    )


def test_L2_les_empreintes_de_corps_sont_persistees():
    assert CARDS_FILE.exists(), "forge_card_summaries.json n'existe pas"
    data = json.loads(CARDS_FILE.read_text(encoding="utf-8"))

    total = len(data)
    avec = [k for k, v in data.items() if "empreinte_vue" in (v if isinstance(v, dict) else {})]
    completes = [k for k in avec if _fiche_complete(data[k])]
    partielles = sorted(set(avec) - set(completes))
    sans_docstring = [k for k in completes if data[k].get("docstring_vue") == ""]

    # Une borne dit COMBIEN, pas seulement TROP — et le dénominateur est émis
    # même quand le test passe, sinon « conforme » ne se distingue pas de
    # « je n'ai pas regardé ». `sans_docstring` n'est pas un défaut : c'est le
    # dénominateur du chantier « modules sans docstring », lu gratuitement ici.
    print(
        f"[L2] {total} fiches recensées · {len(avec)} portent empreinte_vue · "
        f"{len(completes)} complètes · {len(partielles)} partielles · "
        f"{len(sans_docstring)} sans docstring (donnée juste, pas un trou) "
        f"(plancher cliquet {PLANCHER_FICHES_PERSISTEES})"
    )

    assert not partielles, (
        f"{len(partielles)} fiche(s) portent empreinte_vue SANS docstring_vue ou vu_le "
        f"— une empreinte sans la docstring qu'elle date ne permet aucun verdict : "
        f"{partielles[:10]}"
    )
    assert len(completes) >= PLANCHER_FICHES_PERSISTEES, (
        f"effondrement de la persistance L2 : {len(completes)} fiches complètes sur "
        f"{total} recensées, plancher {PLANCHER_FICHES_PERSISTEES} (mesuré 2424 le 2026-09-22)"
    )
