"""NR — LM Studio pilote par Nokido, donc regulable (2026-08-18).

L'owner tenait 5,7 Go de modeles residents sans qu'aucun canal Nokido ne
puisse arreter le serveur : `SVC_MAP` mappait `lmstudio` sur `NokidoLMStudio`,
un service qui n'existe pas (`sc query` -> 1060). Un composant qu'on ne sait
pas arreter ne participe pas a l'autoregulation : il la subit, et la fait
echouer (Docker refuse a 98,5 % de RAM, veille bloquee).

Tests d'EFFET : chaque cas simule la dependance et lit le VERDICT rendu.
Aucun `inspect.getsource` ici — un test qui lit le code atteste qu'il est
ecrit, jamais qu'il fonctionne (cf. les instruments a 8,3 % du 2026-08-18).
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))

import forge_ensure_service as E  # noqa: E402
import forge_resource_manager as R  # noqa: E402


class _Reponse:
    """Contexte minimal facon http.client.HTTPResponse."""

    def __init__(self, charge: bytes, status: int = 200):
        self._charge, self.status = charge, status

    def read(self):
        return self._charge

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture(autouse=True)
def _hermetique(monkeypatch, tmp_path):
    # Le coffre DPAPI n'a rien a faire dans un test : hermetique par defaut.
    monkeypatch.setattr(E, "_lms_jeton", lambda: "")
    # Le journal d'usage est un fichier de PRODUCTION : le rediriger, sinon la
    # suite maquille l'etat que l'homeostat lit pour decider de couper.
    monkeypatch.setattr(E, "_USAGE", tmp_path / "lmstudio_usage.json")
    # ⚠️ PAYE LE 2026-08-18 : `_admission` ECRIT l'horodatage du reveil. Sans
    # redirection, la suite armait la periode refractaire de PRODUCTION —
    # chaque `pytest` interdisait tout demarrage reel pendant trois minutes,
    # et j'ai cherche le defaut dans le garde avant de le trouver dans le test.
    monkeypatch.setattr(E, "_REVEILS", tmp_path / "ensure_reveils.json")


def _urlopen(monkeypatch, effet):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: effet())


# ── la sonde : 401 est un serveur VIVANT, pas un cadavre ────────────────────

def test_sonde_401_prouve_un_serveur_vivant(monkeypatch):
    """LM Studio rend 401 sans jeton. Le lire « mort » ferait croire a un
    `stopped` reussi alors que le serveur tient toujours la RAM."""
    def _leve():
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    _urlopen(monkeypatch, _leve)
    assert E._sonde_lmstudio() is True


def test_sonde_5xx_est_un_serveur_casse(monkeypatch):
    def _leve():
        raise urllib.error.HTTPError("u", 503, "Unavailable", {}, None)

    _urlopen(monkeypatch, _leve)
    assert E._sonde_lmstudio() is False


def test_sonde_port_ferme(monkeypatch):
    def _leve():
        raise ConnectionRefusedError(10061, "refus")

    _urlopen(monkeypatch, _leve)
    monkeypatch.setattr(E, "_port_ouvert", lambda *a, **k: False)
    assert E._sonde_lmstudio() is False


def test_serveur_occupe_nest_pas_un_serveur_arrete(monkeypatch):
    """MESURE 2026-08-18 : pendant un chargement de modele, LM Studio cesse de
    repondre a son API alors que le port TCP reste OUVERT. Sans ce cas, `stopped`
    a annonce « deja arrete : RIEN a liberer » pendant que le serveur tenait la
    memoire — une regulation qui croit avoir libere autorise la suite."""
    def _leve():
        raise TimeoutError("timed out")

    _urlopen(monkeypatch, _leve)
    monkeypatch.setattr(E, "_port_ouvert", lambda *a, **k: True)
    assert E._sonde_lmstudio() is True


def test_sonde_catalogue_vide_nest_pas_pret(monkeypatch):
    _urlopen(monkeypatch, lambda: _Reponse(b'{"data": []}'))
    assert E._sonde_lmstudio() is False
    _urlopen(monkeypatch, lambda: _Reponse(b'{"data": [{"id": "qwen"}]}'))
    assert E._sonde_lmstudio() is True


# ── le verdict vient du PORT, jamais du rc du CLI ───────────────────────────

def test_arret_sur_port_deja_muet_ne_credite_rien(monkeypatch):
    """Annoncer « RAM des modeles liberee » quand rien ne tournait ferait
    surestimer la memoire disponible dans le journal de regulation."""
    monkeypatch.setattr(E, "_lms_bin", lambda: None)
    monkeypatch.setattr(E, "_sonde_lmstudio", lambda **k: False)

    def _interdit(*a, **k):
        raise AssertionError("aucun canal ne doit etre sollicite : rien ne tourne")

    monkeypatch.setattr(E, "_jouer", _interdit)
    r = E._lmstudio("stopped")
    assert r["success"] is True and "RIEN a liberer" in r["detail"]


def test_stop_echoue_si_le_port_repond_encore(monkeypatch):
    """`lms server stop` peut rendre 0 sans rien liberer : c'est le port qui
    tranche. Sinon Nokido annoncerait 5,7 Go rendus qui ne le sont pas."""
    monkeypatch.setattr(E, "_jouer", lambda b, o, d="": "rc=0 ")
    monkeypatch.setattr(E, "_lms_bin", lambda: r"C:\lms.exe")
    monkeypatch.setattr(E, "_sonde_lmstudio", lambda **k: True)  # il SERT avant
    # `_attendre_port` a son propre test : ici on ne veut que le VERDICT, pas
    # vingt secondes d'horloge reelle.
    monkeypatch.setattr(E, "_attendre_port", lambda vise, s=0.0: vise is True)
    r = E._lmstudio("stopped")
    assert r["success"] is False and "toujours ouvert" in r["detail"]


def test_stop_reussit_quand_le_port_se_tait(monkeypatch):
    monkeypatch.setattr(E, "_jouer", lambda b, o, d="": "rc=1 boom")
    monkeypatch.setattr(E, "_lms_bin", lambda: r"C:\lms.exe")
    monkeypatch.setattr(E, "_sonde_lmstudio", lambda **k: True)  # il SERT avant
    monkeypatch.setattr(E, "_attendre_port", lambda vise, s=0.0: vise is False)
    monkeypatch.setattr(E, "_ram_libre_go", lambda: 4.0)
    r = E._lmstudio("stopped")
    assert r["success"] is True


def test_arret_annonce_le_delta_mesure(monkeypatch):
    """MESURE 2026-08-18 : arreter un serveur sans modele resident n'a rien
    rendu (78,1 % avant comme apres). Annoncer « RAM rendue » par principe
    ferait surestimer la memoire disponible."""
    monkeypatch.setattr(E, "_jouer", lambda b, o, d="": "rc=0")
    monkeypatch.setattr(E, "_lms_bin", lambda: r"C:\lms.exe")
    monkeypatch.setattr(E, "_sonde_lmstudio", lambda **k: True)
    monkeypatch.setattr(E, "_attendre_port", lambda vise, s=0.0: vise is False)
    mesures = iter([5.17, 5.18])  # inchangee, aux arrondis pres
    monkeypatch.setattr(E, "_ram_libre_go", lambda: next(mesures))
    assert "inchangee" in E._lmstudio("stopped")["detail"]


def test_arret_chiffre_une_vraie_liberation(monkeypatch):
    monkeypatch.setattr(E, "_jouer", lambda b, o, d="": "rc=0")
    monkeypatch.setattr(E, "_lms_bin", lambda: r"C:\lms.exe")
    monkeypatch.setattr(E, "_sonde_lmstudio", lambda **k: True)
    monkeypatch.setattr(E, "_attendre_port", lambda vise, s=0.0: vise is False)
    mesures = iter([2.0, 7.7])
    monkeypatch.setattr(E, "_ram_libre_go", lambda: next(mesures))
    assert "+5.70 Go" in E._lmstudio("stopped")["detail"]


def test_start_ignore_le_rc_et_lit_le_port(monkeypatch):
    monkeypatch.setattr(E, "_jouer", lambda b, o, d="": "rc=0 ok")
    monkeypatch.setattr(E, "_lms_bin", lambda: r"C:\lms.exe")
    monkeypatch.setattr(E, "_attendre_port", lambda vise, s=0.0: vise is False)
    assert E._lmstudio("running")["success"] is False


def test_aucun_canal_rend_non_mesure_pas_mort(monkeypatch):
    """Ni CLI local ni pont owner : c'est NON MESURE. Dire « mort » ferait
    croire a une panne du serveur au lieu d'un defaut de canal."""
    monkeypatch.setattr(E, "_jouer", lambda b, o, d="": None)
    monkeypatch.setattr(E, "_lms_bin", lambda: None)
    r = E._lmstudio("running")
    assert r["success"] is False and "NON MESURE" in r["detail"]


