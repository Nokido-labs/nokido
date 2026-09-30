"""NR — outils d'archeologie, d'audit et de recuperation (lot du 2026-08-18).

POURQUOI. Le cliquet de couverture (`test_nr_coverage_ratchet_nr`) a mordu au
run GHA 32077672167 : vingt modules ajoutes en trois jours, aucun test. Le gate
avait raison — ces outils portent des VERDICTS (« cette capacite est morte »,
« cette memoire est perimee », « cette tuile ment ») sur lesquels des decisions
se prennent. Un verdict que rien ne teste est une opinion.

Chaque test verifie un EFFET, jamais un import. Les tests qui touchent du git
construisent leur propre depot dans `tmp_path` : lire le working tree ferait
passer le test en local et le ferait echouer en CI sur un arbre propre — mesure
du 2026-08-15, deja payee une fois.

⚠️ Trois modules n'exposent AUCUNE fonction pure (`forge_veille_gap_run`,
`forge_fix_worktree_link`, `forge_mutation_run`) : ils sont couverts par un
contrat STRUCTUREL — ce que le module doit continuer a faire, lu dans sa source.
C'est plus faible qu'un test d'effet, et c'est ecrit ici plutot que masque.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (l.67)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _zone in ("tools", "app"):
    _p = str(ROOT / _zone)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _charger(nom: str, zone: str = "tools"):
    """Charge un module par son chemin. Un ImportError ECHOUE le test : un outil
    qu'on ne peut plus importer est casse, pas 'a sauter'."""
    chemin = ROOT / zone / (nom + ".py")
    assert chemin.exists(), "module absent : %s" % chemin
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    spec.loader.exec_module(mod)
    return mod


def _source(nom: str, zone: str = "tools") -> str:
    return (ROOT / zone / (nom + ".py")).read_text(encoding="utf-8", errors="replace")


