# -*- coding: utf-8 -*-
"""NR levier A (owner 23/10) : modele ET effort fixes par taille S|M|L, pour chaque surface de la facade
(claude, agy, vibe, opencode), depuis UNE table (tools/forge_palier_effort.py).

Regles : table lue ; taille inconnue refusee ; modele a 0 req/min au census refuse (jamais tente) ; effort HAUT
jamais par defaut, seulement sur escalade apres echec VERIFIE (nr_rouge | juge) ; drapeau d'effort absent de l'aide
= UNKNOWN journalise, pas d'invention. Aucun CLI reel, aucun secret.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_palier_effort as P  # noqa: E402
import forge_task_executor as T  # noqa: E402
import nokido_headless as H  # noqa: E402

SURFACES = ("claude", "agy", "vibe", "opencode")
HAUTS = ("high", "xhigh", "max")
ABSENT = Path("absent.json")


def _census(tmp_path, verdicts):
    p = tmp_path / "census.json"
    p.write_text(json.dumps({"verdicts": verdicts}), encoding="utf-8")
    return p


def test_la_table_couvre_chaque_surface_et_chaque_taille():
    for s in SURFACES:
        for t in ("S", "M", "L"):
            r = P.resoudre(s, t, census=ABSENT)
            assert set(r) >= {"surface", "taille", "modele", "effort", "drapeau_effort", "inconnu"}
            assert r["surface"] == s and r["taille"] == t


def test_aucun_effort_haut_par_defaut():
    for s in SURFACES:
        for t in ("S", "M", "L"):
            assert P.resoudre(s, t, census=ABSENT)["effort"] not in HAUTS


def test_principe_S_bas_M_bas_ou_moyen_L_moyen_quand_le_drapeau_existe():
    r = {t: P.resoudre("claude", t, census=ABSENT)["effort"] for t in "SML"}
    assert r["S"] == "low" and r["M"] in ("low", "medium") and r["L"] == "medium"


def test_taille_inconnue_refusee():
    for mauvaise in ("XL", "x", "0"):
        with pytest.raises(ValueError):
            P.resoudre("claude", mauvaise, census=ABSENT)


def test_surface_inconnue_refusee():
    with pytest.raises(ValueError):
        P.resoudre("gemini", "M", census=ABSENT)


def test_modele_a_zero_requete_minute_refuse_jamais_tente(tmp_path):
    modele = P.resoudre("claude", "M", census=ABSENT)["modele"]
    cle = "%s:%s" % (P.FOURNISSEUR["claude"], modele)
    c = _census(tmp_path, {cle: {"joignable": False, "motif": "HTTP 429",
                                 "limites": {"x-ratelimit-limit-req-minute": "0"}}})
    with pytest.raises(P.ModeleHorsQuota) as e:
        P.resoudre("claude", "M", census=c)
    assert "0 req/min" in str(e.value)


def test_census_muet_n_est_pas_un_refus(tmp_path):
    assert P.resoudre("claude", "M", census=_census(tmp_path, {}))["modele"]


def test_effort_haut_sans_escalade_refuse():
    for e in HAUTS:
        with pytest.raises(ValueError):
            P.resoudre("claude", "L", effort=e, census=ABSENT)


def test_escalade_exige_une_preuve_verifiee():
    with pytest.raises(ValueError):
        P.resoudre("claude", "L", escalade="parce_que", census=ABSENT)
    for preuve in ("nr_rouge", "juge"):
        assert P.resoudre("claude", "L", escalade=preuve, census=ABSENT)["effort"] == "high"


def test_escalade_dans_les_limites_du_drapeau_agy_low_high():
    assert P.resoudre("agy", "M", escalade="juge", census=ABSENT)["effort"] == "high"
    # 31/10 : `medium` n'est plus refuse -- aide agy RELUE le 30/10 (--effort low|medium|high|xhigh|max) et L pose
    # gemini-3.8-flash-medium (48f4d6274) dont EFFORTS_SUPPORTES admet medium (22909ef1f) ; jamais un effort HAUT.
    r = P.resoudre("agy", "L", census=ABSENT)
    assert r["effort"] == "medium" and r["effort"] not in HAUTS


def test_drapeau_absent_est_unknown_journalise_pas_invente(caplog):
    for s in ("vibe", "opencode"):
        with caplog.at_level("WARNING"):
            r = P.resoudre(s, "L", census=ABSENT)
        assert r["drapeau_effort"] is None and r["effort"] is None and r["inconnu"]
        assert "UNKNOWN" in caplog.text
        with pytest.raises(ValueError):       # pas d'escalade possible sur un drapeau inconnu
            P.resoudre(s, "L", escalade="juge", census=ABSENT)


def test_drapeaux_lus_dans_l_aide():
    assert P.DRAPEAUX_LUS["claude"]["drapeau"] == "--effort"
    assert P.DRAPEAUX_LUS["claude"]["commande_aide"] == "claude --help"
    assert P.DRAPEAUX_LUS["agy"]["drapeau"] == "--effort"
    assert P.DRAPEAUX_LUS["vibe"]["drapeau"] is None and P.DRAPEAUX_LUS["opencode"]["drapeau"] is None


def test_une_seule_table_l_executeur_la_consomme():
    for t in "SML":
        assert T._MODELE_CLAUDE_PAR_TAILLE[t] == P.resoudre("claude", t, census=ABSENT)["modele"]
    assert (P.FOURNISSEUR["vibe"], P.resoudre("vibe", "M", census=ABSENT)["modele"]) == T._MODELE_VIBE


@pytest.mark.parametrize("taille", ["S", "M", "L"])
def test_args_claude_porte_l_effort_de_la_table(taille):
    args = T._args_claude(Path("C:/wt"), taille)
    voulu = P.resoudre("claude", taille, census=ABSENT)["effort"]
    assert args[args.index("--effort") + 1] == voulu


def test_args_claude_escalade():
    args = T._args_claude(Path("C:/wt"), "L", escalade="nr_rouge")
    assert args[args.index("--effort") + 1] == "high"


def test_facade_agy_effort_de_la_table_pas_de_l_env(monkeypatch):
    monkeypatch.setenv("LAFORGE_AGY_EFFORT", "high")
    plan = H._construire("agy", "p", "f", ".", "X", "M")
    assert plan["args"][plan["args"].index("--effort") + 1] == "low"
    plan = H._construire("agy", "p", "f", ".", "X", "M", "juge")
    assert plan["args"][plan["args"].index("--effort") + 1] == "high"


def test_facade_claude_effort_et_modele():
    plan = H._construire("claude", "p", "f", ".", "X", "S")
    try:
        a = plan["args"]
        assert a[a.index("--effort") + 1] == "low"
        assert a[a.index("--model") + 1] == T._MODELE_CLAUDE_PAR_TAILLE["S"]
    finally:
        for d in plan["nettoyage"]:
            shutil.rmtree(d, ignore_errors=True)


def test_facade_refuse_une_escalade_sans_preuve():
    with pytest.raises(ValueError):
        H.lancer("agy", __file__, "X", ".", 1, "M", "au_pif")
