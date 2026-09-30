"""NR — le diagnostic de demarrage du daemon MESURE, il ne devine pas.

MESURE QUI A MOTIVE CE FICHIER (2026-08-31) : le daemon des boucles a demarre
**34 fois dans la journee** et **2 984 fois** dans l'historique de son journal,
parfois a 3 secondes d'intervalle — pendant que le superviseur affichait
`restarts: 0`. Et ses morts ne laissent presque aucune trace : 120 `Traceback`
et 114 `shutdown` pour 2 984 demarrages.

Le defaut n'est donc PAS l'absence de reprise : le superviseur respawn tres bien.
C'est que la serie est INVISIBLE et SANS CAUSE. Cet emetteur la rend mesurable,
ce qui est le prealable de tout correctif : sans denominateur, on ne saura jamais
si une politique de redemarrage future ameliore quoi que ce soit.

LA REGLE QUE CES TESTS PROTEGENT : on ne deduit JAMAIS la cause d'une mort de
l'absence d'un pouls. Pas de pouls ne veut pas dire « crash », ca veut dire qu'on
ne sait pas. Et une vitalite non verifiable ne vaut pas « mort » — sinon un
`psutil` manquant ferait passer un recouvrement pour une reprise propre.

HERMETIQUE : fonction pure, horloge et test de vitalite injectes. Aucun process,
aucun fichier reel, aucun service.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "app", _ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app import forge_autonomous_loops as al  # noqa: E402

_MAINTENANT = 1788190000.0
_ISO_RECENT = "2026-08-31T15:57:48"      # horodatage plausible, gap calculable


def _pouls(pid=999, ts=_ISO_RECENT, patterns=23) -> dict:
    d = {"pid": pid, "patterns": patterns, "interval_s": 60}
    if ts is not None:
        d["ts"] = ts
    return d


def _diag(pouls, pid=13060, vivant=None, **kw):
    return al.diagnostic_demarrage(pouls, pid, 23, vivant=vivant,
                                   maintenant=_MAINTENANT, **kw)


# ── 1 / 6 : rien a lire ──────────────────────────────────────────────────────
def test_1_aucun_pouls_precedent_est_NEW_START_pas_un_crash():
    """L'absence de pouls ne prouve RIEN sur la mort precedente."""
    r = _diag(None)
    assert r["startup_reason"] == "NEW_START"
    assert r["previous_pid"] is None
    assert r["gap_s"] is None
    assert "crash" not in r["detail"].lower()


@pytest.mark.parametrize("illisible", ["pas un dict", 42, [], b"x"])
def test_6_un_pouls_ILLISIBLE_est_NEW_START(illisible):
    assert _diag(illisible)["startup_reason"] == "NEW_START"


def test_6bis_un_pouls_SANS_pid_est_NEW_START():
    r = _diag({"ts": _ISO_RECENT, "patterns": 21})
    assert r["startup_reason"] == "NEW_START"
    assert "sans pid" in r["detail"]


# ── 2 : autre pid, disparu ───────────────────────────────────────────────────
def test_2_autre_pid_mesure_DISPARU_est_une_RECOVERY():
    r = _diag(_pouls(pid=20148), vivant=lambda p: False)
    assert r["startup_reason"] == "RECOVERY"
    assert r["previous_pid"] == 20148
    # La cause n'est PAS inventee.
    assert "NON etablie" in r["detail"]


def test_2bis_la_recovery_reporte_les_grandeurs_du_pouls_precedent():
    r = _diag(_pouls(pid=20148, patterns=21), vivant=lambda p: False)
    assert r["previous_patterns"] == 21
    assert r["previous_pulse"] == _ISO_RECENT
    assert r["pid"] == 13060 and r["patterns"] == 23
    assert isinstance(r["gap_s"], float)


# ── 3 : autre pid encore vivant ──────────────────────────────────────────────
def test_3_autre_pid_ENCORE_VIVANT_est_un_recouvrement_SUSPECTE():
    """Deux instances ont deja coexiste 9 minutes le 2026-08-31, partageant
    journal, pouls, etat de veille et drapeaux. Le dire au demarrage."""
    r = _diag(_pouls(pid=20124), vivant=lambda p: True)
    assert r["startup_reason"] == "OVERLAP_SUSPECTED"
    assert "ENCORE VIVANT" in r["detail"]