def _depot_git(tmp_path: Path, branche: str = "principal") -> Path:
    """Un vrai depot git, minuscule, dans tmp_path — jamais le working tree."""
    d = tmp_path / "depot"
    d.mkdir()
    env = dict(os.environ)
    env.update(GIT_AUTHOR_NAME="nr", GIT_AUTHOR_EMAIL="nr@local",
               GIT_COMMITTER_NAME="nr", GIT_COMMITTER_EMAIL="nr@local")

    def _g(*args):
        # errors="replace" : un subprocess en mode texte sans lui plante son
        # _readerthread des qu'une sortie n'est pas de l'UTF-8 propre
        # (anti-regression incident 47 Go).
        return subprocess.run(["git", "-C", str(d), *args], capture_output=True,
                              text=True, errors="replace", env=env, timeout=60)

    _g("init", "-q", "-b", branche)
    (d / "fichier.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    _g("add", "-A")
    _g("commit", "-q", "-m", "feat: naissance")
    return d


# ── socle commun ─────────────────────────────────────────────────────────────

def test_socle_bruit_distingue_vendored_et_patrimoine():
    s = _charger("forge_archeo_socle")
    assert s.est_bruit("x/node_modules/a.py") is True
    assert s.est_bruit("app/forge_rag_engine.py") is False
    # bruit parametrable : chaque outil a son idee du bruit
    assert s.bruit_motifs("d/tmp_essai.py", (), ("tmp_",)) is True
    assert s.bruit_motifs("d/forge_x.py", (), ("tmp_",)) is False


def test_socle_port_ouvert_ne_ment_pas_sur_un_port_ferme():
    s = _charger("forge_archeo_socle")
    # port 1 : reserve, jamais servi par la stack Nokido
    assert s.port_ouvert(1, timeout=0.2) is False


def test_socle_liens_memoire_lit_les_citations_et_tolere_l_absence(tmp_path):
    s = _charger("forge_archeo_socle")
    idx = tmp_path / "MEMORY.md"
    idx.write_text("- [Titre](une_memoire.md) — accroche\n- rien\n", encoding="utf-8")
    assert s.liens_memoire(idx) == {"une_memoire.md"}
    assert s.liens_memoire(tmp_path / "ABSENT.md") == set()


def test_socle_noms_par_regroupe_par_verdict():
    s = _charger("forge_archeo_socle")
    d = {"b": {"etat": "MORT"}, "a": {"etat": "MORT"}, "c": {"etat": "VIF"}}
    assert s.noms_par(d, "etat", "MORT") == ["a", "b"]
    assert s.noms_par(d, "etat", "INEXISTANT") == []


def test_socle_git_rend_vide_hors_depot_et_lit_un_vrai_depot(tmp_path):
    s = _charger("forge_archeo_socle")
    d = _depot_git(tmp_path)
    assert s.git(str(d), "rev-parse", "--git-dir").strip()
    # ⚠️ un dossier VIDE ne suffit pas : `--basetemp` peut tomber DANS le
    # checkout, et git remonte alors au depot parent — le test rendait le .git
    # de Nokido. Seul un chemin INEXISTANT prouve l'echec.
    absent = tmp_path / "chemin" / "inexistant"
    assert s.git(str(absent), "rev-parse", "--git-dir") == ""
    # git_rc distingue "vide" de "echec" — c'est sa raison d'etre
    rc, _ = s.git_rc(str(absent), "rev-parse", "--git-dir")
    assert rc != 0


def test_socle_ecrire_json_cree_l_arborescence_et_relit_identique(tmp_path):
    s = _charger("forge_archeo_socle")
    cible = tmp_path / "sous" / "dossier" / "r.json"
    rel = s.ecrire_json(str(cible), {"a": 1, "b": ["x"]})
    assert cible.exists() and isinstance(rel, str)
    assert json.loads(cible.read_text(encoding="utf-8")) == {"a": 1, "b": ["x"]}


def test_socle_sortie_tire_son_code_du_contenu_pas_du_fait_d_avoir_tourne(capsys):
    s = _charger("forge_archeo_socle")
    res = {"defauts": ["x"]}
    code = s.sortie(res, True, lambda r: None, lambda r: bool(r["defauts"]))
    assert code == 1
    assert "defauts" in capsys.readouterr().out       # le JSON a bien ete emis
    assert s.sortie({"defauts": []}, True, lambda r: None, lambda r: bool(r["defauts"])) == 0


def test_socle_decouvrir_depots_rend_les_refus_au_lieu_de_les_avaler():
    s = _charger("forge_archeo_socle")
    depots, refuses = s.decouvrir_depots(extra=("fantome=Z:/inexistant/xyz",))
    assert "fantome" not in depots
    assert "fantome" in refuses and refuses["fantome"]


# ── archeologie et histoire ──────────────────────────────────────────────────

def test_history_census_classe_les_prefixes_de_commit():
    m = _charger("forge_history_census")
    assert m._prefixe("feat(ci): x") == "feat"
    assert m._prefixe("FIX: y") == "fix"
    assert m._prefixe("bidule sans prefixe") == "autre"


def test_archaeology_ecarte_le_bruit_mais_garde_le_patrimoine():
    m = _charger("forge_archaeology")
    assert m._est_bruit("app/_attic/vieux.py") is True
    assert m._est_bruit("tools/tmp_essai.py") is True
    assert m._est_bruit("app/forge_rag_engine.py") is False


def test_constituent_archaeology_ecarte_les_tests_pas_le_code():
    m = _charger("forge_constituent_archaeology")
    assert m._est_bruit("tests/test_x.py") is True
    assert m._est_bruit("app/forge_x.py") is False


def _appels_au_niveau_module(src: str) -> list:
    """[(appelee, nom_utilise_defini_trop_tard)] — ordre de definition fautif.

    Une fonction appelee AU NIVEAU MODULE ne voit que ce qui est deja defini.
    `forge_constituent_archaeology` appelait `_depots_defaut()` a l'import, et
    sa branche d'erreur utilisait `_log`, defini 35 lignes plus bas : sur un
    checkout neuf (pas de sandbox/archaeology_clones), le module levait
    NameError et devenait inimportable. Vert en local, rouge en CI — trouve par
    le run 32080591223.

    ⚠️ Un test qui appelle la fonction APRES l'import ne voit rien : a ce
    moment tout le module est charge. Seule la LECTURE DE L'ORDRE le montre.
    """
    arbre = ast.parse(src)
    fns = {n.name: n for n in arbre.body if isinstance(n, ast.FunctionDef)}
    fautes = []
    for stmt in arbre.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Import, ast.ImportFrom)):
            continue
        for noeud in ast.walk(stmt):
            if not (isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)):
                continue
            appelee = fns.get(noeud.func.id)
            if appelee is None:
                continue
            for interne in ast.walk(appelee):
                if (isinstance(interne, ast.Name) and isinstance(interne.ctx, ast.Load)
                        and interne.id in fns
                        and fns[interne.id].lineno > stmt.lineno):
                    fautes.append((noeud.func.id, interne.id))
    return fautes


