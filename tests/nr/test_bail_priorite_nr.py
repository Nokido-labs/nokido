# -*- coding: utf-8 -*-
"""NR -- bail de priorite : la tache prioritaire prend le dessus, et rend ce qu'elle a pris (owner 2026-10-06).

Owner : « les taches prioritaires doivent prendre le dessus tout en gardant a l'esprit qu'une fois finies
elles ne doivent pas empecher le redemarrage de ce qui a ete interrompu a tort ; les intentions doivent
etre conservees avec une notion de travail long / travail court ». Mesure du 2026-10-04 : la CI GitHub de
0.20.8 tuee deux fois par des timeouts d'E/S disque tant que NokidoDeportEmbed lisait ~76 Mo/s.

Contrats verrouilles (superviseur, couts, TOML et capacites remplaces par des doublures -- jamais un vrai
sommeil, jamais le vrai sandbox) :
  1. OBSERVATION par defaut : le bail inscrit qui AURAIT cede, n'endort rien ;
  2. arme : seuls cedent les non-essentiels, sans neverSleep, non critiques, vivants et COUTEUX ; chaque
     interrompu garde son intention, son objectif et son travail (long / court / INCONNU, jamais « court »
     par defaut) ; le demandeur ne nomme jamais qui cede ;
  3. liberation : reveille exactement ce qui a ete endormi, sauf ce qu'un autre bail actif tient, et
     VERIFIE la vie (accepte != atteint) ;
  4. une tache morte ne garde pas le corps endormi : bail court echu, bail long non renouvele -> libere ;
  5. le reveil RAM ne rend pas un service tenu par un bail ;
  6. decision de la route : 400 sur entree invalide, 403 au-dela du ring 3, 403 sur le bail d'un autre,
     503 ILLISIBLE quand la selection ne peut pas se faire -- jamais « rien a endormir ».
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402
from nokido_agent.app import forge_service_capabilities as caps  # noqa: E402

pytestmark = pytest.mark.timeout(120)

TOML = {
    "NokidoDeportEmbed": {"name": "NokidoDeportEmbed", "essential": False, "intention": "deport:embeddings",
                          "objectif": "hb<5400 | cpu>0.05"},
    "NokidoRSSWatcher": {"name": "NokidoRSSWatcher", "essential": False, "intention": "veille:rss"},
    "NokidoMCP": {"name": "NokidoMCP", "essential": True, "neverSleep": True},
    "NokidoVeille": {"name": "NokidoVeille", "essential": False, "neverSleep": True},
    "NokidoCritique": {"name": "NokidoCritique", "essential": False},
    "NokidoSobre": {"name": "NokidoSobre", "essential": False},
    "NokidoInconnu": {"name": "NokidoInconnu", "essential": False},
}
COUTS = {"NokidoDeportEmbed": (76.0, 4.0), "NokidoRSSWatcher": (0.1, 25.0), "NokidoSobre": (0.2, 1.0),
         "NokidoInconnu": (9.0, 0.0), "NokidoCritique": (50.0, 50.0), "NokidoMCP": (30.0, 60.0),
         "NokidoVeille": (40.0, 0.0)}


@pytest.fixture
def corps(tmp_path, monkeypatch):
    """Un corps factice : registre, sommeils et reveils enregistres, jamais executes."""
    etat = {n: {"pid": 1000 + i} for i, n in enumerate(TOML)}
    endormis, reveils, journal = [], [], []
    monkeypatch.setattr(rm, "_BAUX_DIR", tmp_path / "baux")
    monkeypatch.setattr(rm, "_BAIL_SWITCH", tmp_path / "bail_priorite.switch")
    monkeypatch.delenv("LAFORGE_BAIL_PRIORITE", raising=False)
    monkeypatch.setattr(rm, "_services_du_toml", lambda: dict(TOML))
    monkeypatch.setattr(rm, "_statut_superviseur", lambda: etat)
    monkeypatch.setattr(rm, "_cout_des_pids", lambda pids: {s: COUTS[s] for s in pids})
    monkeypatch.setattr(caps, "is_critical", lambda s: s == "NokidoCritique")

    def _dormir(s):
        endormis.append(s)
        etat[s] = {}
        return True, "ACCEPTE"

    def _reveiller(s):
        reveils.append(s)
        etat[s] = {"pid": 9999}
        return True
    monkeypatch.setattr(rm, "_sleep_service_verdict", _dormir)
    monkeypatch.setattr(rm, "_wake_service", _reveiller)
    monkeypatch.setattr(rm, "_service_est_vivant", lambda s: bool((etat.get(s) or {}).get("pid")))
    monkeypatch.setattr(rm, "_audit_lifecycle", lambda *a, **k: journal.append((a, k)))
    return {"etat": etat, "endormis": endormis, "reveils": reveils, "journal": journal, "dir": tmp_path}


def _armer(c):
    (c["dir"] / "bail_priorite.switch").write_text("arme", encoding="utf-8")


# ── 1. observation par defaut ─────────────────────────────────────────────────────────────────────
def test_par_defaut_le_bail_observe_et_n_endort_rien(corps):
    b = rm.acquerir_bail("CI_REF", "CI de reference", "court", 3600)
    assert b["mode"] == "OBSERVATION" and b["etat"] == "ACTIF" and corps["endormis"] == []
    assert {s["service"] for s in b["interrompus"]} == {"NokidoDeportEmbed", "NokidoRSSWatcher", "NokidoInconnu"}
    assert all(s["endormi"] is False and "aurait cede" in s["motif_sommeil"] for s in b["interrompus"])


# ── 2. arme : qui cede, et ce qui est inscrit ─────────────────────────────────────────────────────
def test_arme_seuls_cedent_les_non_essentiels_couteux_non_critiques(corps):
    _armer(corps)
    b = rm.acquerir_bail("CI_REF", "CI de reference", "court", 3600)
    assert b["mode"] == "ARME"
    assert set(corps["endormis"]) == {"NokidoDeportEmbed", "NokidoRSSWatcher", "NokidoInconnu"}
    # essentiel, neverSleep, critique, sobre : aucun ne cede
    assert not {"NokidoMCP", "NokidoVeille", "NokidoCritique", "NokidoSobre"} & set(corps["endormis"])


def test_chaque_interrompu_garde_son_intention_et_son_travail(corps):
    _armer(corps)
    b = rm.acquerir_bail("CI_REF", "CI", "court", 3600)
    par = {s["service"]: s for s in b["interrompus"]}
    assert par["NokidoDeportEmbed"]["intention"] == "deport:embeddings"
    assert par["NokidoDeportEmbed"]["objectif"] == "hb<5400 | cpu>0.05"
    assert par["NokidoDeportEmbed"]["travail"] == "long"
    assert par["NokidoRSSWatcher"]["travail"] == "court"
    assert par["NokidoInconnu"]["travail"] == "INCONNU", "un service non classe n'est JAMAIS « court » par defaut"


def test_le_demandeur_ne_nomme_jamais_qui_cede(corps):
    code, corps_rep, _ = rm._decider_bail("CI_REF", 2, {"action": "acquerir", "motif": "x",
                                                        "services": ["NokidoMCP"]})
    assert code == 400 and "hub choisit" in corps_rep["detail"] and corps["endormis"] == []


# ── 3. liberation ─────────────────────────────────────────────────────────────────────────────────
def test_la_liberation_rend_exactement_ce_qui_a_ete_pris_et_verifie_la_vie(corps):
    _armer(corps)
    b = rm.acquerir_bail("CI_REF", "CI", "court", 3600)
    code, rep = rm.liberer_bail(b["id"], principal="CI_REF")
    assert code == 200 and sorted(corps["reveils"]) == sorted(corps["endormis"])
    assert all(s["reprise"] == "VIVANT" for s in rep["bail"]["interrompus"] if s["endormi"])
    assert rep["bail"]["etat"] == "LIBERE"


def test_un_service_tenu_par_un_autre_bail_n_est_pas_rendu(corps):
    _armer(corps)
    b1 = rm.acquerir_bail("CI_A", "CI A", "court", 3600)
    # Le second bail trouve DeportEmbed deja endormi (plus de pid) : on le lui fait tenir a la main.
    b2 = rm.acquerir_bail("CI_B", "CI B", "court", 3600)
    b2["interrompus"].append({"service": "NokidoDeportEmbed", "endormi": True})
    rm._ecrire_bail(b2)
    rm.liberer_bail(b1["id"], principal="CI_A")
    assert "NokidoDeportEmbed" not in corps["reveils"]
    rep = next(s for s in rm._lire_baux() if s["id"] == b1["id"])
    assert next(s for s in rep["interrompus"] if s["service"] == "NokidoDeportEmbed")["reprise"] \
        == "TENU_PAR_UN_AUTRE_BAIL"


def test_on_ne_libere_pas_le_bail_d_un_autre(corps):
    b = rm.acquerir_bail("CI_A", "CI A", "court", 3600)
    code, _, _ = rm._decider_bail("INTRUS", 2, {"action": "liberer", "id": b["id"]})
    assert code == 403


# ── 4. une tache morte ne garde pas le corps endormi ──────────────────────────────────────────────
def test_un_bail_court_echu_est_libere(corps):
    _armer(corps)
    b = rm.acquerir_bail("CI_REF", "CI", "court", 60)
    b["cree_le"] -= 120
    rm._ecrire_bail(b)
    assert rm.expirer_baux() == [b["id"]]
    assert sorted(corps["reveils"]) == sorted(corps["endormis"])
    assert next(x for x in rm._lire_baux() if x["id"] == b["id"])["etat"] == "EXPIRE"


def test_un_bail_long_non_renouvele_expire_et_renouvele_survit(corps):
    _armer(corps)
    b = rm.acquerir_bail("LONG", "travail long", "long", 4 * 3600)
    b["renouvele_le"] -= rm._BAIL_LONG_SILENCE_MAX_S + 10
    rm._ecrire_bail(b)
    assert rm.expirer_baux() == [b["id"]], "un bail long muet au-dela de 15 min doit expirer"
    b2 = rm.acquerir_bail("LONG", "travail long", "long", 4 * 3600)
    assert rm.renouveler_bail("LONG", b2["id"])[0] == 200 and rm.expirer_baux() == []


# ── 5. le reveil RAM respecte le bail ─────────────────────────────────────────────────────────────
def test_le_reveil_ram_ne_rend_pas_un_service_tenu(corps, monkeypatch):
    _armer(corps)
    rm.acquerir_bail("CI_REF", "CI", "court", 3600)
    reveilles = []

    class _Rep:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _ouvrir(req, timeout=None):
        reveilles.append(req.full_url.rsplit("/", 1)[-1])
        return _Rep()
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _ouvrir)
    monkeypatch.setattr(rm, "_supervisor_auth_headers", lambda: {})   # jamais le vrai coffre dans un NR
    monkeypatch.setattr(rm, "_SUPERVISOR_WAKE_ON_RECOVERY", ["NokidoRSSWatcher", "NokidoGraph"])
    rm._supervisor_wake_non_essential()
    assert "NokidoRSSWatcher" not in reveilles and "NokidoGraph" in reveilles


# ── 6. decision de la route ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("demande", [None, {}, {"action": "voler"},
                                     {"action": "acquerir", "classe": "eternel"},
                                     {"action": "acquerir", "classe": "court", "ttl_s": 7200},
                                     {"action": "acquerir", "classe": "court", "ttl_s": "NaN"},
                                     {"action": "acquerir", "classe": "long", "ttl_s": 0}])
def test_une_demande_invalide_est_refusee_400(corps, demande):
    assert rm._decider_bail("CI_REF", 2, demande)[0] == 400
    assert corps["endormis"] == []


def test_au_dela_du_ring_3_le_bail_est_refuse_sans_action(corps):
    _armer(corps)
    code, _, entetes = rm._decider_bail("SERVICE", 4, {"action": "acquerir", "motif": "x"})
    assert code == 403 and "insufficient_scope" in entetes["WWW-Authenticate"] and corps["endormis"] == []


def test_en_observation_un_job_sans_ring_peut_mesurer_sans_rien_endormir(corps):
    """Mesure du 2026-10-06 : la CI de reference, lancee en job (identite sans nom, ring 4), recevait
    403 et ne pouvait meme pas OBSERVER. En observation le bail n'endort rien : il est ouvert."""
    code, rep, _ = rm._decider_bail("JOB", 4, {"action": "acquerir", "motif": "CI en job"})
    assert code == 200 and rep["bail"]["mode"] == "OBSERVATION" and corps["endormis"] == []
    assert rep["bail"]["interrompus"], "l'observation doit dire qui AURAIT cede"


def test_une_selection_illisible_se_dit_et_n_agit_pas(corps, monkeypatch):
    _armer(corps)
    monkeypatch.setattr(rm, "_statut_superviseur", lambda: None)
    code, rep, _ = rm._decider_bail("CI_REF", 2, {"action": "acquerir", "motif": "x"})
    assert code == 503 and rep["bail"]["etat"] == "ILLISIBLE" and "ILLISIBLE" in rep["bail"]["selection"]
    assert corps["endormis"] == []


def test_la_route_du_hub_route_le_bail_vers_sa_decision(corps):
    code, rep, _ = rm.decider_demande_deleguee("CI_REF", 2, {"bail": {"action": "etat"}})
    assert code == 200 and rep["arme"] is False and rep["actifs"] == []


def test_le_contexte_libere_toujours_meme_si_la_tache_leve(monkeypatch):
    appels = []
    monkeypatch.setattr(rm, "demander_bail",
                        lambda action, **ch: appels.append(action) or {"ok": True, "bail": {"id": "b1"}})
    with pytest.raises(RuntimeError):
        with rm.bail_priorite("CI"):
            raise RuntimeError("la CI tombe")
    assert appels == ["acquerir", "liberer"]
