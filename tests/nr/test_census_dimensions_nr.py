"""NR (RED) -- le census porte par `fournisseur:modele` des dimensions MESUREES et DISTINCTES (owner 23/10).

« calibrer l'effort et la force/specialite des modeles appeles ; le census doit mesurer ces distinctions ».
Trois dimensions, jamais melangees : specialite (code, raisonnement, outils, vision, voix), force PAR specialite
(mini-banc deterministe, juge non-LLM), effet de l'effort (meme tache a efforts differents : cout, latence, reussite).
Chaque dimension : date, echantillon, etat OBSERVE | DECLARE | UNKNOWN. Une valeur declaree par le fournisseur n'est
PAS une mesure : elle ne devient jamais OBSERVE sans echantillon. Hors ligne, le census ne fabrique pas un echec.
Rapport : sandbox/workspace/rapport_calibration_effort_census_20261023.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_free_tier_census as C  # noqa: E402

SPECIALITES = ("code", "raisonnement", "outils", "vision", "voix")
T0 = "2026-10-23T10:00:00"


def _obs(valeur=0.75, n=12, juge="deterministe", quand=T0, spec="code"):
    return {"force": {spec: {"valeur": valeur, "echantillon": n, "juge": juge, "mesure_le": quand}}}


def test_constantes_du_schema():
    assert C.SPECIALITES == SPECIALITES
    assert C.ETATS_DIMENSION == ("OBSERVE", "DECLARE", "UNKNOWN")


def test_dimension_observee_exige_date_et_echantillon():
    d = C.dimension("OBSERVE", valeur=0.8, mesure_le=T0, echantillon=12)
    assert d == {"etat": "OBSERVE", "valeur": 0.8, "mesure_le": T0, "echantillon": 12, "source": None}
    for manque in ({"mesure_le": None}, {"echantillon": 0}, {"valeur": None}):
        args = {"valeur": 0.8, "mesure_le": T0, "echantillon": 12, **manque}
        with pytest.raises(ValueError):
            C.dimension("OBSERVE", **args)


def test_dimension_declaree_n_est_pas_une_mesure():
    d = C.dimension("DECLARE", valeur=True, source="forge_provider_specs.capabilities")
    assert d["etat"] == "DECLARE" and d["echantillon"] == 0 and d["mesure_le"] is None
    with pytest.raises(ValueError):                      # un declare ne cite pas d'echantillon : ce serait une mesure
        C.dimension("DECLARE", valeur=True, source="x", echantillon=5)
    with pytest.raises(ValueError):                      # un declare sans source n'est pas tracable
        C.dimension("DECLARE", valeur=True)


def test_dimension_inconnue_ne_porte_aucune_valeur():
    assert C.dimension("UNKNOWN")["valeur"] is None
    with pytest.raises(ValueError):
        C.dimension("UNKNOWN", valeur=0.5)
    with pytest.raises(ValueError):
        C.dimension("PROBABLE")                          # etat hors liste blanche


def test_fiche_vierge_est_unknown_partout_et_distincte_par_dimension():
    f = C.fiche_dimensions()
    assert tuple(f["specialite"]) == SPECIALITES and tuple(f["force"]) == SPECIALITES
    assert all(v["etat"] == "UNKNOWN" for v in f["specialite"].values())
    assert all(v["etat"] == "UNKNOWN" for v in f["force"].values())
    assert f["effort"]["etat"] == "UNKNOWN" and f["effort"]["niveaux"] == {}


def test_declare_ne_promeut_jamais_en_observe():
    f = C.fiche_dimensions(declare={"specialite": {"vision": "forge_provider_specs.capabilities"}})
    assert f["specialite"]["vision"]["etat"] == "DECLARE"
    assert f["force"]["vision"]["etat"] == "UNKNOWN"     # declarer une specialite ne dit rien de sa FORCE
    with pytest.raises(ValueError):
        C.fiche_dimensions(declare={"specialite": {"telepathie": "x"}})


def test_force_mesuree_exige_un_juge_deterministe():
    f = C.fiche_dimensions(observes=_obs())
    assert f["force"]["code"]["etat"] == "OBSERVE" and f["force"]["code"]["valeur"] == 0.75
    assert f["specialite"]["code"]["etat"] == "OBSERVE"  # une force mesuree PROUVE la specialite exercee
    with pytest.raises(ValueError):                      # juge LLM = pas un banc deterministe
        C.fiche_dimensions(observes=_obs(juge="llm"))


def test_effet_effort_compare_les_efforts_sur_la_meme_tache():
    mesures = [
        {"tache": "t1", "effort": "low", "cout_usd": 0.02, "latence_ms": 9000, "reussi": False},
        {"tache": "t1", "effort": "low", "cout_usd": 0.03, "latence_ms": 11000, "reussi": True},
        {"tache": "t1", "effort": "high", "cout_usd": 0.10, "latence_ms": 40000, "reussi": True},
        {"tache": "t1", "effort": "high", "cout_usd": 0.12, "latence_ms": 44000, "reussi": True},
    ]
    e = C.effet_effort(mesures, mesure_le=T0)
    assert e["etat"] == "OBSERVE" and e["echantillon"] == 4
    low = e["niveaux"]["low"]
    assert (low["n"], low["latence_ms_mediane"], low["taux_reussite"]) == (2, 10000, 0.5)
    assert low["cout_usd_moyen"] == pytest.approx(0.025)
    assert e["niveaux"]["high"]["taux_reussite"] == 1.0 and e["niveaux"]["high"]["n"] == 2


def test_effet_effort_un_seul_niveau_ne_compare_rien():
    e = C.effet_effort([{"tache": "t", "effort": "low", "cout_usd": None, "latence_ms": 5, "reussi": True}],
                       mesure_le=T0)
    assert e["etat"] == "UNKNOWN" and "comparer" in e["raison"]      # 1 niveau : aucun effet mesurable
    assert C.effet_effort([], mesure_le=T0)["etat"] == "UNKNOWN"


def test_cout_inconnu_reste_inconnu_dans_la_moyenne():
    m = [{"tache": "t", "effort": "low", "cout_usd": None, "latence_ms": 1, "reussi": True},
         {"tache": "t", "effort": "low", "cout_usd": 0.04, "latence_ms": 3, "reussi": True},
         {"tache": "t", "effort": "high", "cout_usd": None, "latence_ms": 9, "reussi": True}]
    n = C.effet_effort(m, mesure_le=T0)["niveaux"]
    assert n["low"]["cout_usd_moyen"] == 0.04          # moyenne des couts CONNUS seulement (jamais 0 fabrique)
    assert n["high"]["cout_usd_moyen"] is None


def test_consigner_dimensions_garde_le_verdict_joignable_et_remplace_la_mesure():
    reg = {"verdicts": {"groq:m": {"joignable": True, "mesure_le": "2026-10-21T00:00:00"}}}
    out = C.consigner_dimensions({"groq:m": C.fiche_dimensions(observes=_obs(1.0, 3))}, reg)
    assert out["verdicts"]["groq:m"]["joignable"] is True
    assert out["verdicts"]["groq:m"]["dimensions"]["force"]["code"]["valeur"] == 1.0
    neuf = C.fiche_dimensions(observes=_obs(0.5, 3, quand="2026-10-24T10:00:00"))
    out2 = C.consigner_dimensions({"groq:m": neuf}, out)
    assert out2["verdicts"]["groq:m"]["dimensions"]["force"]["code"]["valeur"] == 0.5


def test_une_dimension_unknown_n_ecrase_pas_une_mesure_anterieure():
    reg = C.consigner_dimensions({"groq:m": C.fiche_dimensions(observes=_obs(1.0, 3))}, {})
    reg = C.consigner_dimensions({"groq:m": C.fiche_dimensions()}, reg)      # passe sans banc : UNKNOWN != NO
    assert reg["verdicts"]["groq:m"]["dimensions"]["force"]["code"]["etat"] == "OBSERVE"


def test_hors_ligne_le_census_dimensions_ne_fabrique_rien():
    r = C.passe_dimensions([("groq", "m")], en_ligne=lambda: False)
    assert r == {"etat": "HORS_LIGNE", "resultats": {}}, r           # pas de faux URLError, aucun verdict ecrit
    avant = {"verdicts": {"a:b": {"joignable": True}}}
    assert C.consigner_dimensions(r["resultats"], avant) == avant


def test_plan_des_bancs_couvre_chaque_specialite_avec_un_juge_deterministe():
    assert tuple(C.BANCS) == SPECIALITES + ("effort",)
    for nom, b in C.BANCS.items():
        assert b["juge"] == "deterministe", nom
        assert b["items"] >= 1 and b["tokens_entree"] > 0, nom
    assert C.BANCS["effort"]["repetitions"] >= 3                     # 1 essai ne mesure pas une variance


def test_cout_estime_d_un_banc_est_dit_estimation_et_zero_en_palier_gratuit():
    e = C.cout_estime_banc("code", prix_entree_usd_mtok=0.0, prix_sortie_usd_mtok=0.0)
    assert e["usd"] == 0.0 and e["appels"] == C.BANCS["code"]["items"] and e["nature"] == "ESTIMATION"
    p = C.cout_estime_banc("code", prix_entree_usd_mtok=3.0, prix_sortie_usd_mtok=15.0)
    b = C.BANCS["code"]
    attendu = b["items"] * (b["tokens_entree"] * 3.0 + b["tokens_sortie"] * 15.0) / 1e6
    assert p["usd"] == pytest.approx(attendu)
    assert C.cout_estime_banc("code", None, None)["usd"] is None      # prix inconnu : cout inconnu, jamais 0


def test_registre_unifie_porte_les_dimensions_par_surface():
    census = {"horodatage": T0, "fournisseurs": [],
              "verdicts": {"groq:m": {"joignable": True, "mesure_le": T0,
                                      "dimensions": C.fiche_dimensions(declare={"specialite": {"code": "specs"}})}}}
    (s,) = C.registre_unifie(census, {})["surfaces"]
    assert s["dimensions"]["specialite"]["code"]["etat"] == "DECLARE"
    assert s["dimensions"]["force"]["code"]["etat"] == "UNKNOWN"
    census["verdicts"]["groq:m"].pop("dimensions")
    (s2,) = C.registre_unifie(census, {})["surfaces"]
    assert s2["dimensions"]["effort"]["etat"] == "UNKNOWN"           # surface sans dimensions : UNKNOWN, pas absente
