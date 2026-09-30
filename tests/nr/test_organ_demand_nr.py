"""NR — l'etat d'un organe n'est pas une demande, et le surveillant ne demande pas.

LE DEFAUT (mesure 2026-09-02). `llama.wanted` disait a la fois « quelqu'un a
besoin de cognition » et « le service est encore la ». Il etait repose par
`forge_llm_ondemand._poser_drapeau`, appele depuis `llama_up()`, c'est-a-dire
depuis la fonction qui VERIFIE que llama tourne : 957 emissions, une toutes les
~300 s pour un TTL de 900 s. Le drapeau ne perimait jamais, donc le veto qui
protege llama de l'eviction ne retombait jamais.

Et le meme signal avait produit la panne INVERSE en juillet, quand personne ne
le posait : 73 arrets en 7,6 jours, 312,94 Go rechargees. Un signal qui porte
deux sens produit les deux pannes opposees.

Ces tests verrouillent la separation, PAS une politique : rien ici ne consomme
encore ces signaux, et c'est deliberé -- on mesure la couverture avant de
debrancher le faux emetteur.
"""

import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

import forge_organ_demand as od  # noqa: E402
import forge_signal_coupling as sc  # noqa: E402


@pytest.fixture(autouse=True)
def _base_de_test(tmp_path, monkeypatch):
    """Base isolee : ces tests n'ecrivent jamais dans les signaux du corps."""
    monkeypatch.setattr(sc, "DB", tmp_path / "signaux_test.db")
    yield


# ------------------------------------------------- separation etat / demande

def test_un_organe_READY_peut_n_avoir_AUCUNE_demande():
    """LE cas que `llama.wanted` rendait impossible a voir : vivant et inutile."""
    od.poser_etat("llama", "READY", emetteur="keeper_de_test")
    r = od.resume("llama")
    assert r["etat"]["etat"] == "READY"
    assert r["demande_active"] is False


def test_une_demande_peut_exister_sur_un_organe_ETEINT():
    """L'autre cas qui autorisera plus tard un reveil : demande sans organe."""
    od.poser_etat("llama", "OFF", emetteur="keeper_de_test")
    od.acquerir("llama", issuer="agent", reason="inference")
    r = od.resume("llama")
    assert r["etat"]["etat"] == "OFF"
    assert r["demande_active"] is True


def test_poser_un_etat_ne_cree_aucune_demande():
    for etat in ("STARTING", "READY", "SERVING", "IDLE"):
        od.poser_etat("llama", etat, emetteur="keeper_de_test")
        assert od.resume("llama")["demande_active"] is False, etat


# ----------------------------------------------------------- LE garde

@pytest.mark.parametrize("issuer", [
    "forge_llm_ondemand", "forge_llama_keeper", "forge_service_watchdog",
    "forge_port_reconcile", "forge_llm_ondemand._poser_drapeau",
])
def test_la_couche_qui_CONSTATE_ne_peut_pas_demander(issuer):
    """« Un organe vivant n'est pas un organe demande. »

    Garde STRUCTUREL : la regle vit dans le code, pas dans un commentaire. Une
    consigne ecrite ne survit pas a la prochaine boucle de keeper qui aura
    « juste besoin » de poser la demande.
    """
    with pytest.raises(od.DemandeRefusee):
        od.acquerir("llama", issuer=issuer, reason="il tourne")


def test_le_refus_est_JOURNALISE():
    """Une tentative doit se voir : sinon on ne saura jamais qu'un keeper a
    essaye, et le defaut reviendra sans trace."""
    with pytest.raises(od.DemandeRefusee):
        od.acquerir("llama", issuer="forge_llm_ondemand", reason="il tourne")
    evts = [e["evenement"] for e in od.journal("llama")]
    assert "DEMAND_REFUSED" in evts


def test_un_demandeur_legitime_passe():
    ident = od.acquerir("llama", issuer="forge_llamacpp._server_call",
                        reason="inference")
    assert ident.startswith("dem_")


def test_une_demande_sans_raison_est_refusee():
    with pytest.raises(ValueError):
        od.acquerir("llama", issuer="agent", reason="")


# ------------------------------------------------- cycle de vie du bail

def test_le_bail_expire_et_l_expiration_est_tracee():
    od.acquerir("llama", issuer="agent", reason="inference", duree_s=-1)
    assert od.demandes_actives("llama") == []
    assert "DEMAND_EXPIRED" in [e["evenement"] for e in od.journal("llama")]


def test_liberer_ferme_le_bail_et_est_idempotent():
    ident = od.acquerir("llama", issuer="agent", reason="inference")
    assert od.liberer(ident) is True
    assert od.liberer(ident) is False
    assert od.demandes_actives("llama") == []


def test_renouveler_ne_ressuscite_pas_un_bail_ferme():
    """Un renouvellement n'est pas une acquisition deguisee -- sinon on
    rouvrirait la porte que le garde vient de fermer."""
    ident = od.acquerir("llama", issuer="agent", reason="inference")
    od.liberer(ident)
    assert od.renouveler(ident) is False


def test_le_bail_porte_qui_quoi_et_combien_de_temps():
    """C'est ce qui permettra de mesurer la couverture avant de debrancher
    le faux emetteur : qui demande, pourquoi, pendant combien de temps."""
    od.acquerir("llama", issuer="agent_x", reason="user_inference",
                duree_s=120, priority=90, ref="job-7")
    d = od.demandes_actives("llama")[0]
    assert d["issuer"] == "agent_x" and d["reason"] == "user_inference"
    assert d["priority"] == 90 and d["ref"] == "job-7"
    assert 0 < d["reste_s"] <= 120


