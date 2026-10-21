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
                                 "qdrant-windows-x64", "qdrant-linux-x64", "qdrant-macos-arm64", "qdrant-macos-x64",
                                 "caddy-windows-x64", "caddy-linux-x64", "caddy-macos-arm64", "caddy-macos-x64",
                                 "ollama-windows-x64", "ollama-linux-x64", "ollama-macos-arm64", "ollama-macos-x64"])
def test_les_composants_telecharges_sont_epingles_au_manifeste(cid):
    c = _module().composant("local-llm", cid)
    assert c["source"] == "url" and c["url"].startswith("https://")
    assert re.fullmatch(r"[0-9a-f]{64}", c["sha256"]) and isinstance(c["taille"], int) and c["taille"] > 0


def test_un_composant_non_epingle_n_est_jamais_telecharge():
    with pytest.raises(LookupError):
        _module().composant("local-llm", "bitnet_b1_58.gguf")


def test_l_installation_complete_est_testee_sur_les_3_os():
    """2026-10-16 : le job `installation` (protheses, embedder, pack, RAG, hub) ne tournait que sous Windows et Ubuntu
    (les jobs paquet et organisme couvraient deja macOS). Owner : « livrer des versions sur les 3 OS pleinement
    fonctionnelles »."""
    texte = WORKFLOW.read_text(encoding="utf-8")
    bloc = texte.split("\n  installation:", 1)[1].split("\n  paquet", 1)[0]
    m = re.search(r"os:\s*\[([^\]]+)\]", bloc)
    assert m, "matrice du job installation introuvable"
    oss = {o.strip() for o in m.group(1).split(",")}
    assert {"windows-latest", "ubuntu-24.04", "macos-latest"} <= oss, oss


def test_la_repetition_teste_le_pack_CANDIDAT_de_la_release_brouillon():
    """2026-10-16 : 0.20.12 a ete essayee avec le pack 0.20.9 (defaut fige) -- vert sur un objet qui n'etait pas le
    livrable. Une repetition (push) lit la release BROUILLON de la version du snapshot ; absente = rouge ; installation
    et paquet importent CE fichier (sha verifie) ; seul ce job a contents: write ; plus aucun defaut fige."""
    # le CODE du workflow, sans ses commentaires : ils racontent l'incident et citent ce qu'on interdit (un instrument
    # ne lit pas son propre recit -- 1re version de ce NR piegee deux fois par eux)
    texte = "\n".join(lig for lig in WORKFLOW.read_text(encoding="utf-8").splitlines()
                      if not lig.strip().startswith("#"))
    assert not re.search(r"""default:\s*["']\d+\.\d+\.\d+["']""", texte), "version figee en defaut d'input"
    assert not re.search(r"""\|\|\s*'\d+\.\d+\.\d+'""", texte), "version figee en repli d'expression"
    job = texte.split("\n  pack-candidat:", 1)[1].split("\n  installation:", 1)[0]
    assert "if: github.event_name == 'push'" in job
    assert 'select(.draft and .tag_name == \\"v$V\\")' in job and "exit 1" in job
    assert "contents: write" in job and texte.count("contents: write") == 1, "ecriture limitee au job pack-candidat"
    for nom in ("installation", "paquet"):
        bloc = texte.split("\n  %s:" % nom, 1)[1].split("\n  # ", 1)[0]
        assert "needs: [pack-candidat]" in bloc and "NOKIDO_PACK_FICHIER" in bloc and "NOKIDO_PACK_SHA256" in bloc, nom
        assert "name: pack-candidat" in bloc, "%s : le pack candidat est recupere" % nom


def test_le_workflow_reste_sur_runners_heberges_sans_secret():
    texte = WORKFLOW.read_text(encoding="utf-8")
    assert "self-hosted" not in texte, "du code public ne tourne jamais sur le runner du poste owner"
    assert re.search(r"(?m)^permissions:\s*\n\s+contents: read\s*$", texte)
    assert "secrets." not in texte
    assert "windows-latest" in texte and "ubuntu-24.04" in texte
    assert "tools/forge_install_acceptance.py" in texte
    assert re.search(r'push:\s*\n\s+branches:\s*\["essai/\*\*"\]', texte), "push limite aux branches essai/**"
    assert "tags:" not in texte, "une repetition ne se declenche jamais sur un tag de release"
    for ligne in re.findall(r"uses:\s*(\S+)", texte):
        assert re.search(r"@[0-9a-f]{40}$", ligne), "action non epinglee par sha : %s" % ligne


