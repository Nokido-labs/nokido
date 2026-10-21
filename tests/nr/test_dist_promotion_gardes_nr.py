"""NR 20/10 -- tools/dist_promotion.py : les gardes de la promotion du dist ne laissent passer
qu'une certification VERTE et UNIQUE pour le sha, et le scan du tarball compte sans rien rendre."""
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("dist_promotion", RACINE / "tools" / "dist_promotion.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dist_promotion"] = mod
    spec.loader.exec_module(mod)
    return mod


SHA = "d8e8b7b0c" + "0" * 31


def _preuve(racine, nom, **champs):
    j = {"target_sha": SHA, "observed_head": SHA, "certification_state": "SUITE_COMPLETE",
         "process_state": "CAPTURED", "incoherences": [], "non_couvert": []}
    j.update(champs)
    d = racine / nom / "artefacts"
    d.mkdir(parents=True)
    (d / "ci_proof.json").write_text(json.dumps(j), encoding="utf-8")


def test_seule_une_preuve_complete_pour_ce_sha_compte(tmp_path):
    m = _module()
    _preuve(tmp_path, "ci-reference-a")
    _preuve(tmp_path, "ci-reference-b", observed_head="f" * 40)
    _preuve(tmp_path, "ci-reference-c", certification_state="PARTIELLE")
    _preuve(tmp_path, "ci-reference-d", incoherences=["x"])
    (tmp_path / "ci-reference-e" / "artefacts").mkdir(parents=True)
    (tmp_path / "ci-reference-e" / "artefacts" / "ci_proof.json").write_text("{", encoding="utf-8")
    certs = m.certifications(SHA, tmp_path)
    assert [c.parent.name for c in certs] == ["ci-reference-a"]


def test_cible_courte_acceptee_si_la_tete_observee_est_le_sha(tmp_path):
    # 20/10 mesure : forge_ci_reference --sha d8e8b7b0c ecrit target_sha court, observed_head complet
    m = _module()
    _preuve(tmp_path, "ci-reference-a", target_sha=SHA[:9])
    _preuve(tmp_path, "ci-reference-b", target_sha="abc1234", observed_head=SHA)
    _preuve(tmp_path, "ci-reference-c", target_sha=SHA[:4])
    assert [c.parent.name for c in m.certifications(SHA, tmp_path)] == ["ci-reference-a"]


def test_deux_preuves_vertes_sont_ambigues(tmp_path):
    m = _module()
    _preuve(tmp_path, "ci-reference-a")
    _preuve(tmp_path, "ci-reference-b")
    assert len(m.certifications(SHA, tmp_path)) == 2  # main() refuse tout sauf exactement 1


def test_preuve_du_journal_exige_zero_echec_pour_ce_sha():
    m = _module()
    vert = "[preuve] sha=d8e8b7b0c00 x echecs=0 y erreurs=0 z etat=SUITE_COMPLETE"
    assert m.preuve_verte(vert, "d8e8b7b0c")
    assert not m.preuve_verte(vert, "abcdef123")
    assert not m.preuve_verte(vert.replace("echecs=0", "echecs=2"), "d8e8b7b0c")
    assert not m.preuve_verte(vert.replace("erreurs=0", "erreurs=1"), "d8e8b7b0c")
    assert not m.preuve_verte(vert.replace("SUITE_COMPLETE", "PARTIELLE"), "d8e8b7b0c")
    assert not m.preuve_verte("rien", "d8e8b7b0c")


def test_version_non_semver_refusee_avant_toute_lecture():
    m = _module()
    assert m.main(["--version", "0.20", "--sha", "abc", "--job", "inexistant"]) == 3


def test_promotion_sans_job_refusee():
    m = _module()
    assert m.main(["--version", "0.20.13", "--sha", "abc"]) == 3


def test_scan_compte_bloques_et_marqueurs_sans_valeur(tmp_path):
    m = _module()
    regles = tmp_path / "regles.json"
    regles.write_text(json.dumps({"profiles": {"public": {"blocked_paths": ["secret/*"]}}}), encoding="utf-8")
    tgz = tmp_path / "src.tar.gz"
    marqueur = "C:" + "/Users/" + "user" + "/x"
    with tarfile.open(tgz, "w:gz") as t:
        for nom, data in (("nokido/secret/a.txt", b"x"), ("nokido/ok.py", b"print(1)"),
                          ("nokido/fuite.md", marqueur.encode())):
            info = tarfile.TarInfo(nom)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    s = m.scan_tarball(str(tgz), regles)
    assert s["fichiers"] == 3
    assert s["sous_blocked_paths"] == 1
    assert s["marques"] == [("fuite.md", "owner")]
    assert marqueur not in json.dumps(s)
