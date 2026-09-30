"""NR 2026-09-09 — un message adresse a un agent atterrit dans SA boite, quel que
soit l'alias employe.

LE DEFAUT, MESURE DANS LA BASE M2M. `agent_messages` porte trois espaces de noms
pour les memes acteurs :

    agt_claude        read   1583      CLAUDE           unread   12
    agt_antigravity   read     54      ANTIGRAVITY      pending  11
    agt_gemini        read     24      agt_agt_gemini   unread   14

Les tick de session lisent `WHERE to_agent=?` — UNE forme exacte. Tout ce qui est
ecrit sous une autre forme tombe dans une boite que personne ne releve : ~37
messages non lus y dormaient au moment de la mesure, dont 14 pour Gemini et 11 pour
Antigravity en `pending`, statut que `forge_job_notify` designe explicitement comme
invisible aux poll-hooks. Ce n'est donc pas un defaut de MON client : il prive
n'importe quel CLI de ses notifications de fin de job.

CE QU'IL NE FALLAIT PAS FAIRE : ecrire une cinquieme normalisation. Le corps en a
deja quatre, et la mesure sur 1799 fichiers dit laquelle fait autorite --
`forge_postal.canonical` (29 appelants) rend la BOITE de l'acteur et connait les
alias (`AGY`, `GEMINI_RELAY`, `AGY_DAEMON` -> `ANTIGRAVITY`) ; `forge_videur.
mailbox_de` (2 appelants) rend l'ADRESSE `agt_<boite>` en reutilisant le MEME index.
Les deux sont les deux faces d'une meme verite. Il manquait seulement que les
ECRIVAINS de `agent_messages` les appellent.

Zero service externe : la resolution est pure, aucune base reelle n'est ecrite.
"""

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_job_notify as notif  # noqa: E402


def test_le_module_expose_une_resolution_de_boite():
    assert hasattr(notif, "boite_de"), (
        "forge_job_notify n'expose pas boite_de : les destinataires sont donc "
        "inseres BRUTS, et `CLAUDE` n'atterrit pas dans la meme boite que "
        "`agt_claude`")


@pytest.mark.parametrize("alias", ["CLAUDE", "claude", "agt_claude", "AGT_CLAUDE"])
def test_tous_les_alias_de_claude_donnent_une_seule_boite(alias):
    """Le coeur du defaut : 12 messages dormaient sous `CLAUDE`."""
    assert notif.boite_de(alias) == notif.boite_de("agt_claude"), (
        "%r ne resout pas la meme boite que 'agt_claude'" % alias)


def test_le_double_prefixe_est_absorbe():
    """`agt_agt_gemini` : 14 messages non lus dans une boite fantome."""
    assert notif.boite_de("agt_agt_gemini") == notif.boite_de("agt_gemini")
    assert not notif.boite_de("agt_agt_gemini").startswith("agt_agt_")


def test_la_normalisation_ne_FUSIONNE_pas_deux_acteurs():
    """FRONTIERE DU CORRECTIF, et elle a ete posee par une mesure.

    Le registre du videur rend `agt_antigravity` pour `agt_gemini` : il tient les
    deux pour un seul acteur. RULES_SHARED les distingue au contraire -- deux files,
    deux drains -- et la base porte du trafic reel des deux cotes. Router par le
    registre enverrait donc tout le courrier de Gemini chez Antigravity.

    Ce test EXIGE que la normalisation reste mecanique. Le jour ou l'arbitrage
    tranchera que les deux acteurs n'en font qu'un, il faudra le changer SCIEMMENT,
    pas le decouvrir en constatant que Gemini ne recoit plus rien.
    """
    assert notif.boite_de("agt_gemini") == "agt_gemini"
    assert notif.boite_de("GEMINI") == "agt_gemini"
    assert notif.boite_de("agt_antigravity") == "agt_antigravity"
    assert notif.boite_de("gemini") != notif.boite_de("antigravity")


def test_la_boite_est_toujours_prefixee_une_fois():
    """Forme d'ADRESSE, celle que les tick interrogent."""
    for nom in ("CLAUDE", "gemini", "agt_antigravity"):
        b = notif.boite_de(nom)
        assert b.startswith("agt_"), "%r -> %r n'est pas une adresse de boite" % (nom, b)
        assert b == b.lower(), "%r -> %r : l'adresse doit etre en minuscules" % (nom, b)


def test_un_nom_inconnu_n_est_PAS_perdu():
    """Contre-epreuve indispensable.

    `mailbox_de` rend '' pour un nom hors registre. Si `boite_de` propageait cette
    chaine vide, le message serait insere sans destinataire -- perdu plus surement
    encore qu'avec un mauvais prefixe. Un repli DOIT exister, et rester une adresse.
    """
    b = notif.boite_de("UN_AGENT_QUI_N_EXISTE_PAS_2026")
    assert b, "nom inconnu -> boite vide : le message serait insere sans destinataire"
    assert b.startswith("agt_")


def test_une_entree_vide_ne_fabrique_pas_de_boite():
    """Symetrie : ne pas inventer un destinataire quand il n'y en a pas."""
    for vide in ("", None):
        assert notif.boite_de(vide) == "", "%r a produit une boite" % (vide,)