def test_aucun_workflow_ne_vise_ubuntu_latest():
    """16/10 : GitHub annonce (annotation du run public 38851827198, runner-images#14748) que `ubuntu-latest`
    migre vers Ubuntu 26 a partir du 19/10/2026. Un libelle flottant change la machine SOUS la CI sans commit :
    un rouge du lendemain ne se rattacherait a aucun changement. Les runners Ubuntu sont EPINGLES (`ubuntu-24.04`) ;
    passer a 26 sera un commit, apres un essai dedie. Seules les lignes `runs-on:` / `os:` comptent (pas les
    commentaires historiques)."""
    fautifs = []
    for wf in sorted((RACINE / ".github" / "workflows").glob("*.yml")):
        for n, ligne in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            code = ligne.split("#", 1)[0]
            if "ubuntu-latest" in code and re.search(r"\b(runs-on|os)\b", code):
                fautifs.append("%s:%d" % (wf.name, n))
    assert not fautifs, "runner Ubuntu non epingle : %s" % fautifs


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
    assert seq.index("_caddy") < seq.index("_organisme") and seq.index("_ollama_natif") < seq.index("_organisme")
    assert seq.index("_dispatcher") < seq.index("_organisme"), "le dispatcher Go est construit avant le superviseur"
    # 2026-10-09 : le banc appelle l'installeur PRODUIT (tools/forge_composants.py) -- il mesure le produit.
    for appel in ("poser_llama", "poser_qdrant", "poser_caddy", "poser_ollama", "construire_dispatcher"):
        assert "composants().%s(" % appel in src, appel
    produit = (m.ROOT / "tools" / "forge_composants.py").read_text(encoding="utf-8")
    assert '"tools/forge_gen_tls_cert.py"' in produit and '"tools/forge_tls_caddy.py", "--write-config"' in produit, (
        "certificat et Caddyfile par les outils du produit, jamais par un doublon")


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
    for os_ in ("windows-latest", "ubuntu-24.04", "macos-latest"):
        assert os_ in bloc, "%s absent du job organisme" % os_


def test_l_etape_imports_suit_les_lanceurs_delegants():
    # Mesure 5 (run 38162661913) : GithubBridgeMCP et PairMCP morts sur « No module named 'mcp' », que l'etape ne
    # voyait pas -- forge_bridge_launch.py lance sa cible en sous-processus.
    m = _module()
    services = [
        {"name": "Github", "cmd": "${PYTHON}", "args": ["tools/forge_bridge_launch.py", "--port", "8791"]},
        {"name": "Pair", "cmd": "${PYTHON}", "args": ["tools/forge_bridge_launch.py", "--passerelle", "pair"]},
    ]
    entrees, _ = m.entrees_des_services(services)
    noms = {k: [p.name for p in v] for k, v in entrees.items()}
    assert "forge_github_bridge_mcp.py" in noms["Github"]
    assert "forge_pair_mcp.py" in noms["Pair"] and "forge_github_bridge_mcp.py" not in noms["Pair"]
    vus = m.imports_tiers(m.ROOT / "tools" / "forge_github_bridge_mcp.py", m._locaux_du_depot())
    assert "mcp" in vus["requis"] | vus["paresseux"], "le SDK mcp de la passerelle doit etre vu par l'etape"


def test_un_hub_mort_entre_deux_etapes_dit_son_code_de_sortie(tmp_path, monkeypatch):
    # Mesure 6 (run 38208586691, tentative 1) : `rag_hub` refuse 26 s apres `hub` PASS, journal du hub coupe net.
    # Le handle du hub etait jete : le FAIL ne disait ni s'il vivait, ni de quoi il etait mort.
    import subprocess
    import sys
    m = _module()
    lances = {}

    def faux_demarrer(cmd, journal, env=None):
        lances["env"] = env or {}
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("derniere ligne du hub\n", encoding="utf-8")
        p = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
        p.wait(timeout=30)
        return p

    monkeypatch.setattr(m, "RUNTIME", tmp_path)
    monkeypatch.setattr(m, "demarrer", faux_demarrer)
    monkeypatch.setattr(m, "attendre_http", lambda url, delai: 200)
    m.R.update({"dependances": {"etat": "PASS"}, "pack": {"etat": "PASS"}})
    m._PROCESSUS.clear()
    m._hub()
    assert lances["env"].get("PYTHONUNBUFFERED") == "1" and lances["env"].get("PYTHONFAULTHANDLER") == "1"

    def refuse(*a, **k):
        raise m.urllib.error.URLError("connexion refusee")

    monkeypatch.setattr(m.urllib.request, "urlopen", refuse)
    m._rag_hub()
    detail = m.R["rag_hub"]["detail"]
    assert m.R["rag_hub"]["etat"] == "FAIL"
    assert "hub MORT rc=3" in detail and "derniere ligne du hub" in detail
    assert "jamais demarre ici" in m.etat_processus("autre", tmp_path / "absent.log")
