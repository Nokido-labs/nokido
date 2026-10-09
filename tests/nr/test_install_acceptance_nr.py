"""NR -- l'acceptation de l'installation complete (tools/forge_install_acceptance.py + son workflow), 2026-10-07.

Ce qui est garde :
  * une etape dont une dependance n'est pas PASS devient NON_TESTE (avec la raison), une exception devient FAIL,
    et le rapport continue -- un passage dit tout l'ecart ;
  * les identifiants que le script telecharge EXISTENT, epingles, dans distribution/packs/local-llm.toml (sinon le
    runner partirait chercher un composant que le manifeste ne connait pas) ;
  * le workflow ne tourne que sur des runners HEBERGES, en lecture seule, sans secret : du code public n'entre
    jamais sur le runner auto-heberge du poste owner.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
WORKFLOW = RACINE / ".github" / "workflows" / "installation-complete.yml"


def _module():
    spec = importlib.util.spec_from_file_location("acceptance_nr", RACINE / "tools" / "forge_install_acceptance.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.R.clear()
    return m


def test_une_dependance_en_echec_rend_non_teste_et_le_rapport_continue():
    m = _module()

    @m.etape("a")
    def a():
        raise RuntimeError("panne simulee")

    @m.etape("b", "a")
    def b():
        return "PASS", "ne doit pas tourner"

    @m.etape("c")
    def c():
        return "PASS", "independante"

    for f in (a, b, c):
        f()
    assert m.R["a"]["etat"] == "FAIL" and "panne simulee" in m.R["a"]["detail"]
    assert m.R["b"] == {"etat": "NON_TESTE", "detail": "depend de a"}
    assert m.R["c"]["etat"] == "PASS"
    assert "| b | NON_TESTE | depend de a |" in m.resume()


@pytest.mark.parametrize("cid", ["llama-server-windows-x64-cpu", "llama-server-linux-x64-cpu",
                                 "llama-server-macos-arm64-cpu", "llama-server-macos-x64-cpu",
                                 "bge-m3-Q8_0.gguf", "bge-reranker-v2-m3-Q8_0.gguf",
                                 "qdrant-windows-x64", "qdrant-linux-x64", "qdrant-macos-arm64", "qdrant-macos-x64"])
def test_les_composants_telecharges_sont_epingles_au_manifeste(cid):
    c = _module().composant("local-llm", cid)
    assert c["source"] == "url" and c["url"].startswith("https://")
    assert re.fullmatch(r"[0-9a-f]{64}", c["sha256"]) and isinstance(c["taille"], int) and c["taille"] > 0


def test_un_composant_non_epingle_n_est_jamais_telecharge():
    with pytest.raises(LookupError):
        _module().composant("local-llm", "bitnet_b1_58.gguf")


def test_le_workflow_reste_sur_runners_heberges_sans_secret():
    texte = WORKFLOW.read_text(encoding="utf-8")
    assert "self-hosted" not in texte, "du code public ne tourne jamais sur le runner du poste owner"
    assert re.search(r"(?m)^permissions:\s*\n\s+contents: read\s*$", texte)
    assert "secrets." not in texte
    assert "windows-latest" in texte and "ubuntu-latest" in texte
    assert "tools/forge_install_acceptance.py" in texte
    assert re.search(r'push:\s*\n\s+branches:\s*\["essai/\*\*"\]', texte), "push limite aux branches essai/**"
    assert "tags:" not in texte, "une repetition ne se declenche jamais sur un tag de release"
    for ligne in re.findall(r"uses:\s*(\S+)", texte):
        assert re.search(r"@[0-9a-f]{40}$", ligne), "action non epinglee par sha : %s" % ligne


def test_le_promoteur_embarque_le_workflow_dans_le_depot_public():
    src = (RACINE / "tools" / "forge_dist_publish.py").read_text(encoding="utf-8")
    assert '".github/workflows/installation-complete.yml"' in src


# --- Organisme COMPLET sur machine vierge (owner 08/10 : « aucune concession sur les services », 3 OS) ---------

def test_la_plateforme_macos_est_reconnue():
    m = _module()
    assert m.plateforme("Darwin", "arm64", False) == "macos-arm64"
    assert m.plateforme("Darwin", "x86_64", False) == "macos-x64"
    assert m.plateforme("Linux", "x86_64", False) == "linux-x64"
    assert m.plateforme("Windows", "AMD64", True) == "windows-x64"


@pytest.mark.parametrize("entree,attendu", [
    ({"status": "running", "pid": 42, "restarts": 0}, "TOURNE"),
    ({"status": "running", "pid": None, "restarts": 0}, "ECHEC"),  # running sans pid n'est pas une preuve de vie
    ({"status": "sleeping", "pid": None, "restarts": 0}, "ENDORMI"),
    ({"status": "starting", "pid": None, "restarts": 0}, "DEMARRAGE"),
    ({"status": "restarting", "pid": None, "restarts": 4}, "BOUCLE"),
    ({"status": "quarantine", "pid": None, "restarts": 5}, "ECHEC"),
    ({"status": "degraded", "pid": 7, "restarts": 0}, "ECHEC"),
    ({"status": "stopped", "pid": None, "restarts": 1}, "ECHEC"),
    ({"status": "etat_inconnu"}, "ILLISIBLE"),
])
def test_classement_d_un_service_du_superviseur(entree, attendu):
    assert _module().classer_service(entree) == attendu


def test_la_raison_d_un_echec_vient_du_journal_du_superviseur():
    m = _module()
    j = ("NokidoFoo: dep :8766 not open yet — defer (no crash count)\n"
         "NokidoFoo: launch failed — NotFound: %USERPROFILE%/miniforge3/python.exe\nNokidoBar: started\n")
    assert "launch failed" in m.raison_du_journal("NokidoFoo", j)
    assert m.raison_du_journal("NokidoAbsent", j) == ""


def test_le_bilan_compte_chaque_service_actif_et_nomme_les_absents():
    m = _module()
    statut = {"services": {"A": {"status": "running", "pid": 1, "restarts": 0},
                           "B": {"status": "quarantine", "pid": None, "restarts": 5}}}
    b = m.bilan_organisme(statut, "B: launch failed — introuvable\n", ["A", "B", "C"])
    assert b["compte"] == {"TOURNE": 1, "ECHEC": 1, "ABSENT": 1}
    assert b["services"]["C"]["etat"] == "ABSENT"
    assert "introuvable" in b["services"]["B"]["raison"]


def test_un_service_propre_au_poste_non_demarre_n_est_pas_un_absent():
    # Decision owner du 08/10 : NokidoCIRunner est propre au poste ; sur une autre machine son absence est voulue.
    m = _module()
    statut = {"services": {"A": {"status": "running", "pid": 1, "restarts": 0}}}
    b = m.bilan_organisme(statut, "", ["A", "Runner", "C"], {"Runner"})
    assert b["services"]["Runner"]["etat"] == "PROPRE_AU_POSTE" and b["services"]["C"]["etat"] == "ABSENT"
    assert b["services"]["Runner"]["raison"] == ""
    statut["services"]["Runner"] = {"status": "running", "pid": 2, "restarts": 0}
    b = m.bilan_organisme(statut, "", ["A", "Runner"], {"Runner"})
    assert b["services"]["Runner"]["etat"] == "TOURNE", "demarre, il est classe comme les autres"


def test_l_organisme_installe_ses_dependances_et_amorce_la_base_avant_le_superviseur():
    m = _module()
    texte = (m.ROOT / "requirements-organisme.txt").read_text(encoding="utf-8")
    assert texte.splitlines()[0].startswith("#") and "-r requirements.txt" in texte
    for dep in ("pywin32==", "qdrant-client==", "textual-serve==", "torch=="):
        assert dep in texte, dep
    assert 'pywin32==311; sys_platform == "win32"' in texte, "pywin32 n'existe que sous Windows"
    assert m._ligne_torch().startswith("torch==")
    src = (m.ROOT / "tools" / "forge_install_acceptance.py").read_text(encoding="utf-8")
    seq = [e.strip() for e in src[src.index("sequence = (_env, _deps, _deps_organisme"):].split("(", 1)[1]
           .split(")")[0].split(",")]
    assert seq.index("_base") < seq.index("_organisme") and seq.index("_deps_organisme") < seq.index("_imports"), (
        "la base et les dependances de l'organisme precedent le superviseur")
    assert seq.index("_qdrant") < seq.index("_organisme"), "le binaire Qdrant est pose avant le superviseur"


def test_la_mesure_de_l_organisme_n_echoue_pas_le_job():
    m = _module()
    m.R.update({"x": {"etat": "PASS"}, "organisme": {"etat": "MESURE"}})
    assert m.code_de_sortie() == 0
    m.R["y"] = {"etat": "FAIL"}
    assert m.code_de_sortie() == 1


def test_les_imports_tiers_sont_classes_requis_optionnel_paresseux(tmp_path):
    m = _module()
    (tmp_path / "local_b.py").write_text("import module_tiers_b_xyz\n", encoding="utf-8")
    entree = tmp_path / "entree.py"
    entree.write_text(
        "import os, json\n"
        "import module_tiers_a_xyz\n"
        "import local_b\n"
        "try:\n    import module_optionnel_xyz\nexcept ImportError:\n    pass\n"
        "def f():\n    import module_paresseux_xyz\n", encoding="utf-8")
    r = m.imports_tiers(entree, locaux={"local_b": tmp_path / "local_b.py"})
    assert r["requis"] == {"module_tiers_a_xyz", "module_tiers_b_xyz"}, "un import local au demarrage est suivi"
    assert r["optionnel"] == {"module_optionnel_xyz"} and r["paresseux"] == {"module_paresseux_xyz"}
    assert "os" not in r["requis"] and "json" not in r["requis"], "la bibliotheque standard n'est jamais comptee"


def test_les_imports_de_main_et_des_fonctions_appelees_sous_main_sont_requis(tmp_path):
    # Mesure 3 (run 37846238481) : le lanceur runAs importe pywin32 DANS main() ; classe « paresseux », le manque
    # (No module named 'win32event', 10 services) serait reste invisible au bilan.
    m = _module()
    entree = tmp_path / "lanceur.py"
    entree.write_text(
        "def main():\n    import module_main_xyz\n"
        "def demarrer():\n    import module_appele_xyz\n"
        "def outil():\n    import module_tard_xyz\n"
        "if __name__ == '__main__':\n    demarrer()\n    main()\n", encoding="utf-8")
    r = m.imports_tiers(entree, locaux={})
    assert r["requis"] == {"module_main_xyz", "module_appele_xyz"}
    assert r["paresseux"] == {"module_tard_xyz"}, "une fonction jamais appelee au demarrage reste paresseuse"


def test_le_bilan_des_imports_nomme_les_modules_manquants_par_service(tmp_path):
    m = _module()
    entree = tmp_path / "svc.py"
    entree.write_text("import json\nimport module_absent_xyz_42\n", encoding="utf-8")
    b = m.bilan_imports({"SvcA": entree}, locaux={})
    assert b["manquants_requis"] == {"module_absent_xyz_42": ["SvcA"]}
    assert b["services_bloques"] == ["SvcA"]


def test_le_workflow_mesure_l_organisme_sur_trois_os():
    texte = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"(?m)^  organisme:\s*$", texte), "job organisme absent"
    bloc = re.split(r"(?m)^  organisme:\s*$", texte, maxsplit=1)[1]
    assert "--organisme" in bloc
    for os_ in ("windows-latest", "ubuntu-latest", "macos-latest"):
        assert os_ in bloc, "%s absent du job organisme" % os_