@pytest.mark.parametrize("module", [
    "forge_archeo_socle", "forge_constituent_archaeology", "forge_archaeology",
    "forge_history_census", "forge_orphan_branches", "forge_blind_spot_index",
    "forge_capability_contracts", "forge_ui_coherence", "forge_memory_forensics",
    "forge_provider_reachability", "forge_capability_execution_trace",
])
def test_aucun_appel_a_l_import_ne_vise_une_fonction_definie_plus_bas(module):
    fautes = _appels_au_niveau_module(_source(module))
    assert not fautes, (
        "%s : appel au niveau module vers une fonction qui en utilise une autre "
        "definie PLUS BAS -> NameError a l'import : %s" % (module, fautes))


def test_le_garde_d_ordre_sait_mordre():
    """Un garde qui ne peut pas echouer ne garde rien : on lui donne le defaut
    EXACT qui a rougi la CI, et il doit le designer."""
    fautif = ("def premiere():\n"
              "    try:\n"
              "        pass\n"
              "    except OSError:\n"
              "        tardive('bing')\n"
              "\n"
              "\nVALEUR = premiere()\n"
              "\n\ndef tardive(m):\n"
              "    print(m)\n")
    assert _appels_au_niveau_module(fautif) == [("premiere", "tardive")]
    # et l'ordre correct passe
    sain = ("def tardive(m):\n    print(m)\n\n\ndef premiere():\n"
            "    tardive('ok')\n\n\nVALEUR = premiere()\n")
    assert _appels_au_niveau_module(sain) == []


