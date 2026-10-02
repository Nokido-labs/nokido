"""NR -- soif, lot B (2026-10-02) : aveuglement, cycle de vie des lacunes, plafond, etalonnage.

Note soif du 01/10 (§2-§3), SSoT bb:soif_lot_b_2026-10-02. Chaque etat a son cas qui DOIT
echouer par garde, et tout passe par le chemin REEL (coverage_dense, feel_gap, _propose_gap,
run_once du demon). Hermetique : faux services HTTP, base sqlite temporaire, registres sous
tmp -- jamais sandbox/ reel, aucune ecriture dans rag_chunks ni rag_fts.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_db_path as fdb  # noqa: E402
from nokido_agent.app import forge_epistemic_veille as ev  # noqa: E402
from nokido_agent.app import forge_memory_availability as fma  # noqa: E402


# ── faux services ─────────────────────────────────────────────────────────────────────
class _Rep:
    def __init__(self, d):
        self.d = d

    def read(self):
        return json.dumps(self.d).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _services(score):
    def urlopen(req, timeout=None):
        url = req.full_url
        if ":8099/" in url:
            return _Rep({"data": [{"embedding": [0.1, 0.2]}]})
        if ":6333/" in url:
            return _Rep({"result": [{"payload": {"chunk_id": "c1"}}]})
        if ":8100/" in url:
            return _Rep({"results": [{"relevance_score": score}]})
        raise AssertionError("appel inattendu : %s" % url)
    return urlopen


def _snap(fraction=None, frais=True):
    if fraction is None:
        return {"frais": False, "vector_pending": None, "raison": "perime"}
    return {"frais": frais, "vector_pending": int(fraction * 1000), "total": 1000}


@pytest.fixture
def soif(tmp_path, monkeypatch):
    db = tmp_path / "rag.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT)")
    c.execute("INSERT INTO rag_chunks VALUES ('c1', 'un texte de corpus')")
    # Report sur alpha (2026-10-02) : la branche lexicale du lot A (b09d2d87c) interroge
    # rag_chunks_fts ; sans cette table elle echoue et l'instrument s'ABSTIENT
    # (aveugle_lexical_abstention, 75a539562) avant tout jugement d'aveuglement partiel.
    c.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text)")
    c.execute("INSERT INTO rag_chunks_fts(rowid, text) VALUES (1, 'un texte de corpus')")
    c.commit()
    c.close()
    monkeypatch.setattr(fdb, "db_path", lambda *a, **k: db)
    monkeypatch.setattr(ev, "manifold_error", lambda v: 0.1)          # sur la variete
    monkeypatch.setattr(ev, "LACUNES", tmp_path / "soif_lacunes.json")
    monkeypatch.setattr(fma, "snapshot", lambda *a, **k: _snap(0.0))
    return tmp_path


def _mesure(monkeypatch, score, fraction=0.0, frais=True):
    monkeypatch.setattr("urllib.request.urlopen", _services(score))
    monkeypatch.setattr(fma, "snapshot", lambda *a, **k: _snap(fraction, frais))
    return ev.coverage_dense("comment fonctionne le coffre DPAPI de nokido")


# ── 1. AVEUGLE_PARTIEL ────────────────────────────────────────────────────────────────
def test_instrument_qui_voit_declare_le_gap_et_se_signe(soif, monkeypatch):
    cov = _mesure(monkeypatch, -6.0, fraction=0.001)
    assert cov["gap"] is True and cov["verdict"] == "gap_certain"
    assert cov["instrument"] == ev.INSTRUMENT_DENSE and "floor=" in cov["instrument"]


def test_aveugle_partiel_ni_gap_ni_couvert_et_fraction_dite(soif, monkeypatch):
    cov = _mesure(monkeypatch, -6.0, fraction=0.3)
    assert cov["gap"] is None and cov["verdict"] == "aveugle_partiel"
    assert cov["fraction_sans_vecteur"] == 0.3 and cov["verdict_instrument"] == "gap_certain"
    zone_grise = _mesure(monkeypatch, -2.0, fraction=0.3)
    assert zone_grise["verdict"] == "aveugle_partiel" and zone_grise["gap"] is None


def test_aveuglement_inconnu_n_est_pas_une_lacune(soif, monkeypatch):
    cov = _mesure(monkeypatch, -6.0, fraction=None)                     # snapshot perime
    assert cov["gap"] is None and cov["verdict"] == "aveuglement_inconnu_abstention"


def test_couvert_reste_couvert_meme_avec_des_vecteurs_manquants(soif, monkeypatch):
    cov = _mesure(monkeypatch, 2.0, fraction=0.3)
    assert cov["gap"] is False and cov["verdict"] == "couvert"


# ── 2. feel_gap : la mesure fait foi, une panne n'est pas une lacune ─────────────────
@pytest.fixture
def ressentis(monkeypatch):
    from nokido_agent.app import forge_critical_events as ce
    from nokido_agent.app import forge_endocrine as en
    vus = []
    monkeypatch.setattr(ce, "persist", lambda kind, sev, payload=None: vus.append((kind, sev)) or 1)
    monkeypatch.setattr(en, "release", lambda *a, **k: None)
    return vus


def test_feel_gap_ressent_un_gap_mesure_et_pas_un_aveugle(soif, monkeypatch, ressentis):
    gap = _mesure(monkeypatch, -6.0, fraction=0.0)
    assert ev.feel_gap("reference", "q", cov=gap)["felt"] is True
    aveugle = _mesure(monkeypatch, -6.0, fraction=0.3)
    assert ev.feel_gap("reference", "q", cov=aveugle)["felt"] is False
    assert len(ressentis) == 1


def test_feel_gap_rag_en_panne_ne_ressent_rien(soif, monkeypatch, ressentis):
    # Faux module, sans importer le vrai : l'importer ici le figerait dans sys.modules pour
    # les tests suivants (test_epistemic_veille isole sa panne par le meme moyen).
    import types

    def _panne(*a, **k):
        raise ConnectionError("RAG muet")
    faux = types.ModuleType("forge_self_correction")
    faux.preflight_check_verbose = _panne
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_self_correction", faux)
    r = ev.feel_gap("reference", "q")
    assert r["felt"] is False and r["gap"] is None and ressentis == []


# ── 3. cycle de vie d'une lacune ──────────────────────────────────────────────────────
def _gap(score=-6.0, instrument=None):
    return {"ok": True, "gap": True, "score": score, "verdict": "gap_certain",
            "instrument": instrument or ev.INSTRUMENT_DENSE}


def _couvert(instrument=None):
    return {"ok": True, "gap": False, "score": 2.0, "verdict": "couvert",
            "instrument": instrument or ev.INSTRUMENT_DENSE}


def test_ouverture_refusee_sans_gap_sans_instrument_ou_aveugle(soif):
    assert ev.ouvrir_lacune("q", _couvert())["ok"] is False
    assert ev.ouvrir_lacune("q", dict(_gap(), instrument=None))["ok"] is False
    assert ev.ouvrir_lacune("q", dict(_gap(), gap=None, verdict="aveugle_partiel"),
                            motif="rang_intention")["ok"] is False
    assert ev.ouvrir_lacune("q", _gap(), motif="inventé")["ok"] is False
    assert not ev.LACUNES.exists()


def test_fermeture_seulement_par_remesure_du_meme_instrument(soif):
    k = ev.ouvrir_lacune("q", _gap())["cle"]
    autre = ev.remesurer_lacune(k, _couvert(instrument="coverage_dense|floor=-9.0|ceil=1.0"))
    assert autre["ok"] is False and ev.lire_lacunes()[k]["etat"] == ev.OUVERTE
    r = ev.remesurer_lacune(k, _couvert())
    assert r["etat"] == ev.FERMEE_PAR_REMESURE and r["avant"] == -6.0 and r["apres"] == 2.0
    assert ev.remesurer_lacune(k, _couvert())["ok"] is False      # deja fermee
    rouverte = ev.ouvrir_lacune("q", _gap(-5.5))
    lac = ev.lire_lacunes()[k]
    assert rouverte["etat"] == ev.OUVERTE and [e["evenement"] for e in lac["historique"]][:3] == [
        "ouverte", "remesure_refusee", "fermee"]


def test_panne_et_aveuglement_ne_comptent_pas_comme_remesure(soif):
    k = ev.ouvrir_lacune("q", _gap())["cle"]
    ev.remesurer_lacune(k, {"ok": False, "dependance": "reranker :8100",
                            "instrument": ev.INSTRUMENT_DENSE})
    ev.remesurer_lacune(k, dict(_gap(), gap=None, verdict="aveugle_partiel"))
    assert ev.lire_lacunes()[k]["remesures_sans_effet"] == 0


def test_irresolue_jamais_automatique_seulement_par_l_owner(soif):
    k = ev.ouvrir_lacune("q", _gap())["cle"]
    for _ in range(ev.REMESURES_AVANT_PROPOSITION + 4):
        r = ev.remesurer_lacune(k, _gap())
    assert r["irresolution_proposee"] is True and ev.lire_lacunes()[k]["etat"] == ev.OUVERTE
    assert ev.declarer_irresolue(k, par="EPISTEMIC_DAEMON", motif="x")["ok"] is False
    assert ev.declarer_irresolue(k, par=ev.OWNER, motif="  ")["ok"] is False
    assert ev.declarer_irresolue(k, par=ev.OWNER, motif="hors perimetre")["etat"] == ev.IRRESOLUE


# ── 4. le demon, par son chemin reel ──────────────────────────────────────────────────
def _demon():
    spec = importlib.util.spec_from_file_location("demon_soif_lot_b",
                                                  RACINE / "tools" / "forge_epistemic_daemon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def demon(soif, monkeypatch, ressentis):
    from nokido_agent.app import forge_active_inference as fai
    from nokido_agent.app import forge_swarm_blackboard as bb
    d = _demon()
    faits, journal = [], []

    async def _fait(*a, **k):
        faits.append((a, k))
        return {"ok": True}
    monkeypatch.setattr(bb, "apply_fact", _fait)
    monkeypatch.setattr(fai, "observe_signal", lambda *a, **k: None)
    monkeypatch.setattr(d, "_journal", journal.append)
    monkeypatch.setattr(d, "_interoceptive_split", lambda limit=8: {"soif": [], "soin": []})
    monkeypatch.setattr(d, "_intentional_split", lambda limit=6: ["Nokido vise : le jalon X"])
    monkeypatch.setattr(d, "_decision_examen", lambda besoin: "nr")
    monkeypatch.setattr(d, "_reveiller_piliers", lambda attente_s=None: (True, "nr"))
    monkeypatch.setattr(d, "_manque_interne", lambda q: ["forge_x"])   # interne : pas de veille
    monkeypatch.setattr(d, "_marque_dernier_examen", lambda: soif / "dernier_examen")
    monkeypatch.setattr(d, "_demande_manuelle", lambda: soif / "examen.wanted")
    cx = sqlite3.connect(":memory:")
    cx.execute("CREATE TABLE query_log (query_text TEXT, timestamp REAL)")
    return d, cx, faits, journal


def _cov_fixe(monkeypatch, cov):
    monkeypatch.setattr(ev, "coverage_dense", lambda q: dict(cov))


def test_cycle_ouvre_puis_ferme_par_remesure(demon, monkeypatch):
    d, cx, faits, journal = demon
    _cov_fixe(monkeypatch, {"ok": True, "gap": None, "score": -3.0,
                            "verdict": "indetermine_abstention", "instrument": ev.INSTRUMENT_DENSE})
    r1 = d.run_once(cx)
    assert r1["intention_gap"]["lacune"]["etat"] == ev.OUVERTE
    (k,) = ev.lire_lacunes()
    _cov_fixe(monkeypatch, _couvert())
    monkeypatch.setattr(d, "REMESURE_DELAI_S", 0.0)
    r2 = d.run_once(cx)
    assert r2["lacunes"]["fermees"] == 1 and ev.lire_lacunes()[k]["etat"] == ev.FERMEE_PAR_REMESURE


def test_cycle_aveugle_ni_lacune_ni_veille(demon, monkeypatch):
    d, cx, faits, journal = demon
    _cov_fixe(monkeypatch, {"ok": True, "gap": None, "score": -3.0, "verdict": "aveugle_partiel",
                            "fraction_sans_vecteur": 0.3, "instrument": ev.INSTRUMENT_DENSE})
    r = d.run_once(cx)
    assert r["intention_gap"]["traitement"] == "SOIN_INSTRUMENT" and r["veilles"] == 0
    assert not ev.LACUNES.exists() and faits == []


def test_cycles_repetes_ne_prononcent_jamais_irresolue(demon, monkeypatch):
    d, cx, faits, journal = demon
    _cov_fixe(monkeypatch, {"ok": True, "gap": None, "score": -3.0,
                            "verdict": "indetermine_abstention", "instrument": ev.INSTRUMENT_DENSE})
    monkeypatch.setattr(d, "REMESURE_DELAI_S", 0.0)
    for _ in range(8):
        r = d.run_once(cx)
    (lac,) = ev.lire_lacunes().values()
    assert lac["etat"] == ev.OUVERTE and lac["irresolution_proposee"] is True
    assert r["lacunes"]["irresolution_proposee"]


# ── 5. plafond algedonique par FENETRE ────────────────────────────────────────────────
@pytest.fixture
def douleurs(demon, monkeypatch):
    d, cx, faits, journal = demon
    from nokido_agent.app import forge_critical_events as ce
    tirs = []
    monkeypatch.setattr(ce, "persist", lambda kind, sev, payload=None: tirs.append(sev) or 1)
    monkeypatch.setattr(d, "TIRS_ALGEDONIQUES", Path(str(ev.LACUNES)).parent / "tirs.json")
    horloge = {"t": 1_000_000.0}
    monkeypatch.setattr(d.time, "time", lambda: horloge["t"])
    return d, tirs, faits, horloge


def _douleur(i):
    return {"fault": "plaie %d" % i, "cycles": 5, "sig": "s%d" % i, "severity": "high"}


def test_plafond_par_fenetre_puis_voie_lente(douleurs):
    d, tirs, faits, horloge = douleurs
    for i in range(5):
        d._propose_care(_douleur(i))
    assert len(tirs) == d.PLAFOND_TIRS                         # canal rapide plafonne
    # Report sur alpha (2026-10-02) : depuis le lot A, la VOIE LENTE porte TOUTES les douleurs,
    # graves comprises (son seul consommateur lit le tableau noir) ; les plafonnees y portent
    # le motif du plafond, les autres non.
    lents = [a[1] for a, k in faits]
    assert len(lents) == 5
    plafonnees = [t for t in lents if "plafond algedonique" in t]
    assert len(plafonnees) == 5 - d.PLAFOND_TIRS
    horloge["t"] += d.FENETRE_TIRS_S + 1                       # la fenetre a passe
    d._propose_care(_douleur(9))
    assert len(tirs) == d.PLAFOND_TIRS + 1


def test_un_historique_ancien_ne_bloque_pas_le_present(douleurs):
    d, tirs, faits, horloge = douleurs
    d.TIRS_ALGEDONIQUES.write_text(json.dumps({"tirs": [{"ts": 1.0, "sig": "v", "sev": "high"}] * 100}),
                                   encoding="utf-8")
    d._propose_care(_douleur(1))
    assert tirs == ["high"]


def test_registre_des_tirs_illisible_voie_lente_et_dit(douleurs):
    d, tirs, faits, horloge = douleurs
    d.TIRS_ALGEDONIQUES.write_text("{pas du json", encoding="utf-8")
    d._propose_care(_douleur(1))
    assert tirs == [] and "illisible" in faits[0][0][1]


# ── 6. etalonnage gele et hache ───────────────────────────────────────────────────────
def test_le_jeu_livre_est_intact_et_crlf_ne_change_rien(tmp_path):
    assert ev.charger_etalonnage()["ok"] is True
    crlf = tmp_path / "crlf.json"
    crlf.write_bytes(ev.ETALONNAGE.read_bytes().replace(b"\n", b"\r\n"))
    assert ev.charger_etalonnage(crlf)["ok"] is True


def test_un_jeu_modifie_est_refuse_et_l_instrument_jamais_appele(tmp_path):
    altere = tmp_path / "altere.json"
    altere.write_text(ev.ETALONNAGE.read_text(encoding="utf-8").replace("blanquette", "quiche"),
                      encoding="utf-8")
    appels = []
    r = ev.etalonner(instrument=lambda q: appels.append(q) or {}, chemin=altere)
    assert r["ok"] is False and r["verdict"] == "ETALONNAGE_ALTERE" and appels == []


def test_etalonnage_compte_les_faux_gaps():
    def instrument(q):
        return {"ok": True, "gap": "alpagas" in q, "verdict": "gap_certain" if "alpagas" in q
                else "couvert"}
    r = ev.etalonner(instrument=instrument)
    assert r["ok"] is True and r["faux_gaps"] == ["H02"] and r["mesurees"] == 18
    assert r["taux_faux_gap"] == round(1 / 18, 4)