# ── le canal qui execute SOUS l'identite de l'owner ─────────────────────────

def test_la_tache_planifiee_passe_avant_le_pont(monkeypatch):
    """Le pont place le child dans la session interactive mais avec le token
    LaForgeTrusted (mesure : `USERPROFILE=C:\\Users\\Default`) : seul le
    planificateur execute sous l'identite de l'owner."""
    monkeypatch.setattr(E, "_lms_tache", lambda d: "[tache Nokido-LMStudio-Start rc=0]")

    def _interdit(*a, **k):
        raise AssertionError("le pont ne doit pas etre ouvert si la tache repond")

    monkeypatch.setattr(E, "_lms_owner", _interdit)
    assert "Nokido-LMStudio-Start" in E._jouer(None, ["server", "start"], "running")


def test_sans_tache_on_retombe_sur_le_pont(monkeypatch):
    monkeypatch.setattr(E, "_lms_tache", lambda d: None)
    monkeypatch.setattr(E, "_lms_owner",
                        lambda o, **k: {"user": "laforgetrusted", "rc": "1",
                                        "stdout": "Acces refuse."})
    trace = E._jouer(None, ["server", "start"], "running")
    assert "laforgetrusted" in trace and "Acces refuse" in trace


def test_tache_absente_nest_pas_declenchee(monkeypatch):
    monkeypatch.setattr(E, "_tache_existe", lambda n: False)

    def _interdit(*a, **k):
        raise AssertionError("ne jamais lancer une tache dont l'existence n'est pas mesuree")

    monkeypatch.setattr(E.subprocess, "run", _interdit)
    assert E._lms_tache("running") is None