def test_constituent_archaeology_lit_vraiment_un_historique(tmp_path):
    """Appelle `supprimes()` pour de bon : ce chemin utilise subprocess.Popen, et
    un import retire au refactor n'echoue QU'ICI — pas a l'import du module."""
    m = _charger("forge_constituent_archaeology")
    d = _depot_git(tmp_path)
    env = dict(os.environ)
    env.update(GIT_AUTHOR_NAME="nr", GIT_AUTHOR_EMAIL="nr@local",
               GIT_COMMITTER_NAME="nr", GIT_COMMITTER_EMAIL="nr@local")

    def _g(*a):
        return subprocess.run(["git", "-C", str(d), *a], capture_output=True,
                              text=True, errors="replace", env=env, timeout=60)

    # naissance puis mort d'un constituant nommable (>= 3 car., cf est_nom_de_code)
    (d / "fichier.py").write_text(
        "def a():\n    return 1\n\n\ndef capacite_perdue():\n    return 2\n",
        encoding="utf-8")
    _g("commit", "-qam", "feat: ajoute capacite_perdue")
    (d / "fichier.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    _g("commit", "-qam", "refactor: retire capacite_perdue")

    res, err = m.supprimes(str(d), 100_000)
    assert err == "" and res is not None, "streaming de git log en echec : %s" % err
    assert "capacite_perdue" in [c["nom"] for c in res], (
        "une definition supprimee doit etre vue par l'archeologie des constituants")


def test_orphan_branches_prend_le_HEAD_pour_reference_pas_main(tmp_path):
    m = _charger("forge_orphan_branches")
    d = _depot_git(tmp_path, branche="alpha")
    assert m.principale(str(d)) == "alpha"


def test_orphan_branches_voit_une_branche_non_mergee(tmp_path):
    m = _charger("forge_orphan_branches")
    d = _depot_git(tmp_path, branche="alpha")
    env = dict(os.environ)
    env.update(GIT_AUTHOR_NAME="nr", GIT_AUTHOR_EMAIL="nr@local",
               GIT_COMMITTER_NAME="nr", GIT_COMMITTER_EMAIL="nr@local")

    def _g(*a):
        return subprocess.run(["git", "-C", str(d), *a], capture_output=True,
                              text=True, errors="replace", env=env, timeout=60)

    _g("checkout", "-q", "-b", "wip/oublie")
    (d / "perdu.py").write_text("def perdu():\n    return 2\n", encoding="utf-8")
    _g("add", "-A")
    _g("commit", "-q", "-m", "wip: capacite jamais mergee")
    _g("checkout", "-q", "alpha")

    r = m.analyser("tmp", str(d))
    assert r["principale"] == "alpha"
    assert "wip/oublie" in r["branches"]
    assert "perdu.py" in r["branches"]["wip/oublie"]["fichiers_code_exclusifs"]


def test_blind_spot_index_ne_perd_aucune_ligne_en_decoupant():
    m = _charger("forge_blind_spot_index")
    texte = "".join("ligne unique numero %04d\n" % i for i in range(400))
    morceaux = m.decouper(texte)
    assert len(morceaux) > 1, "un texte de 10 ko doit produire plusieurs chunks"
    colle = "\n".join(morceaux)
    for sonde in ("numero 0000", "numero 0199", "numero 0399"):
        assert sonde in colle, "chunking perdu : %s absent" % sonde


def test_blind_spot_index_ecarte_le_bruit():
    m = _charger("forge_blind_spot_index")
    assert m._est_bruit("ctf/node_modules/x.py") is True
    assert m._est_bruit("ctf/tools/laforge_recon_server.py") is False


def test_capability_recovery_decrit_une_capacite_par_AST_sans_l_executer():
    m = _charger("forge_capability_recovery")
    src = ('"""Fait la chose."""\nimport os\n\n\n'
           'class Moteur:\n    pass\n\n\ndef demarrer(x):\n    return x\n')
    d = m.decrire(src)
    assert d["docstring"].startswith("Fait la chose")
    # les classes portent leurs methodes : {"nom": ..., "methodes": [...]}
    assert "Moteur" in [c["nom"] for c in d["classes"]]
    assert "demarrer" in json.dumps(d["fonctions"])
    # un source non parsable est DIT, jamais avale
    assert "erreur_ast" in m.decrire("def (((")


def test_recover_from_branch_rend_vide_sur_une_ref_inexistante():
    m = _charger("forge_recover_from_branch")
    assert m._show("ref_qui_n_existe_pas_9999", "app/forge_rag_engine.py") == ""


# ── capacites et atteignabilite ──────────────────────────────────────────────

def test_capability_contracts_declare_dormant_un_port_ferme():
    m = _charger("forge_capability_contracts")
    r = m.verifier_une("essai", {"port": 1, "organe": "T", "sante": "/"})
    assert r["etat"] == "dormant"
    assert r["transport"] is False
    # un port ferme ne permet AUCUN verdict applicatif : ni vrai, ni faux
    assert r["applicatif"] is None and r["capacite_ok"] is None


def test_capability_contracts_couvre_chaque_capacite_avec_un_organe_et_une_sonde():
    m = _charger("forge_capability_contracts")
    assert m.CONTRATS, "table de contrats vide = surface non couverte"
    for nom, c in m.CONTRATS.items():
        assert c.get("organe"), "%s sans organe" % nom
        assert c.get("port") and c.get("sante"), "%s sans sonde" % nom


def test_capability_crosswalk_ne_declare_pas_teste_un_nom_qui_n_existe_pas():
    """⚠️ Le nom est ASSEMBLE a l'execution, jamais ecrit en clair : ecrit en
    litteral, il se retrouve dans CE fichier, que le crosswalk scanne — et
    l'outil se serait donne raison sur sa propre donnee d'entree. C'est le
    faux-vert exact que son docstring raconte, reproduit ici par accident."""
    m = _charger("forge_capability_crosswalk")
    fantome = "forge_" + "capacite" + "_absente_" + "9999"
    assert not m._mentions_tests([fantome]).get(fantome)


def test_capability_execution_trace_nomme_toutes_ses_transitions_de_mort():
    """Le tracer dit OU meurt un slot. Si un etat disparait de la source, des
    morts deviennent invisibles sans qu'aucun compteur ne bouge."""
    src = _source("forge_capability_execution_trace")
    for etat in ("GHOST", "UNREACHED", "CRED_UNWIRED", "CRED_INVALID",
                 "LIVE_UNVERIFIED", "LOCAL"):
        assert etat in src, "transition %s disparue du tracer" % etat
    assert "noms_par" in src, "le regroupement doit venir du socle, pas d'une copie"


def test_provider_reachability_regroupe_par_verdict_via_le_socle():
    m = _charger("forge_provider_reachability")
    d = {"p1": {"verdict": "SANS_SLOT_SANS_CLE"}, "p2": {"verdict": "AUTRE"}}
    assert m.noms_par(d, "verdict", "SANS_SLOT_SANS_CLE") == ["p1"]


def test_ui_coherence_indexe_le_contexte_de_ligne_pas_le_nom_de_fichier():
    """Premiere version : elle cherchait le nom de la surface dans le NOM du
    fichier et ne trouvait donc jamais rien — un detecteur toujours vert."""
    m = _charger("forge_ui_coherence")
    cites = m._ports_cites_dans_ui()
    assert isinstance(cites, dict)
    for port, contextes in cites.items():
        assert isinstance(port, int) and contextes


# ── memoire ──────────────────────────────────────────────────────────────────

def test_memory_forensics_signale_une_memoire_citee_mais_absente(tmp_path):
    m = _charger("forge_memory_forensics")
    (tmp_path / "MEMORY.md").write_text(
        "- [Vivante](presente.md) — ok\n- [Morte](disparue.md) — trou\n",
        encoding="utf-8")
    (tmp_path / "presente.md").write_text("contenu\n", encoding="utf-8")
    rapport = json.dumps(m.analyser(tmp_path), default=str)
    assert "disparue.md" in rapport, "une memoire citee et absente doit ressortir"


def test_memory_compactor_et_forensics_lisent_les_liens_a_l_identique(tmp_path):
    """Les deux modules partagent desormais l'extraction du socle : le test
    verrouille cette unicite, qui etait une duplication a l'octet pres."""
    c = _charger("forge_memory_compactor")
    f = _charger("forge_memory_forensics")
    idx = tmp_path / "MEMORY.md"
    idx.write_text("- [A](a.md)\n- [B](b.md)\n", encoding="utf-8")
    assert c._index_liens(idx) == f._liens(idx) == {"a.md", "b.md"}


def test_memory_staleness_ecarte_les_mots_ubiquitaires_du_projet():
    m = _charger("forge_memory_staleness")
    toks = m._tokens("le hub nokido forge un embedder circadien")
    assert "circadien" in toks and "embedder" in toks
    assert not {"nokido", "forge", "hub"} & toks, (
        "les mots ubiquitaires matchent partout et fabriquent des recouvrements")


def test_memory_staleness_age_jamais_negatif(tmp_path):
    m = _charger("forge_memory_staleness")
    p = tmp_path / "memoire.md"
    p.write_text("---\nname: x\n---\n\ncorps\n", encoding="utf-8")
    assert m._age_jours(p.read_text(encoding="utf-8"), p) >= 0.0


# ── exploitation : jobs, veille, RAG, modeles ────────────────────────────────

def test_job_liveness_voit_le_processus_courant_et_pas_un_pid_fantome():
    m = _charger("forge_job_liveness")
    assert m._vivant(os.getpid()) is True
    assert m._vivant(0) is False
    assert m._vivant(4_000_000) is False


def test_veille_gap_recover_normalise_et_entrelace_les_domaines():
    m = _charger("forge_veille_gap_recover")
    assert m._norm("  HTTPS://Exemple.COM/page/  ") == "https://exemple.com/page"
    assert m._domaine("https://huggingface.co/a/b") == "huggingface.co"
    urls = ["https://hf.co/1", "https://hf.co/2", "https://hf.co/3", "https://autre.io/1"]
    ordre = m._entrelacer_par_domaine(urls)
    assert sorted(ordre) == sorted(urls), "l'entrelacement ne doit rien perdre"
    assert m._domaine(ordre[0]) != m._domaine(ordre[1]), (
        "un domaine qui rate-limit ne doit plus monopoliser la passe")


def test_rag_coverage_audit_rend_le_cout_et_dit_l_erreur_sql():
    m = _charger("forge_rag_coverage_audit")
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE t (id TEXT)")
    con.executemany("INSERT INTO t VALUES (?)", [("a",), ("b",)])
    val, secondes = m._mesure(con, "SELECT COUNT(*) FROM t")
    assert val == 2 and secondes >= 0
    # une mesure impossible est DITE, jamais rendue comme un zero
    val, _ = m._mesure(con, "SELECT COUNT(*) FROM table_absente")
    assert isinstance(val, dict) and "erreur" in val


def test_warm_code_model_repare_une_base_sans_schema():
    m = _charger("forge_warm_code_model")
    assert m._base("") == "http://127.0.0.1:11434"
    assert m._base("127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert m._base("https://gpu.local:8091/") == "https://gpu.local:8091"


# ── mutation et auto-amelioration ────────────────────────────────────────────

def test_self_mutation_protege_les_fichiers_qui_surveillent_le_systeme():
    m = _charger("forge_self_mutation", zone="app")
    motif = sorted(m.PROTEGES)[0]
    assert m.fichier_protege("app/%s.py" % motif) is True
    assert m.fichier_protege("app/un_module_quelconque_9999.py") is False


def test_self_mutation_extrait_le_code_et_mesure_la_similarite():
    m = _charger("forge_self_mutation", zone="app")
    assert m._code_seul("bla\n```python\nx = 1\n```\nfin") == "x = 1\n"
    assert m._code_seul("x = 2") == "x = 2\n"
    assert m._cosinus([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert m._cosinus([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert m._cosinus([0.0, 0.0], [1.0, 1.0]) == 0.0   # pas de division par zero


def test_mutation_run_pilote_bien_la_boucle_de_self_mutation():
    """Contrat STRUCTUREL (le module n'expose pas de fonction pure) : le lanceur
    doit continuer a piloter forge_self_mutation, pas une copie locale."""
    src = _source("forge_mutation_run")
    assert "forge_self_mutation" in src


def test_veille_gap_run_deporte_bien_le_rattrapage():
    """Contrat STRUCTUREL : ce lanceur existe pour DEPORTER le rattrapage hors
    du hub (l'appel synchrone a tue le hub le 2026-08-15)."""
    src = _source("forge_veille_gap_run")