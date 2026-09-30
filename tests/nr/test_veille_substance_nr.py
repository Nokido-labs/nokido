# -*- coding: utf-8 -*-
"""NR 2026-09-23 — la veille n'ingere que la SUBSTANCE (decision owner, points 1-4).

Mesure sur 212 dumps (6,08 Go) : donnees/config 28,9 %, tests 13,4 %,
traductions 2,1 %, vendor 1,6 % ; teamchong/pxpipe (1 Go, 633 408 chunks deja
ingeres) etait fait de RESULTATS d'evaluation ranges en .md. V: a ete sature
deux fois dans la nuit. Refus par NATURE, nomme, comme le genere.
"""
import pytest

from nokido_agent.tools.forge_veille_intake_filter import (
    FILTRE_VERSION,
    SEUIL_DONNEES_OCTETS,
    est_hors_substance,
)


def test_tests_refuses():
    for rel in ("tests/test_x.py", "src/__tests__/a.ts", "pkg/spec/b_spec.rb",
                "fixtures/data.txt", "lib/foo_test.go", "web/a.test.tsx", "testdata/x.go"):
        assert est_hors_substance(rel, 100)[0], rel


def test_traductions_vendor_sorties_refuses():
    for rel in ("locales/fr/messages.po", "i18n/de.json", "vendor/lib/x.c",
                "third_party/zlib/inflate.c",
                "eval/deepswe/results-retry2/wasmi/out.md", "outputs/run1.md",
                "transcripts/enigma/crypto.traj", "runs/42/log.txt", "build.log"):
        assert est_hors_substance(rel, 100)[0], rel


def test_donnees_au_dela_du_seuil_refusees_petits_manifestes_gardes():
    assert est_hors_substance("data/big.json", SEUIL_DONNEES_OCTETS + 1)[0]
    assert est_hors_substance("SocialCC/data/agent.csv", SEUIL_DONNEES_OCTETS + 1)[0]
    assert est_hors_substance("package.json", 2_000) == (False, "")
    assert est_hors_substance("pyproject.toml", 3_000) == (False, "")
    assert est_hors_substance("config/app.yaml", SEUIL_DONNEES_OCTETS) == (False, "")


def test_substance_gardee():
    for rel in ("README.md", "AGENTS.md", "docs/guide.md", "src/core/engine.py",
                "crates/x/src/lib.rs", "examples/quickstart.py", "docs/testing.md"):
        assert est_hors_substance(rel, 10_000) == (False, ""), rel


def test_resume_garde_la_moelle_des_tests():
    """Owner : « ne perds pas la substantifique moelle, il faut en tirer de
    l'intelligence ». Un test ecarte laisse son CONTRAT : les noms des cas."""
    from nokido_agent.tools.forge_veille_intake_filter import RESUME_MAX, resume_hors_substance
    src = "import x\n\ndef test_wal_tronque_apres_checkpoint():\n    '''le WAL rendu'''\n" \
          "    assert 1\n\nclass TestVerrou:\n    def test_busy_timeout(self):\n        pass\n" \
          + "x = 1\n" * 5000
    r = resume_hors_substance("tests/test_db.py", src, "tests: tests/")
    assert "test_wal_tronque_apres_checkpoint" in r and "test_busy_timeout" in r
    assert "le WAL rendu" in r and len(r) <= RESUME_MAX
    js = 'describe("router", () => { it("renvoie 404 sans jeton", () => {}) })'
    assert "renvoie 404 sans jeton" in resume_hors_substance("a.test.ts", js, "tests")


def test_resume_garde_le_schema_des_donnees_et_le_bilan_des_sorties():
    from nokido_agent.tools.forge_veille_intake_filter import RESUME_MAX, resume_hors_substance
    csv = "agent,score,latence\n" + "a,1,2\n" * 20000
    r = resume_hors_substance("data/agents.csv", csv, "donnees")
    assert "agent,score,latence" in r and "20000" in r and len(r) <= RESUME_MAX
    js = '[{"id": 1, "tache": "x", "resolu": true}]' + " " * 60000
    assert "resolu" in resume_hors_substance("data/r.json", js, "donnees")
    sortie = "DEBUT run\n" + "bruit\n" * 50000 + "FINAL: 42/50 resolus\n"
    r = resume_hors_substance("eval/results/run.md", sortie, "sortie de machine")
    assert "DEBUT run" in r and "42/50 resolus" in r and len(r) <= RESUME_MAX


# Clone d'un depot LOCAL : 0,6 s seul (mesure 2026-09-29), mais > 30 s sous la charge de la CI
# complete -- pytest-timeout (methode thread) a alors tue TOUTE la suite pure (12 958 tests sans
# preuve, CI de reference 986544878). Meme remede que le 27/09 : une borne large pour CE test.
@pytest.mark.timeout(120)
def test_dump_repo_chemin_reel_resume_au_lieu_du_brut(tmp_path, monkeypatch):
    import json
    import subprocess
    from nokido_agent.tools import forge_veille_clone_ingest as ci
    depot = tmp_path / "depot"
    fichiers = {
        "README.md": "# outil\n",
        "src/core.py": "def moteur():\n    return 42\n",
        "tests/test_core.py": "def test_moteur_rend_42():\n    assert 1\n" + "# bruit\n" * 3000,
        "data/grosse.json": json.dumps([{"cle_utile": i, "etat": "x" * 50} for i in range(2000)]),
    }
    for rel, txt in fichiers.items():
        (depot / rel).parent.mkdir(parents=True, exist_ok=True)
        (depot / rel).write_text(txt, encoding="utf-8")
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(depot)]
    subprocess.run(["git", "init", "-q", str(depot)], check=True)
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-q", "-m", "fx"], check=True)
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    monkeypatch.setattr(ci, "CLONE_BASE", tmp_path / "scratch")
    out = ci.dump_repo({"nom_dump": "fx", "url": depot.as_uri(), "repo": "t/fx"})
    texte = out.read_text(encoding="utf-8")
    assert "def moteur" in texte                       # substance : integrale
    assert "test_moteur_rend_42" in texte              # moelle du test gardee
    assert "# bruit" not in texte                      # ... pas son volume
    assert "cle_utile" in texte and '"etat": "xxxxx' not in texte   # schema, pas les donnees
    man = json.loads(ci.chemin_manifeste(out).read_text(encoding="utf-8"))
    assert man["refus"]["hors_substance_resume"] == 2 and man["filtre_version"] == "3"


def test_motif_toujours_dit_et_version_filtre():
    refuse, motif = est_hors_substance("tests/a.py", 10)
    assert refuse and motif
    assert FILTRE_VERSION == "3"