def test_3bis_un_pouls_ANCIEN_d_un_pid_vivant_reste_suspect_mais_le_DIT():
    r = _diag(_pouls(pid=20124, ts="2026-08-31T10:00:00"), vivant=lambda p: True,
              fraicheur=60.0)
    assert r["startup_reason"] == "OVERLAP_SUSPECTED"
    assert "pouls ancien" in r["detail"]


# ── 4 : meme pid ─────────────────────────────────────────────────────────────
def test_4_le_meme_pid_n_est_pas_une_transition():
    r = _diag(_pouls(pid=13060), pid=13060, vivant=lambda p: True)
    assert r["startup_reason"] == "SAME_PID"


# ── 5 : horodatage illisible ─────────────────────────────────────────────────
@pytest.mark.parametrize("ts", [None, "", "pas une date", 12345, "31/08/2026"])
def test_5_horodatage_ILLISIBLE_donne_un_gap_NUL_jamais_zero(ts):
    """Un gap a zero ferait croire a une transition instantanee. `None` dit
    qu'on n'a pas pu le calculer, ce qui n'est pas la meme chose."""
    r = _diag(_pouls(pid=20148, ts=ts), vivant=lambda p: False)
    assert r["gap_s"] is None
    assert r["gap_s"] != 0
    # Le motif reste juste : l'horodatage illisible n'empeche pas de savoir
    # QUI etait la.
    assert r["startup_reason"] == "RECOVERY"


# ── la vitalite non verifiable ───────────────────────────────────────────────
def test_vitalite_NON_VERIFIABLE_n_est_pas_une_mort():
    """Sans cette troisieme valeur, un psutil absent ferait passer une instance
    vivante pour morte — donc un recouvrement pour une reprise propre."""
    r = _diag(_pouls(pid=20124), vivant=lambda p: None)
    assert r["startup_reason"] == "INDETERMINE"
    assert r["startup_reason"] != "RECOVERY"
    assert "non verifiable" in r["detail"]


def test_un_test_de_vitalite_qui_LEVE_ne_fait_pas_conclure(monkeypatch):
    def _boum(pid):
        raise OSError("acces refuse")

    monkeypatch.setattr(al, "_pid_vivant", lambda p: None)
    r = al.diagnostic_demarrage(_pouls(pid=20124), 13060, 23,
                                maintenant=_MAINTENANT)
    assert r["startup_reason"] == "INDETERMINE"


def test_le_lecteur_de_pouls_rend_None_sur_fichier_absent(tmp_path):
    assert al._pouls_precedent(tmp_path / "jamais_ecrit.heartbeat") is None


def test_le_lecteur_de_pouls_rend_None_sur_json_casse(tmp_path):
    p = tmp_path / "casse.heartbeat"
    p.write_text("{ pas du json", encoding="utf-8")
    assert al._pouls_precedent(p) is None


def test_le_lecteur_relit_bien_un_pouls_valide(tmp_path):
    import json
    p = tmp_path / "ok.heartbeat"
    p.write_text(json.dumps(_pouls(pid=777)), encoding="utf-8")
    assert al._pouls_precedent(p)["pid"] == 777


# ── LE POULS PORTE LE TRAVAIL EN COURS ──────────────────────────────────────
@pytest.fixture()
def banc_tick(tmp_path, monkeypatch):
    """Tick ISOLE : pouls capture en memoire, base jetable, patterns remplaces.

    Sans le remplacement de `PATTERNS`, ce banc executerait les 23 routines
    reelles — dont des appels LLM et des clones.
    """
    import forge_heartbeat as fh
    ecrits: list = []

    def _capture(nom, **kw):
        ecrits.append(dict(kw))
        return True

    monkeypatch.setattr(fh, "beat_daemon", _capture)
    monkeypatch.setattr(al, "DB", tmp_path / "loops.db")
    monkeypatch.setattr(al, "_POULS_ETAT", {"patterns": 2, "interval_s": 60})
    return ecrits