def test_attendre_port_ne_conclut_pas_au_premier_coup(monkeypatch):
    """Un serveur qui monte n'est pas un serveur mort : conclure des le retour
    du declencheur refabriquerait le faux mort des backends locaux."""
    monkeypatch.setattr(E.time, "sleep", lambda *_: None)
    etats = iter([False, False, True])
    monkeypatch.setattr(E, "_sonde_lmstudio", lambda **k: next(etats))
    assert E._attendre_port(True, 30.0) is True


def _proc(rc: int, sortie: str = ""):
    return type("P", (), {"returncode": rc, "stdout": sortie, "stderr": ""})()


def test_acl_fermee_ne_se_lit_pas_tache_absente(monkeypatch):
    """MESURE 2026-08-18 : une tache creee par l'owner rend « Acces refuse » des
    le /query depuis un compte de service. La confondre avec une absence fait
    chercher un fantome au lieu de faire ouvrir un droit."""
    monkeypatch.setattr(E.subprocess, "run",
                        lambda *a, **k: _proc(1, "ERREUR: Acces refuse."))
    assert E._etat_tache("Nokido-LMStudio-Start") == "refusee"
    trace = E.declencher_tache("Nokido-LMStudio-Start")
    # Le message doit nommer l'ACL, le compte MESURE, et l'endroit ou vit le
    # descripteur — c'est ce triplet qui evite de refaire l'enquete du jour.
    assert trace is not None and "ACL" in trace
    assert "Compte MESURE" in trace and "TaskCache" in trace


