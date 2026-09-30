"""NR -- trois axes separes : exposition, authentification, autorisation.

Correction du 2026-09-02, apres le finding M2M #4. L'ancienne classe unique
melangeait `LOCAL` (une propriete de TRANSPORT) avec PUBLIC/AUTH (des
proprietes d'AUTORISATION). Le glissement etait invisible et fatal : proposer
`LOCAL` pour 35 routes PARCE QU'un appelant local avait ete OBSERVE faisait de
la provenance une autorisation par la porte de derriere -- exactement
l'invariant que `decider()` protege du PID, contourne par le nom d'une classe.

    localite  != identite
    identite  != autorisation
    PID       != identite

Le reviewer a nomme les deux vecteurs : le RECYCLAGE de PID (l'OS reattribue le
numero d'un processus mort) et la confiance aveugle en l'origine locale (tout
script tournant sur la machine heriterait des droits sans jamais s'authentifier).

Ces tests couvrent les sept cas du mandat, plus deux gardes structurels qui
empechent l'exposition de revenir dans la decision par un chemin detourne.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_authz_shadow as az  # noqa: E402


# --------------------------------------------------------------------------- #
# GARDES STRUCTURELS -- l'exposition ne peut pas revenir dans la decision
# --------------------------------------------------------------------------- #

def test_decider_ne_consulte_jamais_l_exposition():
    """Plus fort qu'une convention : `decider` ne doit pas appeler
    `exposition_de`. Si ce test tombe, la localite est redevenue un argument
    d'autorisation."""
    import inspect

    corps = inspect.getsource(az.decider)
    sans_doc = corps.split('"""')[-1] if corps.count('"""') >= 2 else corps
    # Retirer AUSSI les commentaires : une premiere version de ce test tombait
    # sur la phrase « `exposition_de` est deliberement NON appelee » et
    # declarait la faute que ce commentaire annonce eviter.
    code = "\n".join(l for l in sans_doc.splitlines()
                     if not l.strip().startswith("#"))
    assert "exposition_de" not in code, (
        "decider consulte l'exposition : la localite redevient une autorisation")


def test_decider_ne_prend_aucun_argument_de_provenance():
    """Invariant PID, re-verifie ici : les deux defauts sont la meme famille."""
    import inspect

    params = set(inspect.signature(az.decider).parameters)
    assert not (params & {"pid", "process", "service", "exposure", "local"})


def test_le_vocabulaire_des_axes_est_disjoint():
    """`LOCAL_ONLY` est une exposition, jamais une authentification."""
    assert "LOCAL_ONLY" in az.EXPOSITIONS
    assert "LOCAL_ONLY" not in az.AUTHENTIFICATIONS
    assert set(az.AUTHENTIFICATIONS) == {"NONE", "REQUIRED", "UNKNOWN"}


# --------------------------------------------------------------------------- #
# LES SEPT CAS DU MANDAT
# --------------------------------------------------------------------------- #

# 2026-09-24 -- CLOTURE du chantier d'authentification : plus AUCUNE route reelle
# n'est « observee mais non tranchee » (INTERNE_OBSERVE est entierement couvert par
# AUTH_REQUISE). Les tests du MODELE ci-dessous gardent leur sens sur une route
# SYNTHETIQUE injectee le temps du test, au lieu de dependre d'une route reelle qui
# a, elle, ete tranchee -- c'etait le chemin normal : observer, puis decider.
_SYNTH = "/zz/route_interne_synthetique_nr"


@pytest.fixture()
def interne_non_tranchee(monkeypatch):
    monkeypatch.setitem(az.INTERNE_OBSERVE, _SYNTH, "route synthetique du NR, jamais servie")
    return _SYNTH


def test_1_processus_local_sans_authentification_ne_donne_pas_allow(interne_non_tranchee):
    """Un script lance localement reste un client NON authentifie.

    Deux routes, deux verdicts, et AUCUN n'est ALLOW : sur une route non
    tranchee c'est UNKNOWN, sur une route tranchee c'est DENY. La localite
    n'ouvre ni l'une ni l'autre.
    """
    assert az.decider(interne_non_tranchee, -1, "")["decision"] == "AUTHZ_UNKNOWN"
    assert az.decider("/api/resource/should_spawn", -1, "")["decision"] == "SHADOW_DENY"
    assert az.decider("/api/services/list", -1, "")["decision"] == "SHADOW_DENY"


def test_2_meme_processus_avec_identite_authentifiee_passe_par_le_videur(monkeypatch):
    """L'identite vient de l'authentification ; le ring vient du videur."""
    monkeypatch.setitem(az.AUTH_REQUISE, "/api/resource/should_spawn", "tranchee")
    refuse = az.decider("/api/resource/should_spawn", ring=-1, agent="")
    permis = az.decider("/api/resource/should_spawn", ring=1,
                        agent="SERVICE_SUPERVISOR", via="capability_token")
    assert refuse["decision"] == "SHADOW_DENY"
    assert permis["decision"] == "SHADOW_ALLOW"