def _pat(nom, fn):
    return al.Pattern(name=nom, fn=fn, interval_sec=0, description="banc")


def test_P1_current_pattern_est_ecrit_AVANT_l_appel(banc_tick, monkeypatch):
    """L'ecrire APRES laisserait le champ vide dans le seul cas qui compte :
    une mort PENDANT le pattern."""
    vu = {}

    def _fn():
        vu["au_moment_de_l_appel"] = dict(banc_tick[-1])
        return {"ok": 1}

    monkeypatch.setattr(al, "PATTERNS", {"pat_a": _pat("pat_a", _fn)})
    al.run_due_patterns(force=True)
    assert vu["au_moment_de_l_appel"]["current_pattern"] == "pat_a"
    assert vu["au_moment_de_l_appel"]["pattern_started_at"]


def test_P2_un_pattern_termine_renseigne_sa_duree(banc_tick, monkeypatch):
    monkeypatch.setattr(al, "PATTERNS", {"pat_a": _pat("pat_a", lambda: {"ok": 1})})
    al.run_due_patterns(force=True)
    fin = banc_tick[-1]
    assert fin["current_pattern"] is None
    assert fin["last_completed_pattern"] == "pat_a"
    assert fin["last_completed_at"]
    assert isinstance(fin["last_completed_duration_s"], float)


def test_P3_une_mort_PENDANT_le_pattern_laisse_son_nom(banc_tick, monkeypatch):
    """`SystemExit` traverse le `except Exception` : l'ecriture de fin n'a jamais
    lieu, exactement comme dans une mort reelle."""
    def _meurt():
        raise SystemExit(1)

    monkeypatch.setattr(al, "PATTERNS", {"pat_a": _pat("pat_a", _meurt)})
    with pytest.raises(SystemExit):
        al.run_due_patterns(force=True)
    dernier = banc_tick[-1]
    assert dernier["current_pattern"] == "pat_a"
    assert "last_completed_pattern" not in dernier


def test_P4_une_exception_ATTRAPEE_reste_un_retour(banc_tick, monkeypatch):
    """Terminer en erreur n'est pas mourir : le pattern a rendu la main."""
    def _rate():
        raise ValueError("boum")

    monkeypatch.setattr(al, "PATTERNS", {"pat_a": _pat("pat_a", _rate)})
    al.run_due_patterns(force=True)
    assert banc_tick[-1]["last_completed_pattern"] == "pat_a"
    assert banc_tick[-1]["current_pattern"] is None


def test_P8_deux_patterns_le_second_devient_courant_avant_son_appel(banc_tick,
                                                                   monkeypatch):
    vus = []

    def _f(nom):
        return lambda: vus.append(banc_tick[-1].get("current_pattern")) or {"ok": nom}

    monkeypatch.setattr(al, "PATTERNS", {"pat_a": _pat("pat_a", _f("a")),
                                         "pat_b": _pat("pat_b", _f("b"))})
    al.run_due_patterns(force=True)
    assert vus == ["pat_a", "pat_b"]
    assert banc_tick[-1]["last_completed_pattern"] == "pat_b"


def test_P9_hors_daemon_aucun_pouls_n_est_ecrit(tmp_path, monkeypatch):
    """`run_due_patterns` sert aussi au CLI et aux tests : y ecrire un pouls
    ferait croire au superviseur qu'un daemon tourne."""
    import forge_heartbeat as fh
    ecrits: list = []
    monkeypatch.setattr(fh, "beat_daemon", lambda nom, **kw: ecrits.append(kw) or True)
    monkeypatch.setattr(al, "DB", tmp_path / "loops.db")
    monkeypatch.setattr(al, "_POULS_ETAT", {})          # hors daemon
    monkeypatch.setattr(al, "PATTERNS", {"pat_a": _pat("pat_a", lambda: 1)})
    al.run_due_patterns(force=True)
    assert ecrits == []