def test_tache_vraiment_absente_rend_none(monkeypatch):
    monkeypatch.setattr(E.subprocess, "run",
                        lambda *a, **k: _proc(1, "ERREUR: introuvable"))
    assert E._etat_tache("Nokido-Absente") == "absente"
    assert E.declencher_tache("Nokido-Absente") is None


def test_planificateur_injoignable_nest_pas_un_refus(monkeypatch):
    def _leve(*a, **k):
        raise OSError("schtasks absent")

    monkeypatch.setattr(E.subprocess, "run", _leve)
    assert E._etat_tache("Nokido-LMStudio-Stop") == "absente"


def test_attendre_port_abandonne_sur_delai(monkeypatch):
    monkeypatch.setattr(E.time, "sleep", lambda *_: None)
    monkeypatch.setattr(E, "_sonde_lmstudio", lambda **k: False)
    assert E._attendre_port(True, 0.0) is False


def test_desired_state_inconnu_est_refuse(monkeypatch):
    monkeypatch.setattr(E, "_lms_bin", lambda: None)
    assert E._lmstudio("paused")["success"] is False


# ── le dispatch ne retombe plus sur un service Windows fantome ──────────────

def test_lmstudio_nest_plus_un_service_windows(monkeypatch):
    assert "lmstudio" not in E.SVC_MAP

    def _interdit(*a, **k):
        raise AssertionError("le supervisor NSSM ne doit jamais voir lmstudio")

    monkeypatch.setattr(E, "_supervisor", _interdit)
    monkeypatch.setattr(E, "_ram_pct", lambda: 10.0)
    monkeypatch.setattr(E, "_lmstudio", lambda d: {"service": "lmstudio", "ok": True})
    assert E.ensure("lmstudio", "stopped")["ok"] is True


# ── autoregulation : liberer doit TOUJOURS rester possible ──────────────────

def test_lmstudio_compte_comme_couteux():
    assert "lmstudio" in E._COUTEUX


def test_stopped_jamais_refuse_meme_ram_saturee(monkeypatch):
    """Refuser un arret sous pression RAM serait un interblocage : le seul
    geste qui rend de la memoire deviendrait indisponible quand elle manque."""
    monkeypatch.setattr(E, "_ram_pct", lambda: 99.0)
    assert E._admission("lmstudio", "stopped") is None


def test_running_refuse_au_dessus_du_plafond(monkeypatch):
    monkeypatch.setattr(E, "_ram_pct", lambda: E._RAM_PLAFOND_PCT + 1.0)
    refus = E._admission("lmstudio", "running")
    assert refus is not None and refus["success"] is False


def test_running_admis_sous_le_plafond(monkeypatch):
    monkeypatch.setattr(E, "_ram_pct", lambda: 40.0)
    monkeypatch.setattr(E, "_ram_libre_go", lambda: 12.0)
    assert E._admission("lmstudio", "running") is None


def test_reveil_refuse_sans_la_place_du_modele(monkeypatch):
    """MESURE 2026-08-18 : demarrage a 53 % de RAM, puis le chargement d'un 7B
    a porte la machine a 99,4 %. Un plafond en POURCENTAGE juge l'etat avant le
    geste et ne dit rien de son cout : 85 % autorisait ce reveil."""
    monkeypatch.setattr(E, "_ram_pct", lambda: 53.0)  # sous le plafond
    monkeypatch.setattr(E, "_ram_libre_go", lambda: 5.2)  # mais pas la place
    refus = E._admission("lmstudio", "running")
    assert refus is not None and refus["refus"] == "place_insuffisante"


def test_ram_illisible_ne_refuse_pas(monkeypatch):
    """0.0 veut dire « je n'ai pas su lire », pas « zero octet libre »."""
    monkeypatch.setattr(E, "_ram_pct", lambda: 40.0)
    monkeypatch.setattr(E, "_ram_libre_go", lambda: 0.0)
    assert E._admission("lmstudio", "running") is None


