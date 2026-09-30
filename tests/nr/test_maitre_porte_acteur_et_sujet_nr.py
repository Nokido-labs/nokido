# -*- coding: utf-8 -*-
"""NR — porter le maitre n'est pas ETRE l'agent qu'on nomme.

MANDAT OWNER du 2026-09-21 : « durcir master token oui ».

CE QUE LA MESURE A MONTRE AVANT DE TOUCHER QUOI QUE CE SOIT
    21 647 appels `via=master_token`, `as_master` = 0, IMPERSONATION = 100 %.
    Le porteur du maitre ne s'annonce JAMAIS comme MASTER : il prend toujours
    le nom d'un autre organe, et `resolve_identity` lui accorde LE RING DE CET
    AGENT.

        agent nomme        appels    ring obtenu
        POST_COMMIT        14 478          4
        WEBHUB              6 418          2
        SUPERVISOR            490          1
        CLAUDE                 36          1

    L'etape 4 ne change que le `via` ; le ring a deja ete calcule a l'etape 3
    depuis l'agent DECLARE. Et l'anti-spoof §5 ne teste que `via == "header"` :
    passer en `master_token` DESARME le plafond au lieu de l'appliquer.

CE QUE CE FICHIER VERROUILLE -- ET CE QU'IL NE FAIT PAS
    Il verrouille l'ATTRIBUTION : `acteur` et `sujet` deviennent structurels
    dans la SOURCE UNIQUE, comme la RFC 8693 distingue `act` du sujet. Le
    lecteur d'un verdict cesse de voir « CLAUDE » sans savoir que le porteur
    du maitre agissait derriere.

    Il NE TOUCHE PAS au ring. Appliquer le plancher ferait chuter 7 112 appels
    sur 21 647 (33 %), dont le superviseur et le webhub : ce serait le
    `m2m_mode=error` arme a 100 % de refus le meme soir. L'ecart est donc
    MESURE et EXPOSE (`ring_si_borne`), jamais applique.

        mesurer avant de durcir, jamais l'inverse
        un gate neuf est NON BLOQUANT le temps de mesurer son bruit

    L'armement est une decision d'AUTORITE, donc owner, et elle a maintenant
    le chiffre qui lui manquait.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _p in (str(_RACINE), str(_RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_videur as V  # noqa: E402


@pytest.fixture(autouse=True)
def _interrupteur_neutre(monkeypatch):
    """Les tests d'OBSERVATION ne dependent pas de l'environnement de la machine :
    l'interrupteur owner LAFORGE_MASTER_BORNE est retire, sauf la ou un test le pose."""
    monkeypatch.delenv("LAFORGE_MASTER_BORNE", raising=False)


_MAITRE = "porteur-maitre-de-test-2026"


def _resoudre(agent, jeton=_MAITRE, local=True):
    """Appelle la SOURCE UNIQUE avec un maitre de test. Aucun secret reel."""
    return V.resolve_identity(agent, jeton, local=local, agent_tokens={},
                              hub_token=_MAITRE)


def test_le_maitre_est_reconnu():
    """Sans ce socle, les tests suivants verifieraient un autre chemin."""
    assert _resoudre("CLAUDE")["via"] == "master_token"


def test_le_porteur_du_maitre_est_nomme_comme_acteur():
    """L'identite de A doit survivre a cote de B (RFC 8693, claim `act`)."""
    ident = _resoudre("CLAUDE")
    assert ident.get("acteur") == "classe:porteur_maitre", (
        "le porteur du maitre n'est pas nomme : le journal montre le SUJET "
        "seul, et 21 647 appels etaient ainsi attribues a un autre organe")


def test_l_agent_nomme_devient_le_sujet():
    ident = _resoudre("SUPERVISOR")
    assert ident.get("sujet") == "SUPERVISOR"
    assert ident["agent"] == "SUPERVISOR", (
        "le champ `agent` reste le sujet : changer sa valeur casserait tous "
        "les consommateurs actuels, et ce NR traite l'ATTRIBUTION")


def test_le_sujet_n_est_pas_declare_prouve():
    """Le nom vient d'un EN-TETE : rien ne l'authentifie.

        AUTHENTIFIE_SOUS_CONDITION != PROUVE_AUTHENTIFIE
    """
    assert _resoudre("CLAUDE").get("sujet_prouve") is False