# ── le scenario reel que l'instrument doit expliquer ────────────────────────
def test_BOUT_EN_BOUT_mort_dans_un_pattern_puis_reprise():
    """pouls current_pattern=A -> A meurt avant son retour -> nouveau demarrage
    -> RECOVERY + previous_current_pattern=A + duree calculee a la LECTURE."""
    pouls = {"ts": "2026-08-31T16:00:00", "pid": 13060, "patterns": 23,
             "interval_s": 60, "current_pattern": "veille_digest_auto",
             "pattern_started_at": "2026-08-31T15:58:30"}
    from datetime import datetime as D
    maintenant = D.fromisoformat("2026-08-31T16:04:30").timestamp()
    r = al.diagnostic_demarrage(pouls, 5804, 23, vivant=lambda p: False,
                                maintenant=maintenant)
    assert r["startup_reason"] == "RECOVERY"
    assert r["previous_current_pattern"] == "veille_digest_auto"
    assert r["previous_pattern_started_at"] == "2026-08-31T15:58:30"
    assert r["pattern_running_for_s"] == 360.0        # 15:58:30 -> 16:04:30
    assert "NON etablie" in r["detail"]


def test_aucun_pattern_en_cours_donne_une_duree_NULLE():
    """Rien en cours n'est pas une duree de zero : il n'y a pas de duree."""
    pouls = {"ts": "2026-08-31T16:00:00", "pid": 13060, "current_pattern": None}
    r = _diag(pouls, vivant=lambda p: False)
    assert r["previous_current_pattern"] is None
    assert r["pattern_running_for_s"] is None


@pytest.mark.parametrize("depart", [None, "", "pas une date", 42])
def test_un_depart_ILLISIBLE_donne_une_duree_NULLE_jamais_zero(depart):
    pouls = {"ts": "2026-08-31T16:00:00", "pid": 13060,
             "current_pattern": "pat_x", "pattern_started_at": depart}
    r = _diag(pouls, vivant=lambda p: False)
    assert r["previous_current_pattern"] == "pat_x"
    assert r["pattern_running_for_s"] is None


def test_compatibilite_les_champs_historiques_survivent():
    """Le diagnostic d'origine ne doit pas etre casse par l'enrichissement."""
    r = _diag(_pouls(pid=20148), vivant=lambda p: False)
    for c in ("pid", "patterns", "previous_pid", "previous_pulse",
              "previous_patterns", "gap_s", "startup_reason", "detail"):
        assert c in r


# ── UN DIAGNOSTIC NE DEPLACE PAS LE CALENDRIER DE PRODUCTION ────────────────
@pytest.fixture()
def base(tmp_path, monkeypatch):
    """Base d'etat des boucles ISOLEE."""
    monkeypatch.setattr(al, "DB", tmp_path / "loops.db")
    al._ensure_schema()
    return tmp_path / "loops.db"


def test_M1_un_tour_MANUEL_ne_repousse_pas_l_echeance(base):
    """MESURE 2026-08-31 : un `--run veille_github_head` lance a la main a
    repousse le passage suivant du daemon de 36 minutes, et la preuve autonome
    qu'on attendait avec."""
    al._log_run("pat_x", "ok", "tour programme")          # le daemon passe
    t0 = al._last_run("pat_x")
    assert t0 > 0
    al._log_run("pat_x", "ok", "tour manuel", programme=False)
    assert al._last_run("pat_x") == t0, "un tour manuel a deplace l'echeance"


def test_M2_deux_tours_manuels_ne_deplacent_toujours_rien(base):
    al._log_run("pat_x", "ok", "programme")
    t0 = al._last_run("pat_x")
    for _ in range(2):
        al._log_run("pat_x", "ok", "manuel", programme=False)
    assert al._last_run("pat_x") == t0


def test_M3_un_tour_PROGRAMME_deplace_bien_l_echeance(base):
    al._log_run("pat_x", "ok", "premier")
    t0 = al._last_run("pat_x")
    time.sleep(0.01)
    al._log_run("pat_x", "ok", "second")
    assert al._last_run("pat_x") > t0, "le daemon ne met plus son etat a jour"


