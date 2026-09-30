"""Non-regression : les gardes du watchdog de daemons, et le capteur d'interpreteur.

Ces tests portent sur un defaut MESURE le 2026-08-25 : le heartbeat de
`gemini_poll_daemon` avait 535 776 s (6,2 jours) alors que le service porte
`disabled = true` par decision owner. `_watchdog_daemons()` decidait donc « relancer »
a chaque tick de 300 s depuis six jours, sans cooldown, sans budget, et surtout sans
jamais verifier que la relance produisait quoi que ce soit.

On teste l'EFFET, pas la presence du code : chaque cas verifie qu'un `Popen` a bien
lieu — ou n'a PAS lieu. Un test qui se contenterait de lire les constantes passerait
sur un watchdog dont les gardes ne seraient jamais atteints.

Hermetique : `subprocess.Popen` est remplace (aucun process n'est lance) et le fichier
d'etat est redirige vers `tmp_path` (le sandbox vivant n'est jamais touche).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[2] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import forge_health_diagnostic as hd  # noqa: E402
import forge_homeostasis_orchestrator as ho  # noqa: E402


class _FauxProc:
    pid = 4242


@pytest.fixture()
def banc(tmp_path, monkeypatch):
    """Un watchdog isole : un seul daemon, heartbeat rance, aucun process reel."""
    hb = tmp_path / "faux_daemon.heartbeat"
    hb.write_text(
        json.dumps({"ts": (datetime.now() - timedelta(days=6)).isoformat()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ho, "_WATCHDOG_ETAT", tmp_path / "etat.json")
    monkeypatch.setattr(
        ho,
        "DAEMON_WATCHDOGS",
        [{"name": "faux_daemon", "heartbeat": hb, "cmd": ["python", "-c", "pass"],
          "stale_s": 600}],
    )
    lances: list[list] = []
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda cmd, **kw: (lances.append(cmd), _FauxProc())[1],
    )
    # Par defaut : rien n'est exempte, et l'etat declare est LISIBLE.
    monkeypatch.setattr(hd, "_daemons_au_repos_declare", lambda: (set(), "aucun"))
    return {"hb": hb, "lances": lances, "etat": tmp_path / "etat.json"}


def _seed(banc, **champs):
    base = {"echecs": 0, "derniere_tentative": 0.0, "quarantaine_jusqua": 0.0,
            "verdict_rendu": 0.0}
    base.update(champs)
    banc["etat"].write_text(json.dumps({"faux_daemon": base}), encoding="utf-8")


def _etat(banc) -> dict:
    return json.loads(banc["etat"].read_text(encoding="utf-8"))["faux_daemon"]


# --------------------------------------------------------------- garde 1 : declare

def test_un_daemon_eteint_volontairement_nest_jamais_relance(banc, monkeypatch):
    """Le defaut d'origine. Heartbeat rance + service eteint expres = ne rien faire."""
    monkeypatch.setattr(hd, "_daemons_au_repos_declare",
                        lambda: ({"faux"}, "disabled=true"))
    res = ho._watchdog_daemons()
    assert banc["lances"] == [], "un daemon eteint expres a ete relance"
    assert "au_repos_declare" in res["faux_daemon"]


def test_lexemption_survit_a_un_ecart_de_nommage(banc, monkeypatch):
    """`gemini_poll_daemon` cote watchdog, `gemini_poll` cote registre. Exiger
    l'egalite stricte fabriquerait une exemption qui ne s'applique jamais."""
    monkeypatch.setattr(hd, "_daemons_au_repos_declare",
                        lambda: ({"faux_worker"}, "sleeping"))
    ho._watchdog_daemons()
    assert banc["lances"] == []
    assert ho._watchdog_au_repos("gemini_poll_daemon", {"gemini_poll"}) is True


def test_etat_declare_illisible_fait_sabstenir_jamais_relancer(banc, monkeypatch):
    """Trois etats, pas deux. Ne pas savoir si un daemon est eteint expres n'autorise
    pas a le relancer : dupliquer un process sain coute plus cher qu'attendre un tick."""
    def _leve():
        raise OSError("registre injoignable")

    monkeypatch.setattr(hd, "_daemons_au_repos_declare", _leve)
    res = ho._watchdog_daemons()
    assert banc["lances"] == []
    assert res["faux_daemon"].startswith("indetermine")