def test_3_pid_connu_et_token_absent_n_autorise_pas(monkeypatch):
    """Le cas exact du superviseur : provenance etablie, identite absente."""
    monkeypatch.setitem(az.AUTH_REQUISE, "/x", "tranchee")
    v = az.decider("/x", ring=-1, agent="")
    assert v["decision"] == "SHADOW_DENY"
    # et la provenance n'apparait meme pas dans le verdict
    assert "pid" not in v and "process" not in v


def test_4_pid_inconnu_et_token_valide_autorise_quand_meme(monkeypatch):
    """L'autorisation ne DEPEND PAS du PID : un appelant dont la provenance est
    illisible mais qui prouve son identite doit passer. Sinon un angle mort de
    `psutil` deviendrait un refus de service."""
    monkeypatch.setitem(az.AUTH_REQUISE, "/x", "tranchee")
    v = az.decider("/x", ring=2, agent="CLAUDE", via="bearer")
    assert v["decision"] == "SHADOW_ALLOW"


def test_5_local_only_n_est_pas_public(interne_non_tranchee):
    """La distinction qui manquait : la frontiere reseau n'est pas la confiance."""
    expo_health, _ = az.exposition_de("/health")
    expo_interne, _ = az.exposition_de(interne_non_tranchee)
    assert expo_health == "PUBLIC"
    assert expo_interne == "LOCAL_ONLY"
    assert expo_health != expo_interne
    # Les deux axes bougent INDEPENDAMMENT : meme exposition LOCAL_ONLY,
    # authentifications differentes selon que la route a ete tranchee ou non.
    assert az.authentification_de("/health")[0] == "NONE"
    assert az.authentification_de(interne_non_tranchee)[0] == "UNKNOWN"
    assert az.exposition_de("/api/resource/should_spawn")[0] == "LOCAL_ONLY"
    assert az.authentification_de("/api/resource/should_spawn")[0] == "REQUIRED"


def test_6_local_only_plus_unknown_reste_unknown(interne_non_tranchee):
    """Les appelants internes OBSERVES restent LOCAL_ONLY en exposition ; tant
    que leur authentification n'est pas tranchee, ils sortent UNKNOWN. Une
    route tranchee depuis (cf. AUTH_REQUISE) est exclue -- c'est le chemin
    normal : observer, puis decider."""
    restants = [r for r in az.INTERNE_OBSERVE if r not in az.AUTH_REQUISE]
    # 2026-09-24 : `restants` REEL est vide -- toutes tranchees. La propriete du
    # modele se verifie sur la route synthetique (fixture), jamais tranchee.
    assert interne_non_tranchee in restants
    for route in restants:
        assert az.exposition_de(route)[0] == "LOCAL_ONLY", route
        assert az.authentification_de(route)[0] == "UNKNOWN", route
        assert az.decider(route, -1, "")["decision"] == "AUTHZ_UNKNOWN", route


def test_7_local_only_plus_auth_exige_une_identite(monkeypatch, interne_non_tranchee):
    """Une route peut etre LOCAL_ONLY *et* exiger une authentification : les
    deux axes se combinent, ils ne se remplacent pas."""
    monkeypatch.setitem(az.AUTH_REQUISE, interne_non_tranchee, "tranchee")
    assert az.exposition_de(interne_non_tranchee)[0] == "LOCAL_ONLY"
    assert az.authentification_de(interne_non_tranchee)[0] == "REQUIRED"
    assert az.decider(interne_non_tranchee, -1, "")["decision"] == "SHADOW_DENY"


# --------------------------------------------------------------------------- #
# NON-REGRESSION du modele
# --------------------------------------------------------------------------- #

def test_aucune_route_ne_produit_plus_la_classe_local():
    """La branche `classe == LOCAL` de l'ancien flux doit etre morte : plus
    aucune entree ne peut y mener."""
    for route in list(az.INTERNE_OBSERVE) + list(az.DECLARE) + ["/inexistante"]:
        assert az.decider(route, -1, "").get("classe") != "LOCAL", route


def test_authentication_none_reste_exceptionnelle_et_motivee():
    """`NONE` est le seul etat qui autorise sans identite. Chaque occurrence
    doit etre rare et porter sa raison -- sinon la surface se rouvre par
    accumulation, sans que personne ne l'ait decide."""
    nones = [r for r, d in az.DECLARE.items() if d["authentication"] == "NONE"]
    # 2026-09-24 : la borne numerique (<= 2) devient l'ENSEMBLE NOMME. Trois routes
    # SANS EFFET ont ete decidees NONE a la cloture (non-mutation prouvee par
    # test_routes_organes_authentifiees_nr). Toute nouvelle exemption exige d'editer
    # cette ligne : c'est la decision explicite que « l'accumulation » contournait.
    # 2026-09-26, decision owner : /api/push (RETIREE, 410) sort de l'ensemble -- une route retiree n'elargit
    # pas la surface publique.
    assert set(nones) == {"/health", "/api/rag/tokenize", "/api/sandbox/runtimes"}, nones
    for r in nones:
        assert len(az.DECLARE[r]["motif"]) > 80, (
            "%s autorise sans identite avec un motif trop court pour etre une "
            "decision" % r)