# --------------------------------------------------- l'age fait partie du signal

def test_un_etat_perime_devient_UNKNOWN_pas_le_dernier_connu():
    """Presenter un etat d'hier comme actuel serait la meme faute que
    presenter un backlog d'hier comme frais."""
    od.poser_etat("llama", "SERVING", emetteur="keeper_de_test")
    e = od.etat_courant("llama", age_max_s=-1)
    assert e["etat"] == "UNKNOWN"
    assert e["dernier_connu"] == "SERVING"
    assert "perime" in e["raison"]


def test_aucun_etat_pose_vaut_UNKNOWN_pas_OFF():
    """« Je n'ai rien vu » n'est pas « il est eteint »."""
    e = od.etat_courant("organe_jamais_vu")
    assert e["etat"] == "UNKNOWN" and e["age_s"] is None


def test_un_etat_inconnu_est_refuse():
    with pytest.raises(ValueError):
        od.poser_etat("llama", "PEUT_ETRE")


# ------------------------------------------------------- gardes structurels

def test_le_chemin_d_inference_ouvre_et_ferme_un_bail():
    """GARDE : sans emetteur, la coexistence ne mesurerait rien -- exactement
    le motif « garde branche sur un signal que personne n'emet »."""
    import inspect

    import forge_llamacpp as lc

    src = inspect.getsource(lc._server_call)
    assert "forge_organ_demand" in src, "le passage oblige n'emet aucune demande"
    assert "acquerir" in src and "liberer" in src
    assert "finally" in src, "un bail non libere sur erreur fausserait la duree"


def test_le_keeper_pose_un_etat_et_ne_demande_pas():
    """Verifie un APPEL, pas une chaine.

    Premiere version de ce test : `assert "acquerir(" not in src`. Elle a
    echoue sur le COMMENTAIRE du keeper, qui explique justement que
    `acquerir()` lui est interdit. Meme faute que celle payee le matin meme sur
    les scripts de patch -- un garde doit tester une PROPRIETE, jamais une
    forme textuelle, sinon il accuse a faux et finit desarme.
    """
    import ast

    src = (RACINE / "tools" / "forge_llama_keeper.py").read_text(
        encoding="utf-8", errors="replace")
    assert "poser_etat" in src, "le keeper n'emet aucun etat"
    appels = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            f = n.func
            nom = getattr(f, "id", None) or getattr(f, "attr", None)
            if nom:
                appels.add(nom)
    assert "acquerir" not in appels, "le keeper APPELLE acquerir()"
    assert "poser_etat" in appels or "_poser_etat" in appels, (
        "le keeper n'appelle pas poser_etat : l'etat ne serait jamais emis")


def test_la_demande_est_entree_dans_la_decision_et_SEULEMENT_pour_proteger():
    """FIN DE LA COEXISTENCE STRICTE, actee le 2026-09-02 (point 3).

    La version precedente de ce test exigeait que `forge_resource_manager` ne
    cite PAS ce module, et disait : « si ce test tombe, c'est qu'on est passe a
    l'etape suivante sans le dire ». Il est tombe, et on le dit : le regulateur
    consomme desormais la demande.

    Ce qui remplace la garantie precedente est plus fort qu'une abstention : la
    demande est MONOTONE. Elle ne peut qu'ajouter de la protection, jamais en
    retirer, donc un emetteur incomplet ne peut pas provoquer d'eviction -- il
    peut seulement en empecher une. C'est ce qui rend l'entree dans la decision
    sure AVANT que la couverture de l'emetteur soit demontree.
    """
    import forge_resource_manager as rm

    src = (RACINE / "app" / "forge_resource_manager.py").read_text(
        encoding="utf-8", errors="replace")
    assert "forge_organ_demand" in src, "le regulateur ne lit plus la demande"

    commun = dict(rhythm="NORMAL", coder_up=True, coder_conns=0, chains_active=0,
                  embed_wanted=True, backlog=100000, embedder_up=False,
                  coder_ram_gb=4.4, free_gb=2.0, inutile_s=3600.0)
    sans = rm.arbitrer_pression(demande_active=False, **commun)
    avec = rm.arbitrer_pression(demande_active=True, **commun)
    inconnu = rm.arbitrer_pression(demande_active=None, **commun)
    assert avec["action"] == "protect_coder", "une demande doit proteger"
    assert inconnu["action"] == "protect_coder", "l'inconnu doit proteger"
    assert sans["action"] != "protect_coder", (
        "sans demande, la protection doit pouvoir retomber -- sinon le signal "
        "ne sert a rien")


def test_l_inconnu_de_la_demande_n_est_jamais_lu_comme_une_absence():
    """`demandes_actives` injoignable -> None, surtout pas False : c'est la
    difference entre « personne ne demande » et « je n'ai pas pu regarder »."""
    import forge_resource_manager as rm
    import forge_organ_demand as od_mod

    def _casse(*a, **k):
        raise RuntimeError("base injoignable")

    reel = od_mod.demandes_actives
    od_mod.demandes_actives = _casse
    try:
        assert rm._demande_active_llama() is None
    finally:
        od_mod.demandes_actives = reel