# ---------------------------------------------------------------- garde 2 : cooldown

def test_le_cooldown_empeche_deux_relances_dans_la_meme_fenetre(banc):
    maintenant = time.time()
    _seed(banc, derniere_tentative=maintenant - 100, verdict_rendu=maintenant - 100)
    res = ho._watchdog_daemons()
    assert banc["lances"] == []
    assert res["faux_daemon"].startswith("cooldown")


def test_hors_cooldown_la_relance_a_bien_lieu(banc):
    """Temoin : les gardes bornent, ils ne paralysent pas."""
    res = ho._watchdog_daemons()
    assert len(banc["lances"]) == 1, "aucune relance alors que rien ne s'y oppose"
    assert "relance(" in res["faux_daemon"]
    assert _etat(banc)["derniere_tentative"] > 0


# --------------------------------------------------------- garde 3 : post-condition

def test_une_relance_sans_effet_est_comptee_comme_un_echec(banc):
    """`Popen` qui rend la main n'est pas un accuse de reception. Si le heartbeat n'a
    pas repris apres la fenetre accordee, la tentative a ECHOUE."""
    _seed(banc, derniere_tentative=time.time() - 1000)
    ho._watchdog_daemons()
    assert _etat(banc)["echecs"] == 1


def test_un_heartbeat_qui_repart_remet_les_compteurs_a_zero(banc):
    """Symetrique : la guerison doit desarmer les gardes, sinon la quarantaine finit
    par tomber sur un organe redevenu sain."""
    banc["hb"].write_text(json.dumps({"ts": datetime.now().isoformat()}),
                          encoding="utf-8")
    _seed(banc, echecs=2, derniere_tentative=time.time() - 700)
    res = ho._watchdog_daemons()
    assert _etat(banc)["echecs"] == 0
    assert _etat(banc)["quarantaine_jusqua"] == 0.0
    assert res["faux_daemon"].startswith("ok(")


# ------------------------------------------------------ garde 4 : budget/quarantaine

def test_le_budget_epuise_declenche_la_quarantaine(banc):
    _seed(banc, echecs=ho._WATCHDOG_BUDGET)
    res = ho._watchdog_daemons()
    assert banc["lances"] == []
    assert "QUARANTAINE" in res["faux_daemon"]
    assert _etat(banc)["quarantaine_jusqua"] > time.time()


def test_la_quarantaine_tient_au_tick_suivant(banc):
    _seed(banc, quarantaine_jusqua=time.time() + 3600)
    res = ho._watchdog_daemons()
    assert banc["lances"] == []
    assert res["faux_daemon"].startswith("quarantaine(")


def test_les_gardes_survivent_au_respawn_du_regulateur(banc):
    """Un cooldown garde en memoire disparait au respawn — et c'est justement pendant
    une crise que le regulateur respawne. L'etat doit etre sur DISQUE."""
    ho._watchdog_daemons()
    assert banc["etat"].exists(), "aucun etat persiste : les gardes repartent a zero"
    assert _etat(banc)["derniere_tentative"] > 0


# ------------------------------------------------- capteur d'interpreteur, 3 etats

def test_linterpreteur_courant_prouve_sa_propre_presence():
    """Temoignage plutot que palpation : si ce code s'execute, son interpreteur existe.
    Le defaut corrige devinait la racine depuis un HOME que le compte de service
    resout a cote, et rendait « introuvable » pour -20 au score en permanence."""
    assert hd._interpreteur_laforge_present() is True


def test_une_declaration_qui_pointe_dans_le_vide_est_signalee(tmp_path):
    """Une declaration explicite fait AUTORITE : on repond sur elle. Enchainer sur un
    candidat de repli masquerait le defaut de configuration qu'on veut lever."""
    assert hd._interpreteur_laforge_present(str(tmp_path / "absent.exe")) is False


def test_un_parent_illisible_rend_indetermine_jamais_absent(monkeypatch, tmp_path):
    """`exists()` rend False aussi bien pour « absent » que pour « ACL me le cache ».
    Confondre les deux, c'est accuser un organe sain."""
    cible = tmp_path / "profil_ferme" / "python.exe"

    vrai_iterdir = Path.iterdir

    def _iterdir(self):
        if self.name == "profil_ferme":
            raise PermissionError("acces refuse")
        return vrai_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", _iterdir)
    assert hd._interpreteur_laforge_present(str(cible)) is None


