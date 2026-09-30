"""NR — le registre d'instruction gouverne `open` ET `done?`, jamais `gele`.

Mesure du 2026-09-18. Un tri semantique de 26 lignes `done?` a ete mene par un
agent local ; 23 categories ont ete ecrites dans `docs/roadmap_instruits.json`.
Resultat : **aucun compteur n'a bouge**. Les entrees etaient sur le disque (94
lues par le module), les clefs recalculaient a l'identique — et elles restaient
INERTES, parce que la consultation du registre etait gardee par
`verdict == "open"` seule, et qu'un item `done?` n'atteignait jamais cette ligne.

C'est « un mecanisme present dont l'effet n'existe pas » : le registre se
relisait comme une decision appliquee alors qu'il ne gouvernait qu'un seau sur
trois. Apres correction : `done_to_close` 26 -> 3, `instruit` 71 -> 94, et les 3
restants sont exactement ceux que le tri avait laisses ouverts faute d'appelant.

`gele` reste HORS portee, et c'est un choix : un gel porte `motif_gel`, cite
depuis le document lui-meme. On ne remplace pas une preuve par une lettre.
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

import tools.forge_roadmap_keeper as K  # noqa: E402


def _portee():
    """La condition de portee, relue dans la SOURCE du module.

    On lit le code plutot que de rejouer un scan complet : le test doit tenir en
    millisecondes et ne pas dependre du contenu courant du depot.
    """
    src = (RACINE / "tools" / "forge_roadmap_keeper.py").read_text(encoding="utf-8")
    i = src.index("cat = _instruits().get(")
    return src[i : i + 260]


def test_le_registre_gouverne_open_ET_done():
    p = _portee()
    assert '"open"' in p and '"done?"' in p, (
        "le registre ne couvre pas les deux seaux — des decisions de tri resteraient "
        "inertes, comme les 23 du 2026-09-18 :\n" + p
    )


def test_morsure_la_garde_restreinte_a_open_seule_est_refusee():
    """CONTROLE NEGATIF — la forme exacte qui a rendu 23 decisions inertes."""
    p = _portee()
    assert 'verdict == "open"' not in p, (
        "la garde est revenue a `verdict == \"open\"` seule : c'est la regression "
        "mesuree le 2026-09-18"
    )


def test_gele_reste_hors_portee():
    """Un gel porte son motif cite depuis le document : plus informatif qu'une lettre."""
    p = _portee()
    assert '"gele"' not in p, (
        "le registre absorbe les gels : on remplacerait une preuve documentee "
        "(`motif_gel`) par une etiquette de categorie\n" + p
    )


def test_le_registre_ne_porte_jamais_de_categorie_A():
    """Doctrine ecrite dans le registre lui-meme : une intention REELLE reste ouverte."""
    import json

    d = json.loads((RACINE / "docs" / "roadmap_instruits.json").read_text(encoding="utf-8"))
    fautifs = [k for k, v in d["entrees"].items() if str(v).upper() == "A"]
    assert not fautifs, (
        "des intentions reelles ont ete classees instruites, ce que le registre "
        "interdit explicitement : " + ", ".join(fautifs[:5])
    )


def test_les_categories_sont_dans_le_vocabulaire_declare():
    import json

    d = json.loads((RACINE / "docs" / "roadmap_instruits.json").read_text(encoding="utf-8"))
    hors = sorted({v for v in d["entrees"].values() if v not in ("B", "C", "D")})
    assert not hors, f"categories hors vocabulaire B/C/D : {hors}"


def test_la_clef_survit_a_un_deplacement_de_ligne():
    """La clef porte une empreinte du TEXTE, pas un numero de ligne : une ligne
    qui se DEPLACE reste instruite, une ligne REECRITE redevient ouverte."""
    a = K._clef_instruction("docs/x.md", "  une intention  ")
    b = K._clef_instruction("docs/x.md", "une intention")
    c = K._clef_instruction("docs/x.md", "une intention modifiee")
    assert a == b, "l'espacement ne doit pas changer la clef"
    assert a != c, "un texte reecrit doit redevenir ouvert"
