"""NR -- creer une entite RBAC depuis l'interface, sans pouvoir se l'offrir trop large.

DEMANDE OWNER (2026-09-18) : « il serait bon de pouvoir ajouter via l'interface
un entity_id et pouvoir lui attribuer des reglages ». Il n'existait aucun chemin
de creation : `set_mapping` REFUSE une entite inconnue (« entity inconnue »), et
la page ne servait qu'a modifier la zone de ce qui existait deja.

CE QUE CE NR FIGE, et pourquoi chaque point a sa raison :

1. Une entite neuve apparait dans la liste, avec les reglages demandes.
2. Un doublon est REFUSE. Sans cela, re-soumettre le formulaire ecraserait
   silencieusement les reglages d'une entite existante -- une elevation de
   privilege deguisee en faute de frappe.
3. Un identifiant vide ou fantaisiste est REFUSE. Il sert de cle primaire et se
   retrouve dans les journaux d'audit : un identifiant qui ne se relit pas rend
   l'audit inutilisable.
4. La zone reste COHERENTE avec le ring. `USER_BY_ZONE` impose un compte par
   zone ; laisser choisir librement permettrait de creer une entite `trusted`
   avec le compte d'un bac a sable, c'est-a-dire une autorite sans le compte qui
   la porte.
5. La creation ECRIT UNE LIGNE D'AUDIT. C'est le point qui a motive la demande :
   le journal etait vide, et un journal qui ne consigne pas les creations ne
   documente que la moitie de l'histoire.

Chaque test travaille sur une base TEMPORAIRE : la base reelle est celle du RAG,
et un NR n'ecrit pas dans la base de production pour se prouver.
"""
from __future__ import annotations

import pytest

fm = pytest.importorskip("app.forge_rbac_mapping")


@pytest.fixture
def base(tmp_path):
    """Base neuve : le schema est cree par la premiere connexion."""
    return tmp_path / "rbac_nr.db"


def _creer(base, **kw):
    params = {"entity_id": "agt_essai", "entity_type": "agent", "ring_level": 3,
              "actor": "nr", "reason": "creation de test", "db_path": base}
    params.update(kw)
    return fm.create_mapping(**params)


def test_la_fonction_de_creation_existe():
    """Un NR qui teste un nom absent passerait sur du vide."""
    assert hasattr(fm, "create_mapping"), (
        "`create_mapping` absent : aucun chemin de creation, donc le contrat ne "
        "peut pas etre verifie -- ILLISIBLE, ni vrai ni faux")


def test_une_entite_neuve_apparait_avec_ses_reglages(base):
    _creer(base)
    listee = {e["entity_id"]: e for e in fm.list_mappings(db_path=base)}
    assert "agt_essai" in listee, "l'entite creee ne figure pas dans la liste"
    e = listee["agt_essai"]
    assert e["ring_level"] == 3
    # ring 3 -> sandbox-online, et le compte qui va avec : la zone n'est pas
    # choisie a la main, elle DECOULE du ring.
    assert e["os_account"]["zone"] == fm.ZONE_BY_RING[3]
    assert e["os_account"]["os_user"] == fm.USER_BY_ZONE[fm.ZONE_BY_RING[3]]


def test_un_doublon_est_REFUSE(base):
    _creer(base)
    with pytest.raises(ValueError) as exc:
        _creer(base)
    assert "existe" in str(exc.value).lower(), (
        "le refus doit DIRE que l'entite existe deja : %s" % exc.value)


@pytest.mark.parametrize("mauvais", ["", "   ", "agt essai", "a" * 200, "agt/essai"])
def test_un_identifiant_illisible_est_REFUSE(base, mauvais):
    """Il sert de cle et se retrouve dans l'audit : il doit se relire."""
    with pytest.raises(ValueError):
        _creer(base, entity_id=mauvais)


def test_une_zone_incoherente_avec_le_ring_est_REFUSEE(base):
    """Une autorite sans le compte qui la porte n'est pas une autorite.

    Contre-epreuve du test precedent : ici l'identifiant est bon, c'est la
    combinaison zone/ring qui ne l'est pas.
    """
    with pytest.raises(ValueError):
        _creer(base, entity_id="agt_trop_large", ring_level=4, zone="system")


def test_la_creation_LAISSE_UNE_TRACE(base):
    """Le journal etait vide : c'est ce qui a motive la demande."""
    avant = len(fm.audit_log(limit=50, db_path=base))
    _creer(base, entity_id="agt_trace")
    apres = fm.audit_log(limit=50, db_path=base)
    assert len(apres) == avant + 1, (
        "aucune ligne d'audit pour une creation : le journal ne documenterait "
        "que les modifications, jamais les arrivees")
    ligne = apres[0]
    assert ligne["entity_id"] == "agt_trace"
    assert ligne["actor"] == "nr"
    assert not ligne.get("old"), (
        "une creation n'a PAS d'etat precedent : le champ doit rester vide, "
        "sinon on fabrique un passe a une entite qui vient de naitre")


def test_l_entite_creee_est_ensuite_MODIFIABLE(base):
    """Le chemin complet : creer puis regler. Sans cela, on aurait une creation
    qui produit une entite inerte, et le defaut ne se verrait qu'a l'usage."""
    _creer(base, entity_id="agt_suite", ring_level=3)
    fm.set_mapping("agt_suite", zone="sandbox-offline", actor="nr",
                   reason="resserrage", db_path=base)
    e = {x["entity_id"]: x for x in fm.list_mappings(db_path=base)}["agt_suite"]
    assert e["os_account"]["zone"] == "sandbox-offline"