def _audit_minimal() -> dict:
    """Un audit sain et complet : chaque test n'y change QUE ce qu'il examine."""
    return {
        "rag_chunks": {"pct_vectorized": 99.0, "non_vectorized": 0,
                       "duplicate_hashes": 0},
        "biblio": {"topics_total": 1, "raw_by_status": {}},
        "messages": {"agent_messages_pct_unread": 0.0, "agent_messages_total": 10,
                     "agent_messages_unread": 0},
        "lessons": {"solutions_total": 1, "errors_total": 0, "lessons_last_24h": 0},
        "db_size": {"size_mb_main": 100.0},
        "tables_empty": {"empty_tables": []},
        "workers_heartbeat": {},
        "services_http": {},
        "supervised_fleet": {"dead": [], "drift": [], "orphans": []},
        "constants": {"LAFORGE_PYTHON_path_exists": None,
                      "LAFORGE_ADMIN_TOKEN_set": True, "FORGE_MCP_TOKEN_set": True},
        "provider_keys": {"broken": []},
        "imports": {"broken": []},
        "journal_timestamps": {"scanned": 1, "undated": []},
        "host_vitals": {"ok": True, "ram_pct": 50.0, "disk_pct": 50.0, "gpu_pct": 1.0,
                        "tdr_recent": 0,
                        "ram_pct_1h": {"min": 40.0, "max": 60.0, "avg": 50.0}},
        "identification": {"lisible": True, "part_pct": 0.0, "total_1h": 10,
                           "anonymes_1h": 0, "agents": {}, "emetteurs": []},
    }


def test_le_scoring_ne_penalise_que_labsence_prouvee():
    """Le troisieme etat doit rester distinct EN AVAL : None ne coute aucun point."""
    base = _audit_minimal()
    base["constants"]["LAFORGE_PYTHON_path_exists"] = None
    score_indetermine, _ = hd.compute_score_and_gaps(json.loads(json.dumps(base)))
    base["constants"]["LAFORGE_PYTHON_path_exists"] = True
    score_present, _ = hd.compute_score_and_gaps(json.loads(json.dumps(base)))
    assert score_indetermine == score_present, (
        "un capteur qui n'a PAS PU regarder fait perdre des points"
    )


# ------------------------------------------- fusion de capteurs branchee au scoring

def _audit_avec_port_muet() -> dict:
    a = _audit_minimal()
    a["supervised_fleet"] = {
        "dead": [{"service": "NokidoTest", "port": 7474, "registry_pid": 1}],
        "drift": [], "orphans": [],
    }
    return a


def _score_avec_verdict(monkeypatch, verdict: str):
    import forge_sensor_fusion_probe as sf

    monkeypatch.setattr(sf, "probe",
                        lambda service, port=None: {"verdict": verdict})
    return hd.compute_score_and_gaps(_audit_avec_port_muet())


def test_un_service_endormi_nest_plus_accuse_de_panne(monkeypatch):
    """Le defaut mesure : `NokidoGraph` etait declare ❌ « RIEN n'ecoute » pour -5,
    alors que la fusion le dit `endormi`, consensus complet, zero desaccord. Un port
    muet est un CONSTAT ; seule la fusion en fait un diagnostic."""
    score, gaps = _score_avec_verdict(monkeypatch, "endormi")
    assert score == hd.compute_score_and_gaps(_audit_minimal())[0], (
        "un service endormi fait encore perdre des points"
    )
    assert any("EXPLIQUÉ" in g for g in gaps)
    assert not any("RIEN n'écoute" in g for g in gaps)


def test_un_fantome_reste_penalise(monkeypatch):
    """Temoin : qualifier n'est pas absoudre. Un pid disparu que personne ne
    relancera doit rester une pathologie franche."""
    score, gaps = _score_avec_verdict(monkeypatch, "fantome")
    assert score < hd.compute_score_and_gaps(_audit_minimal())[0]
    assert any("FANTÔME" in g for g in gaps)


