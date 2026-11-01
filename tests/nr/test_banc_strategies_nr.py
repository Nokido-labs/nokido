"""NR -- STRATEGIES DE RECHERCHE du banc d'amelioration (owner 29/10) : phases du take-home generalisees.

Faux juge, tmp_path, aucun reseau, aucun LLM. Une classe de test par strategie (a)-(g)."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import pytest  # noqa: E402

import forge_banc_amelioration as B  # noqa: E402
import forge_banc_strategies as S  # noqa: E402

PARAMS = {"x": {"min": 0, "max": 10, "init": 0}, "y": {"min": 0, "max": 10, "init": 0}}


def juge_bol(p):  # optimum (7, 3) -> metrique min 0
    return float(abs(p["x"] - 7) + abs(p["y"] - 3))


class TestParametresBalayageBasin:  # (a) phases 4 et 11
    def test_bornes_refusees(self):
        ok, motif = S.valider_parametres({"x": {"min": 5, "max": 1, "init": 2}})
        assert not ok and "min" in motif

    def test_balayage_trouve_optimum(self):
        r = S.balayage(juge_bol, PARAMS, "min")
        assert r["metrique"] == 0.0 and r["params"] == {"x": 7, "y": 3}

    def test_basin_bruit_nul_refuse(self):
        with pytest.raises(ValueError, match="inerte"):
            S.basin_hopping(juge_bol, PARAMS, "min", n=5, graine=1, bruit=0)

    def test_deux_graines_deux_trajectoires(self):
        a = S.basin_hopping(juge_bol, PARAMS, "min", n=12, graine=1, bruit=0.5)
        b = S.basin_hopping(juge_bol, PARAMS, "min", n=12, graine=2, bruit=0.5)
        assert a["trajectoire"] != b["trajectoire"]
        assert S.verifier_bruit(juge_bol, PARAMS, "min", (1, 2))
        # meme graine = meme trajectoire (deterministe)
        assert a["trajectoire"] == S.basin_hopping(juge_bol, PARAMS, "min", n=12, graine=1, bruit=0.5)["trajectoire"]

    def test_bruit_inerte_detecte(self):
        assert not S.verifier_bruit(lambda p: 1.0, {"x": {"min": 0, "max": 0, "init": 0}}, "min", (1, 2))


class TestBorne:  # (b) phase 3
    def test_arret_borne_atteinte(self):
        n = []

        def ev(p):
            n.append(1)
            return float(abs(p["x"] - 7))
        r = S.basin_hopping(ev, PARAMS, "min", n=200, graine=3, bruit=0.8, borne=0.0)
        assert r["statut"] == "BORNE_ATTEINTE" and r["metrique"] == 0.0 and len(n) < 200

    def test_calculer_borne_commande(self):
        assert S.calculer_borne("cmd", lambda c: '{"borne": 864}\n') == 864.0
        assert S.calculer_borne("cmd", lambda c: "bruit") is None

    def test_verdict_borne_sens(self):
        assert S.borne_atteinte(864, 864, "min") and not S.borne_atteinte(865, 864, "min")
        assert S.borne_atteinte(10, 9, "max") and not S.borne_atteinte(8, 9, "max")

    def test_boucle_s_arrete_au_registre(self, tmp_path):
        banc = {"perimetre": ["tools/mod.py"], "juge": {"commande": "python j.py", "metrique": "m", "sens": "min"},
                "garde_tests": ["t.py"], "strategies": {"borne": {"commande": "x"}}}
        reg = tmp_path / "b" / "registre.jsonl"
        B.consigner_banc(reg, "c", "REFERENCE", 864, "min", "ref")
        r = S.passe_borne("c", banc, reg, lambda c: '{"borne": 864}')
        assert r["statut"] == "BORNE_ATTEINTE"
        assert B.lire_registre(reg)[-1]["statut"] == "BORNE_ATTEINTE"


class TestReaccord:  # (c) phase 7
    def test_variante_jugee_apres_reaccord(self):
        # froide : 1024 (pire que 1000) ; reaccordee : 990 -> AMELIORE seulement apres N evals
        evals = []

        def reaccorder(v, n):
            evals.append(n)
            return 990.0
        r = S.juger_variante("v", reaccorder, 5, 1000.0, "min", froide=1024.0)
        assert r["verdict"] == "AMELIORE" and evals == [5] and r["metrique_froide"] == 1024.0

    def test_sans_reaccord_refuse(self):
        with pytest.raises(ValueError, match="reaccord"):
            S.juger_variante("v", lambda v, n: 1.0, 0, 1000.0, "min", froide=1.0)

    def test_regression_et_egal(self):
        assert S.juger_variante("v", lambda v, n: 1010.0, 3, 1000.0, "min")["verdict"] == "REGRESSION"
        assert S.juger_variante("v", lambda v, n: 1000.0, 3, 1000.0, "min")["verdict"] == "EGAL"


class TestCroisement:  # (d) phase 14
    def test_deux_meilleurs_maillons(self, tmp_path):
        reg = tmp_path / "r.jsonl"
        for m, p in ((1000, "A"), (990, "B"), (995, "C"), (1100, "D")):
            B.consigner_banc(reg, "c", "AMELIORE", m, "min", "p", patch=p, extra={"variante": p})
        vus = []

        def croiser(a, b):
            vus.append((a["variante"], b["variante"]))
            return "AxB"
        r = S.croiser_meilleurs(reg, "min", croiser, lambda c: 980.0)
        assert vus == [("B", "C")] and r["verdict"] == "AMELIORE" and r["metrique"] == 980.0

    def test_moins_de_deux_maillons(self, tmp_path):
        reg = tmp_path / "r.jsonl"
        B.consigner_banc(reg, "c", "REFERENCE", 1000, "min", "p")
        assert S.croiser_meilleurs(reg, "min", lambda a, b: 1, lambda c: 1.0)["verdict"] == "NON_APPLICABLE"


class TestPlateauImpossible:  # (e) phases 10, 12
    def test_plateau_consigne(self, tmp_path):
        reg = tmp_path / "r.jsonl"
        r = S.consigner_plateau(reg, "c", [1000, 990, 990, 990, 990], 3, "min")
        assert r["statut"] == "IMPOSSIBLE_MESURE" and "3" in r["raison"]
        assert B.lire_registre(reg)[-1]["statut"] == "IMPOSSIBLE_MESURE"

    def test_pas_de_plateau(self, tmp_path):
        assert S.consigner_plateau(tmp_path / "r.jsonl", "c", [1000, 990, 980], 3, "min") is None

    def test_infeasible_exige_motif(self, tmp_path):
        reg = tmp_path / "r.jsonl"
        with pytest.raises(ValueError, match="motif"):
            S.consigner_infeasible(reg, "c", "")
        S.consigner_infeasible(reg, "c", "CP-SAT INFEASIBLE a 864 : -2 ops requis")
        d = B.lire_registre(reg)[-1]
        assert d["statut"] == "INFEASIBLE" and "864" in d["raison"]

    def test_non_prouves(self):
        assert "IMPOSSIBLE_MESURE" not in B.PROUVES and "INFEASIBLE" not in B.PROUVES


class TestCrochets:  # (f) phases 10, 12
    def test_installe(self):
        r = S.crochet("solveur_exact", "py", sonde=lambda py, mod: mod == "ortools")
        assert r["statut"] == "APPLICABLE"

    def test_absent_non_applicable_dit(self):
        r = S.crochet("superopt", "py", sonde=lambda py, mod: False)
        assert r["statut"] == "NON_APPLICABLE" and "z3" in r["motif"]

    def test_crochet_inconnu(self):
        with pytest.raises(ValueError):
            S.crochet("magie", "py", sonde=lambda a, b: True)

    def test_declare_par_cible(self):
        ok, motif = S.valider_strategies({"crochets": ["solveur_exact", "superopt"]})
        assert ok, motif
        ok, _ = S.valider_strategies({"crochets": ["inconnu"]})
        assert not ok


class TestAntiTriche:  # (g) phase 15
    BANC = {"juge": {"empreintes": ["tools/bancs/corpus_x.jsonl", "tools/bancs/graine.json"]},
            "strategies": {"interdits": ["secret_seed"]}}

    def test_lecture_corpus_refusee(self):
        m = S.controler_triche('data = open("tools/bancs/corpus_x.jsonl").read()\n', self.BANC)
        assert m and "corpus_x" in m

    def test_graine_refusee(self):
        assert S.controler_triche("p = Path('graine.json')\n", self.BANC)
        assert S.controler_triche("x = 'secret_seed'\n", self.BANC)

    def test_code_propre(self):
        assert S.controler_triche("def f(a):\n    return a + 1\n", self.BANC) is None

    def test_integre_au_banc(self, tmp_path):
        banc = {"perimetre": ["m.py"], "juge": {"commande": "x", "metrique": "m", "sens": "max",
                                                "empreintes": ["corpus_x.jsonl"]}}
        copie = tmp_path
        (copie / "m.py").write_text("x = open('corpus_x.jsonl').read()\n", encoding="utf-8")
        r = {}
        deps = B.Deps(None, None, None, lambda b, c: (_ for _ in ()).throw(AssertionError("garde atteinte")),
                      lambda b, c: 1.0, None, None)
        B._juger_candidat(banc, copie, deps, r, 0.0, "max", {"m.py": "x = 1\n"})
        assert r["verdict"] == "TRICHE_REFUSEE"