def test_liberer_reste_possible_sans_place(monkeypatch):
    monkeypatch.setattr(E, "_ram_libre_go", lambda: 0.3)
    assert E._admission("lmstudio", "stopped") is None


# ── POLITIQUE : allume quand utile, coupe des que plus necessaire ───────────

def test_usage_se_date_et_se_relit():
    assert E.inactif_depuis("lmstudio") is None  # aucun usage : « je ne sais pas »
    E.marquer_usage("lmstudio")
    depuis = E.inactif_depuis("lmstudio")
    assert depuis is not None and depuis < 5.0


def test_aucun_usage_date_nest_pas_une_inactivite(monkeypatch):
    """None veut dire NON MESURE. Le lire « inactif depuis toujours » couperait
    un serveur dont on ne sait rien."""
    monkeypatch.setattr(R, "_lmstudio_sert", lambda: True)
    monkeypatch.setattr(E, "est_pilote", lambda s="lmstudio": True)
    monkeypatch.setattr(E, "inactif_depuis", lambda s="lmstudio": None)

    def _interdit(*a, **k):
        raise AssertionError("ne jamais couper sur une mesure absente")

    monkeypatch.setattr(E, "ensure", _interdit)
    assert R.lmstudio_arret_si_inactif()["action"] == "noop"


def test_serveur_de_l_owner_jamais_coupe(monkeypatch):
    """Un serveur que Nokido n'a pas allume ne lui appartient pas — meme si une
    vieille date d'usage le fait paraitre inutile."""
    monkeypatch.setattr(R, "_lmstudio_sert", lambda: True)
    monkeypatch.setattr(E, "est_pilote", lambda s="lmstudio": False)
    monkeypatch.setattr(E, "inactif_depuis", lambda s="lmstudio": 99999.0)

    def _interdit(*a, **k):
        raise AssertionError("ne jamais couper le serveur de l'owner")

    monkeypatch.setattr(E, "ensure", _interdit)
    r = R.lmstudio_arret_si_inactif()
    assert r["action"] == "noop" and "owner" in r["raison"]


def test_coupe_apres_le_seuil_dinactivite(monkeypatch):
    monkeypatch.setattr(R, "_lmstudio_sert", lambda: True)
    monkeypatch.setattr(E, "est_pilote", lambda s="lmstudio": True)
    monkeypatch.setattr(E, "inactif_depuis", lambda s="lmstudio": E._INACTIVITE_S + 1)
    vus = []
    monkeypatch.setattr(E, "ensure",
                        lambda s, st: vus.append((s, st)) or {"detail": "arrete"})
    assert R.lmstudio_arret_si_inactif()["action"] == "stopped"
    assert vus == [("lmstudio", "stopped")]


def test_ne_coupe_pas_avant_le_seuil(monkeypatch):
    monkeypatch.setattr(R, "_lmstudio_sert", lambda: True)
    monkeypatch.setattr(E, "est_pilote", lambda s="lmstudio": True)
    monkeypatch.setattr(E, "inactif_depuis", lambda s="lmstudio": 10.0)

    def _interdit(*a, **k):
        raise AssertionError("il servait il y a 10 s")

    monkeypatch.setattr(E, "ensure", _interdit)
    assert R.lmstudio_arret_si_inactif()["action"] == "noop"


def test_arret_ne_depend_pas_de_la_pression_ram(monkeypatch):
    """La consigne est de rendre ce qui est inutile, pas d'attendre la saturation :
    garder 5,7 Go tant que la machine respire est l'inverse de la politique."""
    monkeypatch.setattr(R, "_lmstudio_sert", lambda: True)
    monkeypatch.setattr(E, "est_pilote", lambda s="lmstudio": True)
    monkeypatch.setattr(E, "inactif_depuis", lambda s="lmstudio": E._INACTIVITE_S + 1)
    monkeypatch.setattr(E, "_ram_pct", lambda: 12.0)  # machine au repos
    monkeypatch.setattr(E, "ensure", lambda s, st: {"detail": "arrete"})
    assert R.lmstudio_arret_si_inactif()["action"] == "stopped"