def test_un_verdict_impossible_naccuse_pas_lorgane(monkeypatch):
    """Sonde absente = capteur manquant, pas organe fautif. Confondre les deux fait
    accuser un service sain — et un garde qui crie a faux se fait desarmer."""
    score, gaps = _score_avec_verdict(monkeypatch, "indeterminable")
    assert score == hd.compute_score_and_gaps(_audit_minimal())[0]
    assert any("Verdict IMPOSSIBLE" in g for g in gaps)


def test_un_capteur_indisponible_est_dit_jamais_masque(monkeypatch):
    """Repli DIT. Sans la fusion on retombe sur le constat brut, et on l'annonce :
    un repli silencieux ferait passer « je n'ai pas pu qualifier » pour « c'est bien
    un defaut »."""
    import forge_sensor_fusion_probe as sf

    def _leve(service, port=None):
        raise RuntimeError("capteur injoignable")

    monkeypatch.setattr(sf, "probe", _leve)
    _score, gaps = hd.compute_score_and_gaps(_audit_avec_port_muet())
    assert any("NON QUALIFIÉ" in g for g in gaps)


# ---------------------------------------------- meta-sante : le diagnostic sur lui-meme

def test_la_confiance_est_le_produit_de_ce_quon_voit_et_de_laccord(monkeypatch):
    """Les deux parts n'ont aucun sens l'une sans l'autre : un capteur absent ne se
    compense pas par un capteur d'accord, et tout voir en se contredisant ne tranche
    rien. Donc un PRODUIT, pas une moyenne."""
    import forge_sensor_fusion_probe as sf

    monkeypatch.setattr(sf, "coverage", lambda: {
        "services_sondes": 10, "observables": 8, "zones_non_observables": 2,
        "par_verdict": {"sain": 8}, "en_desaccord": ["A"],
    })
    m = hd.audit_meta_sante()
    assert m["part_observable"] == 0.8
    assert m["part_en_accord"] == 0.9
    assert m["confiance"] == 0.72


def test_meta_sante_illisible_nest_pas_lue_comme_saine(monkeypatch):
    """Le defaut generique du corps : transformer « je n'ai rien vu » en « il n'y a
    rien ». Une meta-sante qui ne se calcule pas doit le DIRE."""
    import forge_sensor_fusion_probe as sf

    def _leve():
        raise RuntimeError("sonde absente")

    monkeypatch.setattr(sf, "coverage", _leve)
    m = hd.audit_meta_sante()
    assert m["lisible"] is False
    base = _audit_minimal()
    base["meta_sante"] = m
    _score, gaps = hd.compute_score_and_gaps(base)
    assert any("MÉTA-SANTÉ ILLISIBLE" in g for g in gaps)


def test_la_meta_sante_ne_retire_jamais_de_point():
    """Elle qualifie le score, elle ne le remplace pas. Un score qui absorberait sa
    propre incertitude deviendrait illisible dans les deux sens — et c'est la regle
    « ne fais pas du score de sante le cerveau »."""
    sans = _audit_minimal()
    avec = _audit_minimal()
    avec["meta_sante"] = {
        "lisible": True, "services_sondes": 55, "observables": 40,
        "zones_non_observables": 15, "par_verdict": {}, "en_desaccord": ["A", "B"],
        "part_observable": 0.727, "part_en_accord": 0.964, "confiance": 0.701,
    }
    score_sans, _ = hd.compute_score_and_gaps(sans)
    score_avec, gaps = hd.compute_score_and_gaps(avec)
    assert score_sans == score_avec, "la meta-sante a modifie le score"
    assert any("NON OBSERVABLE" in g for g in gaps)
    assert any("DÉSACCORD" in g for g in gaps)
    assert any("CONFIANCE" in g for g in gaps)


def test_une_confiance_pleine_ne_produit_aucune_reserve():
    """Temoin : la reserve doit apparaitre quand elle est meritee, et se taire sinon —
    un garde qui crie en permanence se fait desarmer."""
    a = _audit_minimal()
    a["meta_sante"] = {
        "lisible": True, "services_sondes": 55, "observables": 55,
        "zones_non_observables": 0, "par_verdict": {}, "en_desaccord": [],
        "part_observable": 1.0, "part_en_accord": 1.0, "confiance": 1.0,
    }
    _score, gaps = hd.compute_score_and_gaps(a)
    assert not any("CONFIANCE" in g or "NON OBSERVABLE" in g or "DÉSACCORD" in g
                   for g in gaps)