def test_le_maitre_honnete_n_est_pas_une_impersonation():
    """CONTRE-EPREUVE : s'annoncer MASTER ne fabrique pas un sujet tiers.

    Sans ce test, poser `acteur` partout rendrait la distinction inutile --
    tout deviendrait une delegation, y compris l'appel direct du maitre.
    """
    for nom in ("MASTER", "MASTER_TOKEN"):
        ident = _resoudre(nom)
        assert ident.get("sujet") in (None, nom)
        assert ident.get("acteur") in (None, "classe:porteur_maitre")


def test_un_appel_sans_maitre_ne_porte_aucun_acteur():
    """SYMETRIQUE : ne jamais fabriquer une provenance pour tout le monde.

        ABSENCE_DE_DONNEE != DONNEE_RECONSTRUITE
    """
    ident = V.resolve_identity("CLAUDE", "jeton-quelconque", local=True,
                               agent_tokens={}, hub_token=_MAITRE)
    assert ident["via"] != "master_token"
    assert "acteur" not in ident, "un acteur a ete invente hors delegation"


def test_l_ecart_de_ring_est_MESURE_et_non_applique():
    """Le coeur de la prudence : on expose l'ecart, on ne le sanctionne pas.

    `ring` reste celui d'aujourd'hui ; `ring_si_borne` dit ce qu'il VAUDRAIT
    sous le plancher anti-spoof. C'est ce qui permet de compter l'impact avant
    de decider -- 7 112 appels sur 21 647 a la mesure du 2026-09-21.
    """
    ident = _resoudre("SUPERVISOR")
    assert "ring_si_borne" in ident, (
        "l'ecart n'est pas expose : impossible de chiffrer l'impact d'un "
        "durcissement avant de l'armer")
    assert ident["ring_si_borne"] == V._HEADER_FLOOR_RING
    assert ident["ring"] != ident["ring_si_borne"], (
        "ce cas doit justement montrer un ECART (SUPERVISOR obtient ring 1)")


def test_le_ring_n_a_pas_bouge():
    """NON-REGRESSION EXPLICITE : ce commit ne doit RIEN casser.

    Si ce test rougit, c'est qu'un durcissement d'attribution a emporte une
    decision d'autorite au passage -- exactement ce qu'on s'interdit.
    """
    for nom, attendu in (("SUPERVISOR", 1), ("CLAUDE", 1), ("WEBHUB", 2)):
        r = _resoudre(nom)["ring"]
        assert r == attendu, (
            "%s : ring %s au lieu de %s -- l'autorite a change alors que ce "
            "chantier ne traite que l'attribution" % (nom, r, attendu))


def test_la_delegation_garde_son_propre_acteur():
    """Le maitre ne doit pas ECRASER le mecanisme propre d'a cote.

    `delegated:<X>` pose deja `acteur`/`sujet` avec une borne de ring. Si le
    branchement du maitre passait devant, on remplacerait un dispositif borne
    par un dispositif qui ne l'est pas.
    """
    ident = _resoudre("CLAUDE")
    assert ident["acteur"] == "classe:porteur_maitre"
    assert not ident["via"].startswith("delegated:")


# ── ARMEMENT (2026-09-24) : geste OWNER, interrupteur lu a chaque appel ──────────
def test_arme_la_borne_ramene_le_porteur_du_maitre_au_plancher(monkeypatch):
    monkeypatch.setenv("LAFORGE_MASTER_BORNE", "1")
    ident = _resoudre("SUPERVISOR")
    assert ident["ring"] == V._HEADER_FLOOR_RING, "un nom d'organe declare ouvre encore son ring"
    assert ident.get("borne_appliquee") is True
    assert ident["acteur"] == "classe:porteur_maitre"


def test_armee_la_borne_epargne_le_maitre_qui_se_dit_maitre(monkeypatch):
    monkeypatch.setenv("LAFORGE_MASTER_BORNE", "1")
    assert "borne_appliquee" not in _resoudre("MASTER")


def test_armee_la_borne_ne_touche_pas_un_jeton_propre(monkeypatch):
    monkeypatch.setenv("LAFORGE_MASTER_BORNE", "1")
    ident = V.resolve_identity("SUPERVISOR", "jeton-propre-sup", local=True,
                               agent_tokens={"SUPERVISOR": "jeton-propre-sup"}, hub_token=_MAITRE)
    assert ident["via"] != "master_token" and "borne_appliquee" not in ident
    assert ident["ring"] == 1


def test_toute_autre_valeur_que_1_laisse_l_observation(monkeypatch):
    for v in ("0", "true", "", "oui"):
        monkeypatch.setenv("LAFORGE_MASTER_BORNE", v)
        assert _resoudre("SUPERVISOR")["ring"] == 1, v


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