def test_pilotage_se_note_et_se_relit():
    assert E.est_pilote("lmstudio") is False
    E.marquer_pilotage(True)
    assert E.est_pilote("lmstudio") is True
    # Un demarrage compte comme un usage, sinon le tick suivant le couperait.
    assert (E.inactif_depuis("lmstudio") or 999) < 5.0
    E.marquer_pilotage(False)
    assert E.est_pilote("lmstudio") is False


# ── un refus de reveil n'est pas un serveur injoignable ─────────────────────

def test_refus_de_reveil_est_nomme(monkeypatch):
    """Rendre un simple False laissait l'appel echouer sur URLError 10061 : le
    diagnostic devenait « serveur injoignable » alors que Nokido avait DECIDE
    de ne pas le reveiller. Deux causes opposees — l'une a corriger, l'autre a
    respecter."""
    import forge_agent_proxy as P

    monkeypatch.setattr(P, "_lmstudio_pilotage", lambda: E)
    monkeypatch.setattr(E, "_sonde_lmstudio", lambda **k: False)
    monkeypatch.setattr(E, "ensure", lambda s, st: {
        "success": False, "refus": "place_insuffisante",
        "detail": "4.2 Go libres, il en faut 7"})
    with pytest.raises(RuntimeError) as exc:
        P._lmstudio_reveiller_si_besoin()
    assert "place_insuffisante" in str(exc.value) and "4.2 Go" in str(exc.value)


def test_serveur_deja_vivant_ne_leve_pas(monkeypatch):
    import forge_agent_proxy as P

    monkeypatch.setattr(P, "_lmstudio_pilotage", lambda: E)
    monkeypatch.setattr(E, "_sonde_lmstudio", lambda **k: True)

    def _interdit(*a, **k):
        raise AssertionError("aucun reveil ne doit etre demande : il sert deja")

    monkeypatch.setattr(E, "ensure", _interdit)
    P._lmstudio_reveiller_si_besoin()


def test_echec_sans_refus_laisse_l_appel_trancher(monkeypatch):
    """Un echec SANS motif de refus (le demarrage a echoue) ne doit pas masquer
    l'erreur reelle du port : on laisse l'appelant la rencontrer."""
    import forge_agent_proxy as P

    monkeypatch.setattr(P, "_lmstudio_pilotage", lambda: E)
    monkeypatch.setattr(E, "_sonde_lmstudio", lambda **k: False)
    monkeypatch.setattr(E, "ensure", lambda s, st: {"success": False,
                                                    "detail": "port muet apres start"})
    P._lmstudio_reveiller_si_besoin()  # ne leve pas


# ── la RAM des modeles doit etre RECLAMABLE, et le chiffre MESURE ───────────

def test_le_reclaimer_est_declare():
    """Le 2026-08-03, `reclaimers_declares()` rendait [] : le mecanisme
    existait, personne ne s'y etait inscrit. Un levier non declare est absent
    le jour de la saturation."""
    assert "lmstudio_models" in R.reclaimers_declares()


@pytest.fixture(autouse=True)
def _sans_tache(monkeypatch):
    """Par defaut aucune tache planifiee : les tests du pont doivent l'atteindre.
    Sans cela, leur verdict dependrait des taches REELLES de la machine."""
    monkeypatch.setattr(E, "_tache_existe", lambda n: False)


def test_serveur_muet_ne_reclame_rien(monkeypatch):
    """Sans serveur il n'y a rien a rendre : ne pas payer un spawn de pont."""
    monkeypatch.setattr(R, "_lmstudio_sert", lambda: False)

    def _interdit(*a, **k):
        raise AssertionError("aucun pont ne doit etre ouvert sur un port muet")

    monkeypatch.setattr(R, "_free_now", _interdit)
    assert R.lmstudio_unload_all() == 0.0