def test_M4_le_manuel_TRACE_quand_meme(base):
    import json as _j
    import sqlite3
    al._log_run("pat_x", "ok", "sortie manuelle", {"n": 1}, programme=False)
    c = sqlite3.connect(str(al.DB))
    lignes = c.execute("SELECT outcome, details FROM autonomous_loop_audit "
                       "WHERE pattern='pat_x'").fetchall()
    c.close()
    assert len(lignes) == 1, "la trace de l'execution manuelle a disparu"
    assert lignes[0][0] == "sortie manuelle"
    d = _j.loads(lignes[0][1])
    assert d["declencheur"] == "manuel"
    assert d["n"] == 1, "les details d'origine ont ete perdus"


def test_M5_le_programme_est_marque_comme_tel(base):
    import json as _j
    import sqlite3
    al._log_run("pat_x", "ok", "sortie")
    c = sqlite3.connect(str(al.DB))
    d = _j.loads(c.execute("SELECT details FROM autonomous_loop_audit "
                           "WHERE pattern='pat_x'").fetchone()[0])
    c.close()
    assert d["declencheur"] == "programme"


def test_M6_un_manuel_sur_pattern_JAMAIS_vu_le_laisse_eligible(base):
    """`last_run` remis a 0 rendrait le pattern eligible immediatement — l'erreur
    inverse, et tout aussi fausse. Ici il n'a jamais tourne : 0 est le VRAI."""
    al._log_run("pat_neuf", "ok", "manuel", programme=False)
    assert al._last_run("pat_neuf") == 0.0


def test_M7_le_manuel_compte_quand_meme_dans_les_totaux(base):
    import sqlite3
    al._log_run("pat_x", "ok", "manuel", programme=False)
    c = sqlite3.connect(str(al.DB))
    n = c.execute("SELECT runs_total FROM autonomous_loop_state "
                  "WHERE pattern='pat_x'").fetchone()[0]
    c.close()
    assert n == 1, "l'execution manuelle a disparu des compteurs"


def test_M8_LE_TEST_CENTRAL_eligibilite_inchangee_apres_un_manuel(base,
                                                                  monkeypatch):
    """last_run = T0 -> `--run` -> last_run daemon = T0 -> le pattern reste du."""
    passages: list = []
    monkeypatch.setattr(al, "PATTERNS", {"pat_x": al.Pattern(
        name="pat_x", fn=lambda: passages.append(1) or {"ok": 1},
        interval_sec=3600, description="banc")})
    monkeypatch.setattr(al, "_POULS_ETAT", {})
    al._log_run("pat_x", "ok", "programme il y a longtemps")
    import sqlite3
    c = sqlite3.connect(str(al.DB))
    c.execute("UPDATE autonomous_loop_state SET last_run=? WHERE pattern='pat_x'",
              (time.time() - 7200,))           # du depuis 1 h
    c.commit(); c.close()
    t0 = al._last_run("pat_x")
    al._log_run("pat_x", "ok", "manuel", programme=False)
    assert al._last_run("pat_x") == t0
    assert al.run_due_patterns() and passages == [1], \
        "le pattern n'est plus eligible apres un tour manuel"


# ── le contrat global : aucun motif n'affirme une cause ─────────────────────
def test_AUCUN_motif_ne_pretend_connaitre_la_cause_de_la_mort():
    cas = [(None, lambda p: False), (_pouls(pid=1), lambda p: False),
           (_pouls(pid=1), lambda p: True), (_pouls(pid=1), lambda p: None),
           (_pouls(pid=13060), lambda p: True)]
    interdits = ("crash", "oom", "tue", "killed", "exception", "segfault")
    for pouls, vivant in cas:
        r = _diag(pouls, vivant=vivant)
        detail = r["detail"].lower()
        for mot in interdits:
            assert mot not in detail, "%s affirme une cause : %s" % (
                r["startup_reason"], r["detail"])
        assert r["startup_reason"] in {"NEW_START", "SAME_PID", "RECOVERY",
                                       "OVERLAP_SUSPECTED", "INDETERMINE"}
