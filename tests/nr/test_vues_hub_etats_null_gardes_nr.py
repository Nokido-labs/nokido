# -*- coding: utf-8 -*-
"""NR — aucune vue du hub ne derefence un etat `null` : une exception de rendu EFFACE la vue.

CE QUI A ETE PAYE (2026-09-18). L'owner signalait depuis deux jours « Fédération ne
marche toujours pas ». J'avais accuse, a tort, un probleme de portee de `window.ViewX`
dans le bundle -- mesure faite, c'etait faux, et ma « correction » avait introduit une
vraie regression. La cause reelle tient en un libelle :

    const [nodes, setNodes] = React.useState(null);      // <- null tant que le fetch
    ...                                                  //    n'a pas repondu
    <SectionTitle hint={`${nodes.length} agents gouvernés`}>

`null.length` leve `TypeError` **au tout premier rendu, avant meme la reponse du
serveur**. Et une exception pendant le rendu d'un composant React ne DEGRADE pas la vue :
elle l'EMPECHE. La page etait donc vide quoi que reponde `/api/hub/federation` -- ce qui
explique pourquoi aucun correctif cote serveur ne changeait rien.

Tout le reste de ce composant traitait pourtant correctement les trois etats
(`nodes === null` = lecture en cours, `[]` = registre vide, `err` = illisible). Un seul
site les ignorait. C'est la forme locale d'une regle du depot : un etat INCONNU
s'affiche, il ne se lit pas comme un nombre.

CE QUE CE TEST FAIT. Il lit le fichier SOURCE reel (`hub-views.ref.jsx`), masque les
commentaires **sans deplacer les offsets** -- un instrument ne lit jamais sa propre prose,
piege paye quatre fois dans ce depot, dont une fois ce jour meme -- puis exige qu'aucun
etat initialise a `null` ne soit derefence sans garde en amont.

MORSURE (`test_l_instrument_voit_le_defaut_reel`) : le defaut EXACT qui a ete paye est
reinjecte en memoire, et l'instrument doit le retrouver. Sans cette moitie, un scanner
casse passerait au vert sur un fichier casse -- exactement ce que ce depot appelle un
garde branche sur un signal que personne n'emet.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
VUES = RACINE / "design_handoff_nokido" / "ui_kits" / "hub" / "hub-views.ref.jsx"

# Le defaut tel qu'il a ete paye, et sa forme corrigee : le NR nomme les DEUX, pour que
# la trace reste lisible quand ce fichier sera relu dans six mois.
_DEFAUT_PAYE = '<SectionTitle hint={nodes.length + " agents gouvernés"}>'


def _masquer_commentaires(src: str) -> str:
    """Neutralise `/* ... */` et `//` en gardant la longueur : les offsets restent vrais."""
    out = list(src)
    for m in re.finditer(r"/\*.*?\*/", src, flags=re.S):
        for i in range(m.start(), m.end()):
            if out[i] != "\n":
                out[i] = " "
    for m in re.finditer(r"(?m)^\s*//.*$", src):
        for i in range(m.start(), m.end()):
            out[i] = " "
    return "".join(out)


def _sites_sans_garde(src: str) -> list[str]:
    """Derefencements d'un etat `useState(null)` sans garde dans les 240 caracteres amont."""
    code = _masquer_commentaires(src)
    etats = set(re.findall(
        r"\[\s*(\w+)\s*,\s*set\w+\s*\]\s*=\s*(?:React\.)?useState\(\s*null\s*\)", code))
    trouves = []
    for v in sorted(etats):
        for m in re.finditer(r"\b" + v + r"\.(\w+)", code):
            amont = code[max(0, m.start() - 240):m.start()]
            garde = (re.search(v + r"\s*(===|!==)\s*null", amont)
                     or re.search(v + r"\s*&&", amont)
                     or re.search(r"\(\s*" + v + r"\s*\|\|", amont)
                     or re.search(v + r"\s*\?", amont))
            if not garde:
                ligne = code[:m.start()].count("\n") + 1
                trouves.append("L%d %s.%s" % (ligne, v, m.group(1)))
    return trouves


@pytest.fixture(scope="module")
def source() -> str:
    if not VUES.exists():
        pytest.skip("hub-views.ref.jsx absent de cet arbre")
    return VUES.read_text(encoding="utf-8")


def test_les_etats_null_sont_bien_vus(source):
    """Garde-fou de l'instrument : s'il ne voit aucun etat `null`, il ne prouve rien.

    Mesure du jour : une premiere version de ce scan SUPPRIMAIT les commentaires au lieu
    de les masquer, et n'apercevait plus que 2 des 5 etats -- un scan qui ne regarde pas
    rend « 0 defaut » exactement comme un fichier sain.
    """
    code = _masquer_commentaires(source)
    etats = set(re.findall(
        r"\[\s*(\w+)\s*,\s*set\w+\s*\]\s*=\s*(?:React\.)?useState\(\s*null\s*\)", code))
    assert len(etats) >= 5, "l'instrument ne voit que %s : il regarde mal" % sorted(etats)
    assert "nodes" in etats, "l'etat de Federation n'est plus vu par le scan"


def test_aucune_vue_ne_derefence_un_etat_null(source):
    sites = _sites_sans_garde(source)
    assert sites == [], (
        "un etat `null` est derefence sans garde : la vue ne se montera PAS.\n  " +
        "\n  ".join(sites))


def test_l_instrument_voit_le_defaut_reel(source):
    """MORSURE — le defaut exact paye le 2026-09-18, reinjecte, doit etre retrouve."""
    corrige = ('<SectionTitle hint={nodes === null ? (err ? "registre illisible" '
               ': "lecture…")')
    assert corrige in source, "la forme corrigee a disparu du fichier"
    mute = re.sub(
        r'<SectionTitle hint=\{nodes === null \? \(err \? "registre illisible" : "lecture…"\)\s*'
        r': \(nodes\.length \+ " agents gouvernés"\)\}>',
        _DEFAUT_PAYE, source)
    assert mute != source, "la mutation n'a pas pu etre appliquee : le NR ne mord plus"
    assert any("nodes.length" in s for s in _sites_sans_garde(mute)), \
        "l'instrument est AVEUGLE au defaut qui a coute deux jours"
