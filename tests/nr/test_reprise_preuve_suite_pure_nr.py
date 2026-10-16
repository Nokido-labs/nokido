"""NR -- option A (decision owner du 2026-10-14) : le runner REPREND la preuve de la suite pure d'un autre observateur.

Mesure : la CI de reference (compte de job) puis le runner GitHub (compte du poste) rejouaient la MEME suite pure
(14 255 tests, ~20 min) sur le MEME poste. Contrats :
  1. reprise seulement si TOUT ce qui ne depend pas du compte concorde : preuve certifiee (CAPTURED/SUITE_COMPLETE,
     lock reconcilie), meme sha, meme plan, meme contrat, meme lock, repreneur CONFORME au lock, meme machine ;
  2. les axes non re-mesures (compte, fichiers du profil) sont DITS ;
  3. une racine absente, une preuve illisible ou refusee est DITE, et la suite pure est alors REJOUEE ;
  4. le chemin reel (`main --only pytest --reprendre-preuve`) sort AVANT toute bascule de worktree ;
  5. le workflow passe la racine partagee et garde un rejeu force (`rejouer_suite_pure`).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_ci_proof as P  # noqa: E402

SHA = "eed4c61dbc52a7fee1e499e1a08162bed316f0cc"
MACHINE = {"os": "Windows 11", "arch": "AMD64", "modele_cpu": "AMD Ryzen 7 8700G", "processeur": "AMD64 Family 25"}
ATTENDU = {"plan": "plan-1", "contrat": "contrat-1", "lock": "lock-1", "match": "CONFORME", "substrat": dict(MACHINE)}


def _preuve(**sur):
    base = dict(target_sha=SHA[:9], process_state="CAPTURED", certification_state="SUITE_COMPLETE",
                test_plan_hash="plan-1", ci_contract_hash="contrat-1", environment_fingerprint="env-job",
                observed_head=SHA, failure_stage=None, proof_root="x", execution_id="ci-reference-abc",
                dependency_lock_hash="lock-1", dependency_match="CONFORME", contrat_illisible=[], extra=None,
                substrat=dict(MACHINE), proof_write_error=None)
    base.update(sur)
    return P.manifeste(**base)


def test_reprise_seulement_si_tout_concorde_hors_compte():
    assert P.reprenable(_preuve(), SHA, ATTENDU) == (True, "")
    assert not P.reprenable(_preuve(observed_head="0" * 40), SHA, ATTENDU)[0]
    assert not P.reprenable(_preuve(test_plan_hash="plan-2"), SHA, ATTENDU)[0]
    assert not P.reprenable(_preuve(ci_contract_hash="autre"), SHA, ATTENDU)[0]
    assert not P.reprenable(_preuve(dependency_lock_hash="lock-2"), SHA, ATTENDU)[0]
    assert not P.reprenable(_preuve(certification_state="SUITE_PARTIELLE"), SHA, ATTENDU)[0]
    ailleurs = dict(MACHINE, modele_cpu="Intel")
    assert "machine" in P.reprenable(_preuve(substrat=ailleurs), SHA, ATTENDU)[1]
    assert "repreneur" in P.reprenable(_preuve(), SHA, dict(ATTENDU, match="ECARTS"))[1]


def test_la_recherche_prend_la_plus_recente_valide_et_dit_les_refus(tmp_path):
    import os
    import time
    rac = tmp_path / "nokido_proof"
    for nom, m, t in (("ci-reference-vieille", _preuve(test_plan_hash="plan-0"), 100),
                      ("ci-reference-bonne", _preuve(), 200),
                      ("ci-reference-autre-sha", _preuve(observed_head="1" * 40), 300)):
        f = rac / nom / "artefacts" / "ci_proof.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps(m), encoding="utf-8")
        os.utime(f, (time.time() - 1000 + t, time.time() - 1000 + t))
    chemin, m, refus = P.chercher_reprise(SHA, [str(rac), str(tmp_path / "absente")], ATTENDU)
    assert chemin and chemin.parent.parent.name == "ci-reference-bonne"
    assert any("absente" in r for r in refus), refus
    assert P.chercher_reprise("2" * 40, [str(rac)], ATTENDU)[0] is None
    assert P.AXES_NON_REMESURES == ("compte", "fichiers residents du profil")


def test_le_chemin_reel_sort_avant_toute_bascule(monkeypatch, capsys):
    import ci_local as C
    vus = {}
    monkeypatch.setenv("NOKIDO_PREUVES_PARTAGEES", "C:/nulle/part")
    monkeypatch.setattr(C, "_git_reference", lambda args: (0, SHA + "\n", ""))
    monkeypatch.setattr(P, "chercher_reprise",
                        lambda sha, racines, attendu: (vus.update(sha=sha, racines=racines, attendu=attendu)
                                                       or (Path("x/ci-reference-abc/artefacts/ci_proof.json"),
                                                           _preuve(), [])))
    assert C._reprendre_preuve_suite_pure() == 0
    out = capsys.readouterr().out
    assert "[preuve-reprise]" in out and "compte,fichiers residents du profil" in out
    assert vus["sha"] == SHA and vus["racines"] == ["C:/nulle/part"]
    assert set(vus["attendu"]) >= {"plan", "contrat", "lock", "match", "substrat"}

    # `main` pose des GLOBALES (_ONLY, _EMPREINTES_FERMETURE) : les confier a monkeypatch pour qu'elles soient
    # restaurees -- sans cela les tests suivants heritaient de `--only pytest` (3 echecs d'ordre, mesures le 14/10).
    for g in ("_ONLY", "_EMPREINTES_FERMETURE"):
        monkeypatch.setattr(C, g, getattr(C, g, None))
    monkeypatch.setattr(C, "_reprendre_preuve_suite_pure", lambda: 0)
    monkeypatch.setattr(C, "_ecrire_ci_proof", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gate lance")))
    monkeypatch.setattr(sys, "argv", ["ci_local.py", "--only", "pytest", "--reprendre-preuve"])
    assert C.main() == 0


def test_sans_racine_declaree_rien_n_est_repris(monkeypatch, capsys):
    import ci_local as C
    monkeypatch.delenv("NOKIDO_PREUVES_PARTAGEES", raising=False)
    assert C._reprendre_preuve_suite_pure() is None
    assert "REJOUEE" in capsys.readouterr().out


def test_le_workflow_passe_la_racine_et_garde_le_rejeu_force():
    import yaml
    d = yaml.safe_load((ROOT / ".github" / "workflows" / "ci-selfhosted.yml").read_text(encoding="utf-8"))
    assert "rejouer_suite_pure" in d[True]["workflow_dispatch"]["inputs"]
    etape = next(s for s in d["jobs"]["pytest-pur"]["steps"] if "ci_local.py" in (s.get("run") or ""))
    assert "nokido_proof" in etape["env"]["NOKIDO_PREUVES_PARTAGEES"]
    assert "--reprendre-preuve" in etape["run"] and "rejouer_suite_pure" in etape["run"]
    assert "'--turbo'" in etape["run"], "le runner rejoue la suite pure en turbo quand il ne reprend pas la preuve"
    assert "$args" not in etape["run"], "$args est une variable automatique PowerShell"


def test_le_contrat_ne_depend_ni_de_l_emplacement_ni_des_fins_de_ligne(tmp_path):
    # Mesure 2026-10-14 (973191f54) : reference (worktree, LF) c819c46f... contre runner (checkout, CRLF)
    # 2a87803a... au MEME sha -- cles absolues + octets bruts : la reprise ne pouvait jamais concorder.
    import forge_ci_proof as P
    a, b = tmp_path / "reference" / "worktree", tmp_path / "laforge-runner" / "_work" / "checkout"
    for racine, fin in ((a, b"\n"), (b, b"\r\n")):
        (racine / "tools").mkdir(parents=True)
        (racine / "tools" / "ci_local.py").write_bytes(b"def f():" + fin + b"    return 1" + fin)
    rel = ["tools/ci_local.py"]
    ha = P.hash_contrat([a / r for r in rel], racine=a)
    hb = P.hash_contrat([b / r for r in rel], racine=b)
    assert ha == hb and ha[1] == []
    (b / "tools" / "ci_local.py").write_bytes(b"def f():\r\n    return 2\r\n")
    assert P.hash_contrat([b / r for r in rel], racine=b)[0] != ha[0], "le CONTENU change le contrat"


def test_ci_local_passe_la_racine_et_la_preuve_nomme_ses_ecarts_au_lock():
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert src.count("hash_contrat([ROOT / c for c in _CONTRAT_CI], racine=ROOT)") == 2
    assert "hash_contrat([ROOT / c for c in _CONTRAT_CI])" not in src
    assert '{"dependances": _dependances}' in src, "un DIVERGENT doit nommer ses ecarts dans la preuve"


def test_le_hook_pre_push_ignore_le_user_site_et_reste_en_lf():
    # 2026-10-14 : les preuves DIVERGENT prises pour celles du runner venaient du pre-push (session owner). Et un
    # shebang en CRLF (`python\r`) casse le hook sous le sh de Git : il doit rester en LF dans la copie de travail.
    brut = (ROOT / ".githooks" / "pre-push").read_bytes()
    assert b'env["PYTHONNOUSERSITE"] = "1"' in brut
    assert b"\r\n" not in brut, "pre-push en CRLF : le shebang devient `python\\r` et le hook ne s'execute plus"


def test_le_runner_ne_lit_pas_le_user_site_de_l_owner():
    # Mesure 2026-10-14 : le runner tourne sous le compte du poste, dont le user-site Python 3.14 passe DEVANT
    # l'env ; 5 des 43 paquets du lock CI y ont une autre version -> la preuve du runner pour eed4c61db sortait
    # DIVERGENT quand la reference etait CONFORME au meme lock, et `find_spec` y voyait des modules du seul
    # user-site (empreinte de substrat) : aucune reprise n'aurait jamais concorde.
    # Portee : les jobs qui produisent et consomment les preuves. Pas tout le workflow -- sans user-site, l'env
    # n'a pas pyarmor, dont `build-dist` a besoin.
    import yaml
    d = yaml.safe_load((ROOT / ".github" / "workflows" / "ci-selfhosted.yml").read_text(encoding="utf-8"))
    for nom in ("gates", "pytest-pur"):
        job = d["jobs"][nom]
        assert str((job.get("env") or {}).get("PYTHONNOUSERSITE")) == "1", nom
        for s in job.get("steps", []):
            assert str((s.get("env") or {}).get("PYTHONNOUSERSITE", "1")) == "1", (nom, s.get("name"))
