"""NR -- mesure APRES application et retour arriere PROUVE, sur un DEPOT TEMPORAIRE.

Mission regeneration du 2026-10-01 (note RSI §2.3-2.5, criteres de preuve 5, 6, 7) :
  5. acte dans la bande  -> CONSERVE, inscrit au registre et rattache a l'exp_id ;
  6. regression mesuree  -> `git revert -m 1` reel, arbre IDENTIQUE a celui d'avant le
     merge, mesure revenue dans la bande, entree REVERTE, chaine du registre intacte ;
  7. porte fermee        -> aucune etape ne mute (ni depot, ni registre), verdict = etat.
Plus les deux freins : revert NON prouve -> frein immediat ; deux reverts consecutifs ->
frein ; un CONSERVE intercale remet le compte a zero.

Les tests touchent la zone de l'evaluateur : ils sont RELUS par l'owner avant tout merge.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from nokido_agent.app import forge_autonomous_loops as al
from nokido_agent.app import forge_mutation_controller as mc
from nokido_agent.app import forge_mutation_judge as juge
from nokido_agent.tools import forge_merge_gate as mg

BRUIT = {"score": 0.5}


def _git(depot, *args):
    r = subprocess.run(["git", "-c", "safe.directory=*", *args], cwd=str(depot),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    depot = tmp_path / "depot"
    depot.mkdir()
    _git(depot, "init", "-q", "-b", "alpha")
    _git(depot, "config", "user.email", "nr@nokido.local")
    _git(depot, "config", "user.name", "nr")
    (depot / "score.txt").write_text("10", encoding="utf-8")
    _git(depot, "add", "score.txt")
    _git(depot, "commit", "-q", "-m", "base")
    monkeypatch.setattr(al, "_EVOLUTION_LEDGER", tmp_path / "evolution_experiences.jsonl")
    monkeypatch.setattr(al, "_ensure_ledger_migrated", lambda: None)
    monkeypatch.setattr(mc, "_generation_avant", lambda: None)
    freins = []
    monkeypatch.setattr(juge, "poser_frein_evolution",
                        lambda motif, par="": freins.append((motif, par)) or {"ok": True},
                        raising=False)
    monkeypatch.setattr(juge, "evolution_autorisee",
                        lambda: {"autorisee": True, "etat": "ARMEE", "motif": "nr"}, raising=False)
    return {"depot": depot, "freins": freins, "ledger": tmp_path / "evolution_experiences.jsonl"}


def _merger_wip(depot, score, nom="wip/agent"):
    """Prepare wip/<agent> avec `score`, puis fait le merge --no-ff dans alpha. Rend son sha."""
    _git(depot, "checkout", "-q", "-b", nom)
    (depot / "score.txt").write_text(str(score), encoding="utf-8")
    _git(depot, "commit", "-q", "-am", "candidat %s" % score)
    _git(depot, "checkout", "-q", "alpha")
    _git(depot, "merge", "-q", "--no-ff", "-m", "merge %s" % nom, nom)
    return _git(depot, "rev-parse", "HEAD")


def _mesurer(depot):
    return lambda: {"score": float((depot / "score.txt").read_text(encoding="utf-8"))}


def _registre(ledger):
    return [json.loads(x) for x in Path(ledger).read_text(encoding="utf-8").splitlines() if x]


# ── 5. dans la bande : garde, inscrit, rattache ─────────────────────────────────────
def test_merge_dans_la_bande_est_conserve_et_rattache(env):
    d = env["depot"]
    merge = _merger_wip(d, 12)
    gen = []
    r = mc.mesurer_apres_merge(merge, "exp_nr_5", {"score": 10.0}, racine=d,
                               mesurer=_mesurer(d), bruit=BRUIT,
                               apres_conserve=lambda: gen.append(1) or {"generation": "GEN-T"})
    assert r["verdict"] == "CONSERVE" and gen == [1]
    assert _git(d, "rev-parse", "HEAD") == merge  # rien n'a ete defait
    (e,) = [x for x in _registre(env["ledger"]) if x["kind"] == "post_application"]
    assert e["ref_exp"] == "exp_nr_5" and e["verdict"] == "CONSERVE"
    assert e["apres_conserve"] == {"generation": "GEN-T"} and env["freins"] == []


# ── 6. regression : revert reel, arbre identique, mesure revenue, chaine intacte ─────
def test_regression_revert_reel_et_prouve(env):
    d = env["depot"]
    arbre_avant = _git(d, "rev-parse", "HEAD^{tree}")
    merge = _merger_wip(d, 5)
    r = mc.mesurer_apres_merge(merge, "exp_nr_6", {"score": 10.0}, racine=d,
                               mesurer=_mesurer(d), bruit=BRUIT)
    assert r["verdict"] == "REVERTE", r
    p = r["preuve"]
    assert p["revert_ok"] and p["empreinte_identique"] and p["mesure_revenue_dans_bande"]
    # Le CONTENU, pas le rc : l'arbre et la valeur sont bien ceux d'avant.
    assert _git(d, "rev-parse", "HEAD^{tree}") == arbre_avant
    assert (d / "score.txt").read_text(encoding="utf-8") == "10"
    # Un commit de PLUS (revert), jamais une reecriture : le merge reste dans l'historique.
    assert _git(d, "rev-parse", "HEAD~1") == merge
    (e,) = [x for x in _registre(env["ledger"]) if x["kind"] == "post_application"]
    assert e["verdict"] == "REVERTE" and e["ref_exp"] == "exp_nr_6"
    assert e["ecarts"][0]["dimension"] == "score"
    assert al.verifier_chaine_evolution()["ok"] is True
    assert env["freins"] == []  # un seul revert : pas encore de frein


def test_deux_reverts_consecutifs_posent_le_frein(env):
    d = env["depot"]
    for i, nom in enumerate(("wip/a", "wip/b")):
        merge = _merger_wip(d, 4, nom=nom)
        r = mc.mesurer_apres_merge(merge, "exp_%d" % i, {"score": 10.0}, racine=d,
                                   mesurer=_mesurer(d), bruit=BRUIT)
        assert r["verdict"] == "REVERTE"
    assert len(env["freins"]) == 1 and "2 reverts consecutifs" in env["freins"][0][0]
    assert env["freins"][0][1] == "forge_mutation_controller"


def test_un_conserve_intercale_remet_le_compte_a_zero(env):
    d = env["depot"]
    for nom, score in (("wip/a", 4), ("wip/b", 11), ("wip/c", 4)):
        merge = _merger_wip(d, score, nom=nom)
        ref = {"score": float(_git(d, "show", "%s^1:score.txt" % merge))}
        mc.mesurer_apres_merge(merge, nom, ref, racine=d, mesurer=_mesurer(d), bruit=BRUIT)
    assert env["freins"] == []


def test_revert_non_prouve_pose_le_frein_immediatement(env):
    d = env["depot"]
    merge = _merger_wip(d, 5)
    # Mesure qui ne revient PAS avec le revert (effet de bord hors du depot) : l'arbre est
    # identique, mais la capacite ne l'est pas -- le retour n'est pas prouve.
    r = mc.mesurer_apres_merge(merge, "exp_np", {"score": 10.0}, racine=d,
                               mesurer=lambda: {"score": 5.0}, bruit=BRUIT)
    assert r["verdict"] == "REVERT_NON_PROUVE"
    assert r["preuve"]["empreinte_identique"] is True
    assert r["preuve"]["mesure_revenue_dans_bande"] is False
    assert len(env["freins"]) == 1 and "NON PROUVE" in env["freins"][0][0]


def test_mesure_apres_illisible_vaut_regression(env):
    d = env["depot"]
    arbre_avant = _git(d, "rev-parse", "HEAD^{tree}")
    merge = _merger_wip(d, 12)
    appels = []

    def _mesure():
        appels.append(1)
        if len(appels) == 1:
            raise OSError("banc injoignable")
        return {"score": 10.0}
    r = mc.mesurer_apres_merge(merge, "exp_ill", {"score": 10.0}, racine=d, mesurer=_mesure,
                               bruit=BRUIT)
    assert r["verdict"] == "REVERTE"  # on ne garde pas ce qu'on n'a pas pu mesurer
    assert _git(d, "rev-parse", "HEAD^{tree}") == arbre_avant


# ── 7. porte fermee : rien ne mute ──────────────────────────────────────────────────
@pytest.mark.parametrize("etat", ["HALTED", "DESARMEE", "VERROU_HUMAIN", "INCONNU"])
def test_porte_fermee_appliquer_et_mesurer_ne_mute_rien(env, monkeypatch, etat):
    monkeypatch.setattr(juge, "evolution_autorisee",
                        lambda: {"autorisee": False, "etat": etat, "motif": "nr"}, raising=False)
    actes = []
    r = mc.appliquer_et_mesurer("L1", "param:x", None, appliquer=lambda: actes.append(1),
                                reverter=lambda: actes.append(-1), mesurer=lambda: actes.append(0),
                                empreinte=lambda: "e", bruit={})
    assert r["verdict"] == etat and r["applique"] is False and actes == []
    assert not env["ledger"].exists()


def test_porte_fermee_cycle_ne_tente_aucun_merge(env, monkeypatch):
    d = env["depot"]
    head = _git(d, "rev-parse", "HEAD")
    monkeypatch.setattr(juge, "evolution_autorisee",
                        lambda: {"autorisee": False, "etat": "HALTED", "motif": "frein"},
                        raising=False)
    appels = []
    monkeypatch.setattr(mg, "merger", lambda *a, **k: appels.append(a) or {"applique": True})
    r = mc.cycle("agent", tests=["t"], apply=True, racine=d, mesurer=_mesurer(d))
    assert r["verdict"] == "HALTED" and appels == []
    assert _git(d, "rev-parse", "HEAD") == head and not env["ledger"].exists()


def test_porte_absente_vaut_fermee(env, monkeypatch):
    monkeypatch.delattr(juge, "evolution_autorisee", raising=False)
    r = mc.appliquer_et_mesurer("L1", "param:x", None, appliquer=lambda: {"ok": True},
                                reverter=lambda: {"ok": True}, mesurer=lambda: {"s": 1.0},
                                empreinte=lambda: "e", bruit={})
    assert r["verdict"] == "INCONNU" and r["applique"] is False


# ── cycle complet : gate (simulee) -> merge reel -> mesure apres -> revert ──────────
def test_cycle_regression_apres_merge_est_revertee(env, monkeypatch):
    d = env["depot"]
    arbre_avant = _git(d, "rev-parse", "HEAD^{tree}")

    def _merger(agent, tests, apply):
        _merger_wip(d, 3)
        return {"applique": True, "verdict": "AMELIORE", "branch": "wip/agent",
                "decision": "MERGE (nr)", "baseline": {}}
    monkeypatch.setattr(mg, "merger", _merger)
    monkeypatch.setattr(mc, "_capturer_generation",
                        lambda agent, note: pytest.fail("pas de generation pour un revert"))
    r = mc.cycle("agent", tests=["t"], apply=True, racine=d, mesurer=_mesurer(d), bruit=BRUIT)
    assert r["verdict_apres"] == "REVERTE"
    assert _git(d, "rev-parse", "HEAD^{tree}") == arbre_avant
    kinds = [x["kind"] for x in _registre(env["ledger"])]
    assert kinds == ["merge_applique", "post_application"]  # l'effet a une cause inscrite
    reg = _registre(env["ledger"])
    assert reg[1]["ref_exp"] == reg[0]["exp_id"]


def test_cycle_conserve_capture_la_generation(env, monkeypatch):
    d = env["depot"]

    def _merger(agent, tests, apply):
        _merger_wip(d, 11)
        return {"applique": True, "verdict": "AMELIORE", "branch": "wip/agent", "baseline": {}}
    monkeypatch.setattr(mg, "merger", _merger)
    notes = []
    monkeypatch.setattr(mc, "_capturer_generation",
                        lambda agent, note: notes.append(note) or {"generation": "GEN-NR"})
    r = mc.cycle("agent", tests=["t"], apply=True, racine=d, mesurer=_mesurer(d), bruit=BRUIT,
                 exp_id="exp_cycle")
    assert r["verdict_apres"] == "CONSERVE" and r["etapes"]["generation"] == {"generation": "GEN-NR"}
    assert len(notes) == 1 and "exp_cycle" in notes[0]


# ── la bande, en pur ────────────────────────────────────────────────────────────────
def test_bande_dimension_perdue_ou_non_finie_compte():
    ref = {"a": 1.0, "b": 2.0}
    assert mc.ecarts_hors_bande(ref, {"a": 1.0, "b": 2.0}, {}) == []
    assert [e["dimension"] for e in mc.ecarts_hors_bande(ref, {"a": 1.0}, {})] == ["b"]
    assert [e["dimension"] for e in mc.ecarts_hors_bande(ref, {"a": float("nan"), "b": 2.0},
                                                          {})] == ["a"]
    assert mc.ecarts_hors_bande(ref, None, {})[0]["dimension"] == "*"
    # Un GAIN n'est pas une regression ; mais il n'est pas « revenu dans la bande ».
    assert mc.ecarts_hors_bande(ref, {"a": 5.0, "b": 2.0}, {}) == []
    assert [e["dimension"] for e in mc.ecarts_hors_bande(ref, {"a": 5.0, "b": 2.0}, {},
                                                          sens="ecart")] == ["a"]


def test_dimensions_par_test_voient_un_echange():
    """Reparer un test et en casser un autre laisse le COMPTE egal : la dimension par test
    voit le recul."""
    avant = mc._dimensions_tests({"tests": ["t1", "t2"], "tests_passes": ["t1"], "tests_ok": 1})
    apres = mc._dimensions_tests({"tests": ["t1", "t2"], "tests_passes": ["t2"], "tests_ok": 1})
    assert [e["dimension"] for e in mc.ecarts_hors_bande(avant, apres, {})] == ["nr:t1"]


# ── revue adversariale : les trois faux-verts fermes ────────────────────────────────
def test_reference_vide_indecidable_et_frein_sans_revert(env):
    d = env["depot"]
    merge = _merger_wip(d, 3)
    r = mc.mesurer_apres_merge(merge, "exp_vide", {}, racine=d, mesurer=_mesure_constante(3.0),
                               bruit=BRUIT)
    assert r["verdict"] == "INDECIDABLE" and _git(d, "rev-parse", "HEAD") == merge
    assert len(env["freins"]) == 1 and "reference vide" in env["freins"][0][0]


def test_cycle_sans_baseline_mesuree_ne_conserve_pas_par_vide(env, monkeypatch):
    d = env["depot"]

    def _merger(agent, tests, apply):
        _merger_wip(d, 3)
        return {"applique": True, "verdict": "AMELIORE", "branch": "wip/agent", "baseline": {}}
    monkeypatch.setattr(mg, "merger", _merger)
    monkeypatch.setattr(mc, "_capturer_generation",
                        lambda agent, note: pytest.fail("aucune generation sans mesure"))
    r = mc.cycle("agent", tests=["tests/nr/t_nr.py"], apply=True, racine=d)
    assert r["verdict_apres"] == "INDECIDABLE"


def test_revert_en_conflit_est_annule_et_non_prouve(env):
    d = env["depot"]
    merge = _merger_wip(d, 5)
    (d / "score.txt").write_text("7", encoding="utf-8")  # alpha a bouge depuis le merge
    _git(d, "commit", "-q", "-am", "apres le merge")
    r = mc.mesurer_apres_merge(merge, "exp_conflit", {"score": 10.0}, racine=d,
                               mesurer=_mesurer(d), bruit=BRUIT)
    assert r["verdict"] == "REVERT_NON_PROUVE"
    assert r["preuve"]["revert_ok"] is False and r["preuve"]["detail_revert"]["abort"] == "ok"
    assert not (d / ".git" / "REVERT_HEAD").exists()           # pas laisse a moitie defait
    assert _git(d, "status", "--porcelain", "--untracked-files=no") == ""
    assert len(env["freins"]) == 1


def test_empreinte_illisible_ni_acte_ni_preuve(env):
    actes = []

    def _boum():
        raise OSError("magasin illisible")
    r = mc.appliquer_et_mesurer("L1", "param:x", None, appliquer=lambda: actes.append(1),
                                reverter=lambda: {"ok": True}, mesurer=lambda: {"s": 1.0},
                                empreinte=_boum, bruit={})
    assert r["verdict"] == "INDECIDABLE" and actes == []
    # Et deux lectures ratees ne font JAMAIS une empreinte identique.
    assert mc._empreinte_sure(_boum) is None


def _mesure_constante(v):
    return lambda: {"score": v}
