"""NR -- la route du tray se DECOUVRE depuis le corps distribue, pas depuis la memoire d'un agent (owner 21/10).

Owner, 21/10 : « toutes les decisions qui font appel a la memoire de nos echanges doivent etre notifiees en base, sinon
les versions distribuables ne vont jamais trouver le fonctionnement, par exemple les commandes pour enlever les
commandes du tray ». Mesure du 21/10 : `commande-deposer`, `commandes-en-attente` et `commande-faite` sont CODEES
(app/forge_ordres_bureau.py) mais INTROUVABLES : la description de l'outil hub ne les cite pas
(app/forge_mcp_registry.py), le refus « ordre inconnu ... (connus : ...) » non plus, et aucune skill. Seule ma memoire
de session (~/.claude, hors depot) disait la forme -- rien de cela n'atteint une installation neuve.

Contrats :
  1. le refus d'un ordre inconnu liste aussi les trois ordres de commande ;
  2. la description de l'outil hub (demander_ordre) les nomme ;
  3. la skill distribuee forge-hub decrit le cycle : deposer -> l'owner lance -> commande-faite (avec l'extrait).
"""
import asyncio
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

COMMANDES = ("commande-deposer", "commandes-en-attente", "commande-faite")


def test_le_refus_liste_les_ordres_de_commande():
    import forge_ordres_bureau as O
    r = asyncio.run(O.demander_ordre("TEST", "ordre-qui-n-existe-pas"))
    assert r["etat"] == O.REFUSE
    for c in COMMANDES:
        assert c in r["raison"], (c, r["raison"])


def test_la_description_de_l_outil_hub_les_nomme():
    src = (RACINE / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8", errors="replace")
    # 31/10 : depuis 1d8259fbf la liste porte une parenthese imbriquee (« restart-hub (hub SEUL, ...) ») -- l'ancien
    # motif [^)]* s'arretait dessus. On lit la description de demander_ordre sur une fenetre bornee.
    i = src.find("demander_ordre : ordre=<nom>")
    assert i >= 0, "description de demander_ordre introuvable"
    fenetre = src[i:i + 900]
    for c in COMMANDES:
        assert c in fenetre, (c, fenetre)


def test_la_skill_forge_hub_decrit_le_cycle_du_tray():
    t = (RACINE / "docs" / "skills" / "forge-hub" / "SKILL.md").read_text(encoding="utf-8")
    for c in COMMANDES:
        assert c in t, c
