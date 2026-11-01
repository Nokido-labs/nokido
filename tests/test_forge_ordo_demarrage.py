"""NR de tools/forge_ordo_demarrage.py -- ordonnancement CP-SAT du demarrage sous budget RAM.

Donnees FACTICES uniquement (aucun journal reel, aucune base). Le solveur CP-SAT est lance
dans un sous-processus sous LAFORGE_PYTHON (Python 3.12 + OR-tools) : sous 3.14, OR-tools
plante en access violation (mesure 27/10), ce qui tuerait pytest lui-meme.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
OUTIL = RACINE / "tools" / "forge_ordo_demarrage.py"
sys.path.insert(0, str(RACINE / "tools"))

import forge_ordo_demarrage as fod  # noqa: E402

LAFORGE_PYTHON = os.environ.get("LAFORGE_PYTHON", "%USERPROFILE%/miniforge3/python.exe")

S = "[SUPERVISOR]"


def _l(ts: str, msg: str) -> str:
    return f"[2026-10-27 {ts}] {S} {msg}"


def _boot(jour: str, dA: str, dB: str, rssB: int) -> list[str]:
    """Un demarrage factice : SvcA (vague 1, pret), SvcHb (vague 1, jamais 'pret'),
    SvcB (vague 2, depend du port de SvcA, pret par /health)."""
    j = lambda ts, m: f"[2026-10-{jour} {ts}] {S} {m}"  # noqa: E731
    return [
        j("12:00:00.000", "LaForge-Master supervisor starting — 3 services"),
        j("12:00:01.000", "🌊 Démarrage Vague Physiologique 1 ..."),
        j("12:00:01.100", "SvcA: started PID 10"),
        j(dA, "SvcA: demarre — vitalite applicative NON MESUREE (aucun health_path declare)"),
        j("12:00:02.600", "SvcHb: started PID 11"),
        j("12:00:04.000", "✅ Vague 1 stabilisée."),
        j("12:00:04.000", "🌊 Démarrage Vague Physiologique 2 ..."),
        j("12:00:04.100", "SvcB: waiting for deps 9000"),
        j("12:00:04.200", "SvcB: started PID 12"),
        j(dB, "SvcB: APPLICATION_UP sur /health"),
        j("12:00:08.200", "✅ Vague 2 stabilisée."),
        j("12:30:00.000", "RAM 90.1% > 88% — sleeping non-essential services"),
        j("12:30:00.000", f"Sleeping SvcB (uptime 1800s, rss {rssB} Mo)"),
        j("12:31:00.000", "Waking SvcB (RAM now 70.0%, cout presume 999 Mo)"),
        j("12:31:01.000", "SvcLate: started PID 13"),
        j("12:31:01.500", "SvcLate: demarre — vitalite applicative NON MESUREE (aucun health_path declare)"),
    ]


JOURNAL = (_boot("26", "12:00:01.600", "12:00:06.200", 300)
           + _boot("27", "12:00:02.600", "12:00:07.200", 350))


# ---------------------------------------------------------------- (1) MESURE

def test_parse_decoupe_les_demarrages_et_garde_les_n_derniers():
    ev = fod.parser_journal(JOURNAL)
    boots = fod.decouper_demarrages(ev, n=5)
    assert len(boots) == 2
    assert len(fod.decouper_demarrages(ev, n=1)) == 1
    assert fod.decouper_demarrages(ev, n=1)[0]["debut"].day == 27


def test_mesure_par_demarrage_duree_illisible_et_rss():
    boots = fod.decouper_demarrages(fod.parser_journal(JOURNAL), n=5)
    m = fod.mesurer_demarrage(boots[0])
    assert m["services"]["SvcA"]["duree_s"] == pytest.approx(0.5)
    assert m["services"]["SvcB"]["duree_s"] == pytest.approx(2.0)
    # SvcHb n'a aucune ligne 'pret' : duree NON mesurable, jamais estimee
    assert m["services"]["SvcHb"]["duree_s"] is None
    # SvcLate est lance APRES la fin des vagues : pas un service de demarrage
    assert "SvcLate" not in m["services"]
    # RSS : la ligne Sleeping compte, le 'cout presume' du Waking non (c'est une recopie)
    assert m["services"]["SvcB"]["rss_mo"] == [300]
    assert m["services"]["SvcA"]["rss_mo"] == []
    assert m["duree_observee_s"] == pytest.approx(7.2)
    assert m["seuil_eviction_pct"] == 88.0
    assert m["ram_max_pct"] == pytest.approx(90.1)
    assert m["stagger_s"] == pytest.approx(1.5)
    assert m["stab_s"] == pytest.approx(1.7)  # mediane(1.4, 2.0)


def test_agregat_mediane_max_et_illisible_dit():
    boots = fod.decouper_demarrages(fod.parser_journal(JOURNAL), n=5)
    agr = fod.agreger([fod.mesurer_demarrage(b) for b in boots])
    assert agr["SvcA"]["duree_s"] == pytest.approx(1.0)   # mediane(0.5, 1.5)
    assert agr["SvcB"]["duree_s"] == pytest.approx(2.5)   # mediane(2.0, 3.0)
    assert agr["SvcHb"]["duree_s"] == fod.ILLISIBLE
    assert agr["SvcB"]["rss_regime_mo"] == 350            # max des mesures
    assert agr["SvcA"]["rss_regime_mo"] == fod.ILLISIBLE
    # aucun journal ne donne de pic : ILLISIBLE pour tous
    assert all(v["rss_pic_mo"] == fod.ILLISIBLE for v in agr.values())


def test_lire_services_resout_les_deps_par_port(tmp_path):
    toml = tmp_path / "services.toml"
    toml.write_text(
        '[[service]]\nname="SvcA"\nwave=1\nport=9000\nessential=true\ncmd="x"\nargs=[]\ncwd="."\n'
        '[[service]]\nname="SvcB"\nwave=2\ndeps=[9000, 7777]\nessential=false\ncmd="x"\nargs=[]\ncwd="."\n'
        '[[service]]\nname="SvcOff"\nwave=2\ndisabled=true\nessential=false\ncmd="x"\nargs=[]\ncwd="."\n',
        encoding="utf-8")
    sv = fod.lire_services(toml)
    assert sv["SvcB"]["deps"] == ["SvcA"]
    assert sv["SvcB"]["deps_orphelines"] == [7777]
    assert sv["SvcA"]["essentiel"] is True and sv["SvcOff"]["disabled"] is True
    assert sv["SvcA"]["ordre"] < sv["SvcB"]["ordre"]


def test_construire_instance_exclut_l_illisible_et_dit_l_ecart():
    sv = {
        "SvcA": {"vague": 1, "deps": [], "deps_orphelines": [], "essentiel": True, "disabled": False, "ordre": 0},
        "SvcHb": {"vague": 1, "deps": [], "deps_orphelines": [], "essentiel": False, "disabled": False, "ordre": 1},
        "SvcB": {"vague": 2, "deps": ["SvcA", "SvcHb"], "deps_orphelines": [], "essentiel": False,
                 "disabled": False, "ordre": 2},
    }
    agr = {
        "SvcA": {"duree_s": 1.0, "rss_regime_mo": fod.ILLISIBLE, "rss_pic_mo": fod.ILLISIBLE},
        "SvcHb": {"duree_s": fod.ILLISIBLE, "rss_regime_mo": 50, "rss_pic_mo": fod.ILLISIBLE},
        "SvcB": {"duree_s": 2.5, "rss_regime_mo": 350, "rss_pic_mo": fod.ILLISIBLE},
    }
    inst = fod.construire_instance(sv, agr, unite_s=0.5)
    noms = {t["nom"]: t for t in inst["taches"]}
    assert set(noms) == {"SvcA", "SvcB"}
    assert noms["SvcA"]["duree"] == 2 and noms["SvcB"]["duree"] == 5   # ceil(d / unite)
    assert noms["SvcA"]["ram"] == 0 and noms["SvcA"]["ram_mesuree"] is False
    assert noms["SvcB"]["pic"] == 350                                   # pic illisible -> regime, dit
    assert noms["SvcB"]["deps"] == ["SvcA"]
    assert any(e["nom"] == "SvcHb" for e in inst["exclus"])
    assert any("SvcHb" in e for e in inst["ecarts"])


# ---------------------------------------------------------------- (2) BORNE

def _inst(**over):
    t = [
        {"nom": "A", "duree": 2, "ram": 3, "pic": 3, "essentiel": True, "deps": [], "vague": 1, "ordre": 0},
        {"nom": "C", "duree": 3, "ram": 4, "pic": 4, "essentiel": False, "deps": [], "vague": 1, "ordre": 1},
        {"nom": "B", "duree": 1, "ram": 2, "pic": 2, "essentiel": True, "deps": ["A"], "vague": 2, "ordre": 2},
    ]
    inst = {"unite_s": 1.0, "taches": t, "exclus": [], "ecarts": []}
    inst.update(over)
    return inst


def test_borne_ram_et_chemin_critique():
    b = fod.borne(_inst(), budget_mo=8)
    assert b["ram_au_plus_tot_mo"] == 9
    assert b["depasse_budget"] is True
    assert b["chemin_critique_unites"] == 3
    assert fod.borne(_inst(), budget_mo=9)["depasse_budget"] is False


# ---------------------------------------------------------------- (4) JUGE

def test_rejeu_detecte_violation_de_dependance_et_mesure_pic():
    r = fod.rejouer(_inst(), {"A": 0, "C": 0, "B": 1}, budget_mo=8)
    assert r["violations_deps"] == [{"tache": "B", "dep": "A", "debut": 1, "dep_pret": 2}]
    assert r["pic_ram_mo"] == 9
    assert r["fin"] == 3
    assert r["instants_hors_budget"] >= 1


def test_simulation_ordre_actuel_par_vagues():
    d = fod.simuler_ordre_actuel(_inst(), stagger=1, stab=1)
    assert d == {"A": 0, "C": 1, "B": 5}
    assert fod.rejouer(_inst(), d, budget_mo=100)["fin"] == 6


def test_juger_compare_plan_et_actuel_par_rejeu():
    inst = _inst()
    j = fod.juger(inst, {"A": 0, "C": 0, "B": 2}, fod.simuler_ordre_actuel(inst, 1, 1), budget_mo=100)
    assert j["plan"]["fin"] == 3 and j["actuel"]["fin"] == 6
    assert j["gain_unites"] == 3
    assert j["plan"]["violations_deps"] == []


# ---------------------------------------------------------------- (3) MODELE CP-SAT

def _resoudre(inst, budget, *extra):
    r = subprocess.run([LAFORGE_PYTHON, str(OUTIL), "resoudre", "--instance", "-", "--budget", str(budget), *extra],
                       input=json.dumps(inst), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def test_cpsat_tout_tient_fin_au_chemin_critique():
    p = _resoudre(_inst(), 9)
    assert p["statut"] == "OPTIMAL"
    assert p["fin"] == 3 and p["reportes"] == []
    assert p["debuts"]["B"] >= p["debuts"]["A"] + 2
    assert fod.rejouer(_inst(), p["debuts"], 9)["violations_deps"] == []


def test_cpsat_reporte_le_non_essentiel_si_budget_court():
    p = _resoudre(_inst(), 6)
    assert p["statut"] == "OPTIMAL"
    assert p["reportes"] == ["C"]
    assert p["fin"] == 3


def test_cpsat_infaisable_dit_sans_report_possible():
    p = _resoudre(_inst(), 4, "--sans-report")
    assert p["statut"] == "INFEASIBLE"
    assert p["debuts"] == {}


def test_cpsat_indexe_par_le_temps_separe_les_pics():
    t = [
        {"nom": "X", "duree": 2, "ram": 1, "pic": 5, "essentiel": True, "deps": [], "vague": 1, "ordre": 0},
        {"nom": "Y", "duree": 2, "ram": 1, "pic": 5, "essentiel": True, "deps": [], "vague": 1, "ordre": 1},
    ]
    inst = {"unite_s": 1.0, "taches": t, "exclus": [], "ecarts": []}
    p = _resoudre(inst, 6)
    assert p["statut"] == "OPTIMAL" and p["fin"] == 4
    r = fod.rejouer(inst, p["debuts"], 6)
    assert r["pic_ram_mo"] <= 6 and r["instants_hors_budget"] == 0
    assert p["vagues"] == [["X"], ["Y"]] or p["vagues"] == [["Y"], ["X"]]


def test_cpsat_departage_au_plus_tot_a_fin_egale():
    # a fin egale, chaque service demarre au plus tot (plan lisible, pas un optimum arbitraire)
    assert _resoudre(_inst(), 9)["debuts"] == {"A": 0, "C": 0, "B": 2}


def test_borne_pile_compte_toute_rss_mesuree_meme_hors_modele():
    agr = {
        "SvcA": {"duree_s": 1.0, "rss_regime_mo": 100, "rss_pic_mo": fod.ILLISIBLE},
        "SvcHb": {"duree_s": fod.ILLISIBLE, "rss_regime_mo": 50, "rss_pic_mo": fod.ILLISIBLE},
        "SvcX": {"duree_s": 2.0, "rss_regime_mo": fod.ILLISIBLE, "rss_pic_mo": fod.ILLISIBLE},
    }
    b = fod.borne_pile(agr, budget_mo=120)
    assert b["rss_regime_mesuree_mo"] == 150
    assert b["n_services"] == 3 and b["n_rss_illisible"] == 1
    assert b["depasse_budget"] is True and b["minorant"] is True


def test_cpsat_deterministe():
    assert _resoudre(_inst(), 9) == _resoudre(_inst(), 9)


# ---------------------------------------------------------------- hygiene

def test_couleur_declaree_et_aucun_except_muet():
    src = OUTIL.read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert any(isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "__FORGE_COLOR__" for t in n.targets)
               for n in tree.body)
    for n in ast.walk(tree):
        if isinstance(n, ast.ExceptHandler):
            corps = n.body
            muet = all(isinstance(s, (ast.Pass, ast.Continue)) or
                       (isinstance(s, ast.Expr) and isinstance(getattr(s, "value", None), ast.Constant))
                       for s in corps)
            assert not muet, f"except muet ligne {n.lineno}"
    assert "embeddings.db" not in src
