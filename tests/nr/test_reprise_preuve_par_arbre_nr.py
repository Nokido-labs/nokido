"""NR -- verdict PAR ARBRE (choix owner du 2026-11-10) : une preuve du MEME `HEAD^{tree}` sous un AUTRE sha est reprise.

Mesure : `[reprise] AUCUNE preuve reprenable pour e2e37e248b9f -- aucune preuve capturee pour ce sha`
(C:/tmp/job_pytest_pur_42547794727.log l.152) -- la CI locale avait certifie un AUTRE sha au contenu identique,
et le runner a rejoue la suite pure (~15 min). Un sha change avec le message, l'auteur, la date ; l'arbre ne change
qu'avec le CONTENU suivi. Contrats :
  1. meme arbre, autre sha -> reprise, et le motif dit qu'elle se fait PAR L'ARBRE ;
  2. arbre different (ou absent d'un cote) et autre sha -> refus, comme avant ;
  3. une preuve ancienne sans `observed_tree` reste reprenable par le sha seul (compatibilite) ;
  4. la capture ecrit `observed_tree` dans le manifeste.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_ci_proof as P  # noqa: E402

SHA = "eed4c61dbc52a7fee1e499e1a08162bed316f0cc"
AUTRE = "e2e37e248b9f" + "0" * 28
ARBRE = "a" * 40
MACHINE = {"os": "Windows 11", "arch": "AMD64", "modele_cpu": "AMD Ryzen 7 8700G", "processeur": "AMD64 Family 25"}
ATTENDU = {"plan": "plan-1", "contrat": "contrat-1", "lock": "lock-1", "match": "CONFORME",
           "substrat": dict(MACHINE), "tree": ARBRE}


def _preuve(**sur):
    base = dict(target_sha=SHA[:9], process_state="CAPTURED", certification_state="SUITE_COMPLETE",
                test_plan_hash="plan-1", ci_contract_hash="contrat-1", environment_fingerprint="env-job",
                observed_head=SHA, observed_tree=ARBRE, failure_stage=None, proof_root="x",
                execution_id="ci-reference-abc", dependency_lock_hash="lock-1", dependency_match="CONFORME",
                contrat_illisible=[], extra=None, substrat=dict(MACHINE), proof_write_error=None)
    base.update(sur)
    return P.manifeste(**base)


def test_le_manifeste_porte_l_arbre_observe():
    assert _preuve()["observed_tree"] == ARBRE
    assert _preuve(observed_tree=None)["observed_tree"] is None


def test_meme_arbre_autre_sha_est_repris():
    ok, motif = P.reprenable(_preuve(), AUTRE, ATTENDU)
    assert ok, motif


def test_arbre_different_ou_absent_refuse_sous_un_autre_sha():
    assert not P.reprenable(_preuve(observed_tree="b" * 40), AUTRE, ATTENDU)[0]
    assert not P.reprenable(_preuve(observed_tree=None), AUTRE, ATTENDU)[0]
    assert not P.reprenable(_preuve(), AUTRE, dict(ATTENDU, tree=None))[0]
    # l'arbre ne dispense d'AUCUN autre axe
    assert not P.reprenable(_preuve(test_plan_hash="plan-2"), AUTRE, ATTENDU)[0]


def test_preuve_ancienne_sans_arbre_reste_reprenable_par_le_sha():
    assert P.reprenable(_preuve(observed_tree=None), SHA, ATTENDU) == (True, "")


def test_la_recherche_trouve_la_preuve_par_l_arbre(tmp_path):
    rac = tmp_path / "nokido_proof"
    for nom, m in (("ci-reference-meme-arbre", _preuve()),
                   ("ci-reference-autre-arbre", _preuve(observed_head="1" * 40, observed_tree="c" * 40))):
        f = rac / nom / "artefacts" / "ci_proof.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps(m), encoding="utf-8")
    chemin, m, refus = P.chercher_reprise(AUTRE, [str(rac)], ATTENDU)
    assert chemin and chemin.parent.parent.name == "ci-reference-meme-arbre", refus
    assert P.chercher_reprise(AUTRE, [str(rac)], dict(ATTENDU, tree="d" * 40))[0] is None


def test_la_capture_et_le_repreneur_lisent_l_arbre():
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert 'HEAD^{tree}' in src
    assert 'observed_tree=ctx.get("tree")' in src
    assert 'attendu["tree"]' in src


def test_le_job_gates_reprend_la_preuve():
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert '_gates_seuls = bool(getattr(a, "no_tests", False)) and not _ONLY' in src
    wf = (ROOT / ".github" / "workflows" / "ci-selfhosted.yml").read_text(encoding="utf-8")
    bloc = wf.split("Gates CI (flake8", 1)[1].split("- name:", 1)[0]
    assert "NOKIDO_PREUVES_PARTAGEES" in bloc and "--reprendre-preuve" in bloc
    assert "rejouer_suite_pure" in bloc, "le rejeu force doit rester possible"