def test_chaque_declaration_porte_les_deux_axes():
    for route, d in az.DECLARE.items():
        assert d["exposure"] in az.EXPOSITIONS, route
        assert d["authentication"] in az.AUTHENTIFICATIONS, route
        assert d.get("motif", "").strip(), route


def test_la_trace_porte_les_deux_axes_separement(interne_non_tranchee):
    t = az.trace_de(interne_non_tranchee, "GET", -1, "", "anonyme",
                    {"pid": None, "raison": "test"})
    assert t["exposure"] == "LOCAL_ONLY"
    assert t["authentication"] == "UNKNOWN"
    assert t["decision"] == "AUTHZ_UNKNOWN"
    # meme exposition, authentification tranchee -> la trace les distingue
    t2 = az.trace_de("/api/resource/should_spawn", "GET", -1, "", "anonyme",
                     {"pid": None, "raison": "test"})
    assert t2["exposure"] == "LOCAL_ONLY"
    assert t2["authentication"] == "REQUIRED"


# --------------------------------------------------------------------------- #
# INSTRUMENT : ne pas se compter soi-meme, et nommer un appelant periodique
# --------------------------------------------------------------------------- #

def test_la_sonde_d_audit_s_annonce():
    """L'audit envoie `LaForge-Agent-Name: AUDIT_PROBE`. Sans cet en-tete, ses
    propres requetes se comptent comme des appelants anonymes du corps -- c'est
    ce qui a fait relever trois « appels non authentifies sur /mcp » qui etaient
    les sondes elles-memes."""
    import inspect
    import sys as _s
    from pathlib import Path as _P

    _s.path.insert(0, str(_P(__file__).resolve().parents[2] / "tools"))
    import forge_route_authz_audit as audit

    assert "AUDIT_PROBE" in inspect.getsource(audit.prober)


def test_la_sonde_ne_s_authentifie_PAS():
    """Elle doit rester anonyme : son role est de mesurer ce qu'un appelant
    sans identite obtient. Un en-tete de nom n'est pas un credential."""
    import inspect
    import sys as _s
    from pathlib import Path as _P

    _s.path.insert(0, str(_P(__file__).resolve().parents[2] / "tools"))
    import forge_route_authz_audit as audit

    src = inspect.getsource(audit.prober)
    assert "Authorization" not in src
    assert "Bearer" not in src


def test_la_dette_de_cablage_de_la_sonde_est_constatee():
    """`_resolve_ring` rend (-1, 'no_auth') AVANT de lire l'en-tete de nom quand
    il n'y a pas de Bearer -- donc `sonde_interne` vaut False aujourd'hui, quoi
    qu'il arrive. Ce test CONSTATE la dette au lieu de la masquer : le jour ou
    le middleware transmettra l'en-tete brut, il tombera et devra etre mis a
    jour, ce qui est exactement le signal qu'on veut."""
    t = az.trace_de("/mcp", "GET", -1, "no_auth", "header_agent",
                    {"pid": None, "raison": "test"})
    assert t["sonde_interne"] is False, (
        "le marquage des sondes fonctionne desormais : retirer cette dette du "
        "commentaire de trace_de et adapter ce test")


def test_la_chaine_d_ancetres_est_tronquee_explicitement():
    """Un appelant periodique lance par des shells ephemeres n'a pas de parent
    stable ; la chaine remonte plus haut. Une chaine coupee doit se voir."""
    class _P:
        def __init__(self, pid, nom, parent=None):
            self.pid, self._n, self._p = pid, nom, parent
        def name(self): return self._n
        def parent(self): return self._p

    racine = _P(1, "a.exe")
    for i in range(2, 12):
        racine = _P(i, "p%d.exe" % i, racine)

    class _Faux:
        Process = staticmethod(lambda pid: racine)

    ch = az._chaine_ancetres(_Faux, 11, profondeur=3)
    assert len(ch) == 4 and ch[-1] == "...", ch


def test_la_chaine_d_ancetres_dit_l_illisible():
    class _Faux:
        @staticmethod
        def Process(pid):
            raise PermissionError("autre compte")

    assert az._chaine_ancetres(_Faux, 42) == ["illisible"]


def test_aucune_route_tranchee_sans_observation():
    """Une route ne peut pas passer REQUIRED si personne ne l'a vue appelee :
    ce serait promouvoir une supposition en politique. Les trois entrees du
    2026-09-02 reposent chacune sur un comptage (541, 726 et 4 appels)."""
    for route, motif in az.AUTH_REQUISE.items():
        assert "TRANCHEE" in motif and "mesure" in motif.lower(), route


def test_une_route_tranchee_n_est_plus_unknown():
    """Effet attendu de la decision : elle sort de l'indetermine."""
    for route in az.AUTH_REQUISE:
        assert az.authentification_de(route)[0] == "REQUIRED", route
        assert az.decider(route, -1, "")["decision"] == "SHADOW_DENY", route
        assert az.decider(route, 1, "X", "bearer")["decision"] == "SHADOW_ALLOW", route


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
