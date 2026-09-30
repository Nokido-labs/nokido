"""NR — le rythme MODULE la tolerance, il ne decrete plus la protection.

CE QUI EST CORRIGE (mesure 2026-09-02). `arbitrer_pression` calculait :

    interactif = (r not in ("CONSERVE","SOMMEIL","DEEP","REPOS")
                  or coder_conns != 0 or chains_active > 0)
    if interactif: return protect_coder

`NORMAL` n'etant pas un rythme de repos, la fonction sortait en `protect_coder`
AVANT de regarder quoi que ce soit d'autre. Mesure : rythme NORMAL, conns=0,
chains=0, backlog 150x le seuil -- protege, avec pour raison « l'organe qui SERT
garde sa place » alors qu'il ne servait personne. Le libelle designait le
service ; ce qui protegeait etait le rythme.

`NORMAL` dit « le systeme est eveille ». Il ne dit RIEN sur cet organe. Il
choisit desormais la TOLERANCE a l'inactivite (`grace_s`), pas le verdict.

CE QUI REMPLACE LE VETO : `inutile_s`, duree CONTINUE a zero connexion, tenue
par le keeper. Contrairement a l'age d'un drapeau -- remis a zero a chaque
repose, donc menteur -- elle ne triche pas. C'est aussi le garde qui manquait
au 2026-07-26 : un coder qu'on vient d'allumer est inactif PAR DEFINITION et ne
doit pas etre fauche dans ses premieres secondes.

L'INCERTITUDE EST CONSERVATRICE, UNIFORMEMENT. `coder_conns < 0`,
`demande_active is None`, `inutile_s` illisible : chacun protege. Un trou de
telemetrie ne devient jamais une autorisation d'eteindre -- ce serait rejouer
juillet (73 arrets, 312,94 Go rechargees) sous une autre forme.
"""

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

import forge_resource_manager as rm  # noqa: E402

BASE = dict(coder_up=True, embed_wanted=False, backlog=124659, embedder_up=False,
            coder_ram_gb=5.17, free_gb=2.7)


def _decide(**kw):
    args = dict(BASE)
    args.update(kw)
    return rm.arbitrer_pression(**args)


def _protege(**kw) -> bool:
    return _decide(**kw)["action"] == "protect_coder"


# --------------------------------------------------------------- la matrice

@pytest.mark.parametrize("conns,chains,demande,inutile,protege,pourquoi", [
    (1, 0, False, 3600, True, "des connexions : l'organe sert"),
    (0, 1, False, 3600, True, "des chaines de veille tournent"),
    (0, 0, True, 3600, True, "un bail de demande est ouvert"),
    (0, 0, False, 10, True, "delai de grace : allume trop recemment"),
    (0, 0, False, 1000, False, "reellement inactif au-dela de la grace"),
    (-1, 0, False, 1000, True, "conns INCONNU : jamais evincer sur une non-mesure"),
    (0, 0, None, 1000, True, "demande INCONNUE : un trou n'autorise pas l'arret"),
])
def test_matrice_de_protection(conns, chains, demande, inutile, protege, pourquoi):
    obtenu = _protege(rhythm="NORMAL", coder_conns=conns, chains_active=chains,
                      demande_active=demande, inutile_s=inutile)
    assert obtenu is protege, pourquoi


def test_le_point_de_bascule_est_net():
    g = rm._GRACE_EVEILLE_S
    commun = dict(rhythm="NORMAL", coder_conns=0, chains_active=0, demande_active=False)
    assert _protege(inutile_s=g - 1, **commun) is True
    assert _protege(inutile_s=g, **commun) is False


def test_l_inactivite_inconnue_protege():
    d = _decide(rhythm="NORMAL", coder_conns=0, chains_active=0,
                demande_active=False, inutile_s=None)
    assert d["action"] == "protect_coder"
    assert "INCONNUE" in d["raison"]


# ------------------------------------------- le rythme module, il ne decrete pas

def test_NORMAL_seul_ne_protege_plus():
    """LE defaut corrige : eveille + rien qui travaille = evincable."""
    assert _protege(rhythm="NORMAL", coder_conns=0, chains_active=0,
                    demande_active=False, inutile_s=99999) is False


def test_le_rythme_change_la_TOLERANCE_pas_le_verdict():
    """Meme inactivite : protegee en eveil, evincable en sommeil. C'est cela,
    moduler."""
    commun = dict(coder_conns=0, chains_active=0, demande_active=False, inutile_s=60)
    assert _protege(rhythm="NORMAL", **commun) is True      # grace 300 s
    assert _protege(rhythm="SOMMEIL", **commun) is False     # grace 30 s


def test_la_grace_du_sommeil_est_plus_courte_que_celle_de_l_eveil():
    assert rm._GRACE_PAR_RYTHME["SOMMEIL"] < rm._GRACE_EVEILLE_S
    assert rm._GRACE_PAR_RYTHME["CONSERVE"] < rm._GRACE_EVEILLE_S


