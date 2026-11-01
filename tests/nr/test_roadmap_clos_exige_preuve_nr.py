"""NR : le moteur d'etat refuse CLOS sans preuve structuree (sha git existant + NR present OU [LIVRABLE_CONTRAT])."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from tools import forge_roadmap_keeper as k  # noqa: E402


def _depot(tmp_path):
    def g(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True, text=True,
                              errors="replace").stdout.strip()
    g("init", "-q")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (tmp_path / "tests" / "nr").mkdir(parents=True)
    (tmp_path / "tests" / "nr" / "test_x_nr.py").write_text("def test_a(): pass\n")
    (tmp_path / "liv.md").write_text("rapport")
    g("add", "-A")
    g("commit", "-qm", "init")
    return g("rev-parse", "HEAD")


def test_cloture_sans_preuve_refusee_avec_motif(tmp_path):
    _depot(tmp_path)
    ok, motif = k.exiger_preuve_cloture("[OUVERT] x", "[CLOS] fini", root=tmp_path,
                                        journal=tmp_path / "j.log")
    assert not ok and "sha" in motif.lower()
    assert "refus" in (tmp_path / "j.log").read_text(encoding="utf-8").lower()


def test_sha_inexistant_refuse(tmp_path):
    _depot(tmp_path)
    ok, motif = k.exiger_preuve_cloture("[OUVERT] x", "[CLOS] sha deadbeefcafe1234 tests/nr/test_x_nr.py",
                                        root=tmp_path, journal=tmp_path / "j.log")
    assert not ok and "sha" in motif.lower()


def test_sha_existant_et_nr_present_accepte(tmp_path):
    sha = _depot(tmp_path)
    ok, motif = k.exiger_preuve_cloture("[OUVERT] x", "[CLOS] commit %s tests/nr/test_x_nr.py" % sha[:12],
                                        root=tmp_path, journal=tmp_path / "j.log")
    assert ok, motif


def test_sha_et_livrable_contrat_accepte(tmp_path):
    sha = _depot(tmp_path)
    txt = '[CLOS] %s [LIVRABLE_CONTRAT] {"livrable": "liv.md"}' % sha[:10]
    ok, motif = k.exiger_preuve_cloture("[OUVERT] x", txt, root=tmp_path, journal=tmp_path / "j.log")
    assert ok, motif


def test_contrat_au_format_canonique_de_l_executeur_accepte(tmp_path):
    """Le contrat que l'executeur emet et juge (forge_task_executor) est {"type", "chemins"} :
    la livraison d'origine ne lisait que "livrable", un format qu'aucun emetteur ne produit."""
    sha = _depot(tmp_path)
    txt = '[CLOS] %s [LIVRABLE_CONTRAT] {"type": "fichier", "chemins": ["liv.md"]}' % sha[:10]
    ok, motif = k.exiger_preuve_cloture("[OUVERT] x", txt, root=tmp_path, journal=tmp_path / "j.log")
    assert ok, motif


def _commit_sans_test(tmp_path):
    (tmp_path / "doc.md").write_text("doc")
    for a in (("add", "doc.md"), ("commit", "-qm", "doc seule")):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True,
                          errors="replace").stdout.strip()


def test_sha_d_un_commit_sans_test_ni_livrable_refuse(tmp_path):
    _depot(tmp_path)
    sha = _commit_sans_test(tmp_path)
    ok, motif = k.exiger_preuve_cloture("[OUVERT] x", "[CLOS] %s" % sha[:10], root=tmp_path,
                                        journal=tmp_path / "j.log")
    assert not ok and "nr" in motif.lower()


def test_sha_d_un_commit_qui_porte_son_nr_suffit(tmp_path):
    """Recensement 24/10 : 112/127 CLOS sans preuve, dont des items dont les commits PORTENT leurs NR
    (1bcbb5416, 25f2c1d6e) sans que le texte nomme le fichier. Le NR est dans le commit, pas dans la phrase."""
    sha = _depot(tmp_path)  # le commit initial contient tests/nr/test_x_nr.py
    ok, motif = k.exiger_preuve_cloture("[OUVERT] x", "[CLOS] %s" % sha[:10], root=tmp_path,
                                        journal=tmp_path / "j.log")
    assert ok, motif


def test_sha_hex_dans_nom_de_test_nr_ne_suffit_pas_sans_sha(tmp_path):
    _depot(tmp_path)
    ok, _ = k.preuve_cloture("[CLOS] tests/nr/test_x_nr.py", root=tmp_path)
    assert not ok


def test_ancien_clos_sans_preuve_affiche_et_inchange(tmp_path):
    _depot(tmp_path)
    texte = "[CLOS] ancien"
    assert k.etat_affiche(texte, root=tmp_path) == "CLOS_SANS_PREUVE"
    assert texte == "[CLOS] ancien"
    assert k.etat_affiche("[OUVERT] x", root=tmp_path) == "OUVERT"


def test_transition_hors_clos_ou_deja_clos_non_gardee(tmp_path):
    _depot(tmp_path)
    assert k.exiger_preuve_cloture("[OUVERT] a", "[PARTIEL] b", root=tmp_path, journal=tmp_path / "j")[0]
    assert k.exiger_preuve_cloture("[CLOS] a", "[CLOS] b", root=tmp_path, journal=tmp_path / "j")[0]