def test_le_reclaimer_rend_le_delta_mesure(monkeypatch):
    monkeypatch.setattr(R, "_lmstudio_sert", lambda: True)
    monkeypatch.setattr(R.time, "sleep", lambda *_: None)
    mesures = iter([3.0, 8.7])
    monkeypatch.setattr(R, "_free_now", lambda: next(mesures))
    monkeypatch.setitem(sys.modules, "forge_owner_bridge",
                        type(sys)("forge_owner_bridge"))
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_owner_bridge",
                        type(sys)("nokido_agent.tools.forge_owner_bridge"))
    sys.modules["forge_owner_bridge"].run_in_owner = lambda *a, **k: {"ok": True}
    sys.modules["nokido_agent.tools.forge_owner_bridge"].run_in_owner = lambda *a, **k: {"ok": True}
    assert R.lmstudio_unload_all() == 5.7


def test_un_unload_sans_effet_rend_zero_pas_une_promesse(monkeypatch):
    """Rendre la taille annoncee du modele ferait croire a de la place faite,
    et autoriserait un spawn qui ferait tomber la machine."""
    monkeypatch.setattr(R, "_lmstudio_sert", lambda: True)
    monkeypatch.setattr(R.time, "sleep", lambda *_: None)
    mesures = iter([6.0, 5.2])  # la RAM libre a BAISSE pendant l'operation
    monkeypatch.setattr(R, "_free_now", lambda: next(mesures))
    monkeypatch.setitem(sys.modules, "forge_owner_bridge",
                        type(sys)("forge_owner_bridge"))
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_owner_bridge",
                        type(sys)("nokido_agent.tools.forge_owner_bridge"))
    sys.modules["forge_owner_bridge"].run_in_owner = lambda *a, **k: {"ok": True}
    sys.modules["nokido_agent.tools.forge_owner_bridge"].run_in_owner = lambda *a, **k: {"ok": True}
    assert R.lmstudio_unload_all() == 0.0


def test_le_reclaimer_prefere_la_tache_au_pont(monkeypatch):
    """Le pont s'execute en laforgetrusted et se fait refuser le profil : si la
    tache repond, il ne doit meme pas etre ouvert."""
    monkeypatch.setattr(R, "_lmstudio_sert", lambda: True)
    monkeypatch.setattr(R.time, "sleep", lambda *_: None)
    mesures = iter([2.0, 4.5])
    monkeypatch.setattr(R, "_free_now", lambda: next(mesures))
    monkeypatch.setattr(E, "_tache_existe", lambda n: True)
    monkeypatch.setattr(E.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "",
                                                       "stderr": ""})())

    def _interdit(*a, **k):
        raise AssertionError("le pont ne doit pas etre ouvert si la tache repond")

    monkeypatch.setitem(sys.modules, "forge_owner_bridge",
                        type(sys)("forge_owner_bridge"))
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_owner_bridge",
                        type(sys)("nokido_agent.tools.forge_owner_bridge"))
    sys.modules["forge_owner_bridge"].run_in_owner = _interdit
    sys.modules["nokido_agent.tools.forge_owner_bridge"].run_in_owner = _interdit
    assert R.lmstudio_unload_all() == 2.5


def test_pont_indisponible_rend_zero_sans_lever(monkeypatch):
    monkeypatch.setattr(R, "_lmstudio_sert", lambda: True)
    monkeypatch.setattr(R, "_free_now", lambda: 4.0)
    monkeypatch.setitem(sys.modules, "forge_owner_bridge",
                        type(sys)("forge_owner_bridge"))
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_owner_bridge",
                        type(sys)("nokido_agent.tools.forge_owner_bridge"))

    def _casse(*a, **k):
        raise OSError("session console absente")

    sys.modules["forge_owner_bridge"].run_in_owner = _casse
    sys.modules["nokido_agent.tools.forge_owner_bridge"].run_in_owner = _casse
    assert R.lmstudio_unload_all() == 0.0