def test_un_rythme_inconnu_prend_la_grace_la_plus_LONGUE():
    """Un nom de rythme qu'on ne connait pas ne doit pas raccourcir la
    protection : l'ignorance penche du cote prudent."""
    assert _protege(rhythm="RYTHME_INVENTE", coder_conns=0, chains_active=0,
                    demande_active=False, inutile_s=60) is True


# ------------------------------------------------------- gardes structurels

def test_le_rythme_n_apparait_plus_dans_la_condition_de_protection():
    """GARDE : lecture du CORPS. Remettre le rythme dans le OR ne ferait echouer
    aucun test fonctionnel tant que les autres branches protegent -- il faut
    donc verifier la structure elle-meme."""
    import inspect
    import re

    src = inspect.getsource(rm.arbitrer_pression)
    bloc = src[src.find("protection_active = ("):]
    bloc = bloc[:bloc.find(")")]
    for interdit in ("CONSERVE", "SOMMEIL", "REPOS", "rhythm", "r not in"):
        assert interdit not in bloc, (
            "le rythme est revenu dans la condition de protection : %r" % interdit)
    assert re.search(r"coder_conns\s*!=\s*0", bloc)
    assert "demande_protectrice" in bloc and "assez_inactif" in bloc


def test_l_incertitude_est_conservatrice_de_facon_UNIFORME():
    """Les trois mesures manquantes protegent, et pour la meme raison."""
    commun = dict(rhythm="NORMAL", chains_active=0, inutile_s=1000)
    assert _protege(coder_conns=-1, demande_active=False, **commun) is True
    assert _protege(coder_conns=0, demande_active=None, **commun) is True
    assert _protege(coder_conns=0, demande_active=False, rhythm="NORMAL",
                    chains_active=0, inutile_s=None) is True


def test_la_demande_ne_peut_QUE_proteger():
    """Une demande n'evince jamais : elle ajoute de la protection, point.
    Sans cette monotonie, un emetteur incomplet deviendrait dangereux."""
    commun = dict(rhythm="NORMAL", coder_conns=0, chains_active=0, inutile_s=1000)
    sans = _protege(demande_active=False, **commun)
    avec = _protege(demande_active=True, **commun)
    assert avec is True
    assert sans is False
    assert not (sans and not avec), "la demande a RETIRE de la protection"


def test_le_nom_ne_ment_plus():
    """`interactif` designait une interaction ; ni un bail ni un delai de grace
    n'en sont une. Le nom precedent invitait a re-deduire « NORMAL = interactif
    = protection »."""
    import inspect

    src = inspect.getsource(rm.arbitrer_pression)
    assert "protection_active" in src
    assert "\n    interactif = (" not in src


def test_les_seuils_voisins_n_ont_pas_bouge():
    """Ce changement remplace un proxy par une mesure. Il ne touche NI au seuil
    de backlog, NI a la strategie de consolidation."""
    assert rm._BACKLOG_AFFAME == 5000


# ------------------------------------------------- les mesures rendent l'inconnu

def test_demande_active_rend_None_quand_elle_ne_peut_pas_regarder(monkeypatch):
    import forge_organ_demand as od

    def _casse(*a, **k):
        raise RuntimeError("base injoignable")

    monkeypatch.setattr(od, "demandes_actives", _casse)
    assert rm._demande_active_llama() is None


def test_inutile_s_rend_None_sur_heartbeat_absent(monkeypatch):
    monkeypatch.setattr(rm, "_heartbeat_keeper", dict)
    assert rm._inutile_s_llama() is None


def test_inutile_s_rend_None_sur_heartbeat_PERIME(monkeypatch):
    """Une inactivite d'il y a une heure ne decrit pas le present."""
    import time

    monkeypatch.setattr(rm, "_heartbeat_keeper",
                        lambda: {"inutile_s": 9999, "ts": time.time() - 7200})
    assert rm._inutile_s_llama() is None


def test_inutile_s_lit_un_heartbeat_frais(monkeypatch):
    import time

    monkeypatch.setattr(rm, "_heartbeat_keeper",
                        lambda: {"inutile_s": 153, "ts": time.time()})
    assert rm._inutile_s_llama() == 153.0


def test_les_deux_mesures_lisent_le_MEME_heartbeat(monkeypatch):
    """Deux lectures independantes du meme etat finissent par diverger : le
    coder_conns et l'inactivite doivent venir du meme fichier, lu une fois."""
    import time

    monkeypatch.setattr(rm, "_heartbeat_keeper",
                        lambda: {"active_conns": 3, "inutile_s": 0, "ts": time.time()})
    assert rm._coder_conns() == 3
    assert rm._inutile_s_llama() == 0.0
