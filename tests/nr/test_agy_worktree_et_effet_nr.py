"""NR -- AGY delegue travaille dans SON worktree, et le resultat porte l'EFFET observe, pas seulement
le succes declare.

2026-10-01 : l'owner a recu deux fois des invites d'approbation d'AGY. Cause (reponse d'AGY,
confirmee par le code) : `--sandbox` confine a `--add-dir <racine PARTAGEE>` alors que la mission
visait nokido_worktrees/antigravity -> une sortie de bac a sable par commande. Le meme soir AGY a
rendu OK_DONE/SUCCESS sur trois NR sans en committer aucun.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "tools" / "forge_task_executor.py"


def _mod():
    spec = importlib.util.spec_from_file_location("task_exec_nr", SOURCE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_le_workdir_est_le_worktree_d_agy(tmp_path, monkeypatch):
    m = _mod()
    racine = tmp_path / "Nokido"
    racine.mkdir()
    monkeypatch.setattr(m, "ROOT", racine)
    monkeypatch.delenv("LAFORGE_AGY_WORKDIR", raising=False)
    assert m._workdir_agy() == str(racine), "sans worktree : repli sur la racine (dit au journal)"
    wt = tmp_path / "nokido_worktrees" / "antigravity"
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: ailleurs", encoding="utf-8")
    assert m._workdir_agy() == str(wt)
    monkeypatch.setenv("LAFORGE_AGY_WORKDIR", "C:/explicite")
    assert m._workdir_agy() == "C:/explicite", "la variable explicite reste prioritaire"


def _git(d, *args):
    # Sans les GIT_* heritees (hooks, tests voisins) : sinon `-C d` peut viser un AUTRE depot.
    import os as _os
    env = {k: v for k, v in _os.environ.items() if not k.upper().startswith("GIT_")}
    subprocess.run(["git", "-c", "safe.directory=*", "-c", "user.name=nr", "-c", "user.email=nr@x",
                    "-C", str(d), *args], check=True, capture_output=True, text=True,
                   encoding="utf-8", errors="replace", env=env)


def test_l_effet_observe_compte_commits_et_fichiers(tmp_path):
    m = _mod()
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "base")
    avant = m._etat_git(str(tmp_path))
    assert avant[0] and avant[1] == 0
    for i in range(2):
        (tmp_path / ("f%d.txt" % i)).write_text(str(i), encoding="utf-8")
        _git(tmp_path, "add", "f%d.txt" % i)
        _git(tmp_path, "commit", "-q", "-m", "c%d" % i)
    (tmp_path / "non_suivi.txt").write_text("x", encoding="utf-8")
    effet = m._effet_observe(str(tmp_path), avant)
    assert "commits produits : 2" in effet and "fichiers non commites : 1" in effet, effet


def test_aucun_commit_se_voit_et_l_illisible_se_dit(tmp_path):
    m = _mod()
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "base")
    avant = m._etat_git(str(tmp_path))
    assert "commits produits : 0" in m._effet_observe(str(tmp_path), avant)
    assert "ILLISIBLE" in m._effet_observe(str(tmp_path / "absent"), (None, None))


def test_un_git_dir_herite_ne_fausse_pas_l_effet(tmp_path, monkeypatch):
    """Hypothese de l'echec CI du 2026-10-02 : un GIT_DIR / GIT_INDEX_FILE herite (hook, test voisin)
    detourne `git -C <workdir>`. Le drain l'ignore : il compte les commits du workdir.
    (Hypothese REFUTEE ensuite : la cause etait la longueur du chemin, voir le test suivant. Le garde
    reste : une GIT_* heritee detournerait reellement `-C`.)"""
    m = _mod()
    depot = tmp_path / "depot"
    depot.mkdir()
    _git(depot, "init", "-q")
    (depot / "a.txt").write_text("a", encoding="utf-8")
    _git(depot, "add", "a.txt")
    _git(depot, "commit", "-q", "-m", "base")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "ailleurs.git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "index_etranger"))
    avant = m._etat_git(str(depot))
    for i in range(2):
        (depot / ("f%d.txt" % i)).write_text(str(i), encoding="utf-8")
        _git(depot, "add", "f%d.txt" % i)
        _git(depot, "commit", "-q", "-m", "c%d" % i)
    effet = m._effet_observe(str(depot), avant)
    assert "commits produits : 2" in effet, effet


def test_un_workdir_profond_compte_ses_commits(tmp_path):
    """CAUSE de l'echec CI (2026-10-02, CI de reference 479480200, dite par le rc) : « failed to stat
    '<a>..<b>': Filename too long », rc 128. Sans `--`, git teste aussi la plage comme CHEMIN ; sous
    un worktree profond, <workdir>/<a>..<b> depasse MAX_PATH et le stat rend ENAMETOOLONG (fatal) au
    lieu d'ENOENT. Workdir ~190 caracteres : le depot reste inscriptible (objets < 260), la plage
    de 81 caracteres le fait deborder. Hors Windows le test passe sans rien prouver de plus."""
    m = _mod()
    depot = tmp_path
    while len(str(depot)) < 185:
        depot = depot / "profond"
    if len(str(depot)) > 196:
        pytest.skip("tmp_path deja trop long pour construire le cas (%d)" % len(str(tmp_path)))
    depot.mkdir(parents=True)
    _git(depot, "init", "-q")
    (depot / "a.txt").write_text("a", encoding="utf-8")
    _git(depot, "add", "a.txt")
    _git(depot, "commit", "-q", "-m", "base")
    avant = m._etat_git(str(depot))
    for i in range(2):
        (depot / ("f%d.txt" % i)).write_text(str(i), encoding="utf-8")
        _git(depot, "add", "f%d.txt" % i)
        _git(depot, "commit", "-q", "-m", "c%d" % i)
    effet = m._effet_observe(str(depot), avant)
    assert "commits produits : 2" in effet, effet


def test_un_rev_list_en_echec_n_est_pas_zero_commit(tmp_path, monkeypatch):
    """CI de reference f340e9ca4 (2026-10-02) : `int(stdout or 0)` faisait d'un rev-list en ECHEC
    « 0 commit ». Base inconnue -> ILLISIBLE, avec l'erreur de git, jamais un effet nul."""
    m = _mod()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    depot = tmp_path / "depot"
    depot.mkdir()
    _git(depot, "init", "-q")
    (depot / "a.txt").write_text("a", encoding="utf-8")
    _git(depot, "add", "a.txt")
    _git(depot, "commit", "-q", "-m", "base")
    effet = m._effet_observe(str(depot), ("deadbeef" * 5, 0))
    assert "commits produits : ILLISIBLE" in effet and "rev-list rc=" in effet, effet


def _appels(nom: str) -> set:
    arbre = ast.parse(SOURCE.read_text(encoding="utf-8"))
    f = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == nom)
    return {n.func.id for n in ast.walk(f) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def test_la_delegation_passe_par_le_worktree_et_l_effet():
    """16/10 : le jugement de livraison est COMMUN aux delegations (AGY, CODEX) -- `_juger_livraison` ; une voie
    qui le recopierait divergerait de l'autre en silence."""
    assert {"_workdir_agy", "_etat_git", "_juger_livraison"} <= _appels("_delegate_to_agy")
    assert {"_effet_observe", "_intent_rendu", "_artefact_declare_absent", "_est_accuse_reception",
            "_non_livre"} <= _appels("_juger_livraison")


# ------------------------------------------------- voie CODEX AUTONOME (decision owner 15/10 : apres 0.20.12, 3/jour)
def test_la_delegation_codex_juge_comme_agy_et_passe_par_le_harness():
    assert {"_workdir_codex", "_etat_git", "_attendre_harness", "_consommer_quota_codex",
            "_juger_livraison"} <= _appels("_delegate_to_codex")


def test_le_quota_codex_est_compte_par_jour_et_l_illisible_n_autorise_rien(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_CODEX_QUOTA", tmp_path / "q.json")
    assert m._quota_codex("2026-10-16") == 0
    for attendu in (1, 2, 3):
        assert m._consommer_quota_codex("2026-10-16") == attendu
    assert m._quota_codex("2026-10-16") == m.CODEX_QUOTA_JOUR == 3
    assert m._quota_codex("2026-10-17") == 0, "le compteur repart chaque jour"
    (tmp_path / "q.json").write_text("{casse", encoding="utf-8")
    assert m._quota_codex("2026-10-16") == m.CODEX_QUOTA_JOUR, "illisible = plafond atteint (quota non paye)"


def _depot_git(tmp_path):
    d = tmp_path / "wt"
    d.mkdir()
    for cmd in (["init", "-q"], ["config", "user.name", "nr"], ["config", "user.email", "nr@example.invalid"],
                ["commit", "-q", "--allow-empty", "-m", "racine"]):
        subprocess.run(["git", "-C", str(d)] + cmd, check=True, capture_output=True)
    return d


def _nb_commits(d):
    r = subprocess.run(["git", "-C", str(d), "rev-list", "--count", "HEAD"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return int(r.stdout.strip())


def test_codex_ecrit_et_l_executeur_committe(tmp_path):
    """16/10, 2 sondes : `workspace-write` tient .git en lecture seule PAR CONCEPTION (codex-rs « .git excluded ») ;
    ni sans ni avec --add-dir Codex ne peut `git add`. Le bac a sable reste, l'executeur committe les fichiers LISTES
    avec le message que Codex propose ; rien si Codex dit « pas fait », rien s'il n'a rien ecrit."""
    m = _mod()
    args = m._args_codex(tmp_path)
    assert "--add-dir" not in args and args[4:6] == ["-s", "workspace-write"] and args[-1] == "-"
    assert "ne lance ni `git add`" in m._CONSIGNE_GIT_CODEX.lower()
    d = _depot_git(tmp_path)
    assert m._committer_pour_codex(str(d), "t0", '{"intent":"OK_DONE"}') is None, "rien d'ecrit : rien a committer"
    (d / "docs").mkdir()
    (d / "docs" / "a.md").write_text("contenu\n", encoding="utf-8")
    refus = '{"intent":"ERR_INTERNAL","status_code":"FAILURE","pointer_ref":"err:x"}'
    assert m._committer_pour_codex(str(d), "t1", refus) is None and _nb_commits(d) == 1, "« pas fait » : 0 commit"
    note = m._committer_pour_codex(str(d), "t2", '... {"intent":"OK_DONE","pointer_ref":"docs/a.md",'
                                                    '"commit_message":"docs(codex): ajoute a"}')
    assert note and "1 fichier" in note, note
    assert _nb_commits(d) == 2
    sujet = subprocess.run(["git", "-C", str(d), "log", "-1", "--format=%s"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    assert sujet.stdout.strip() == "docs(codex): ajoute a"
    assert "_committer_pour_codex" in _appels("_delegate_to_codex")


def test_agy_ecrit_et_l_executeur_committe_seulement_ce_que_la_tache_a_produit(tmp_path):
    """16/10, essai partage n°1 : sous --sandbox, AGY a demande RunCommand hors bac (git/pytest), refuse
    (tasks.db : denied_actions unsandboxed RunCommand) -> rien livre. Meme forme que Codex : AGY ecrit sans commande,
    l'executeur committe -- mais SEULEMENT les chemins apparus pendant la tache : le worktree d'AGY portait 5 dossiers
    non suivis sans rapport (debat_*, clients/, sandbox/ci_Naarob) qu'un « tout git status » aurait embarques."""
    m = _mod()
    assert "aucune commande" in m._CONSIGNE_SANS_COMMANDE_AGY.lower()
    d = _depot_git(tmp_path)
    (d / "vieux_brouillon").mkdir()
    (d / "vieux_brouillon" / "x.md").write_text("sans rapport\n", encoding="utf-8")
    avant = m._chemins_status(str(d))
    (d / "tests").mkdir()
    (d / "tests" / "test_neuf.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    note = m._committer_pour_agent(str(d), "t3", '{"intent":"OK_DONE","pointer_ref":"tests/test_neuf.py",'
                                                '"commit_message":"test(agy): ajoute"}', "agy", exclus=avant)
    fichiers = subprocess.run(["git", "-C", str(d), "show", "--name-only", "--format=", "HEAD"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace").stdout.split()
    assert (bool(note), fichiers) == (True, ["tests/test_neuf.py"]), (note, fichiers)
    assert "_committer_pour_agent" in _appels("_delegate_to_agy")


def test_sans_worktree_dedie_codex_ne_part_pas(tmp_path, monkeypatch):
    """Pas de repli sur la racine partagee : un agent qui ecrit hors de son claim empeche tout verdict de CI."""
    m = _mod()
    monkeypatch.setenv("LAFORGE_CODEX_WORKDIR", str(tmp_path / "codex"))
    monkeypatch.setattr(m, "_HARNESS_JOBS", tmp_path / "jobs")
    ok, pourquoi = m._peut_lancer_codex()
    assert not ok and "geste OWNER" in pourquoi
    (tmp_path / "codex").mkdir()
    (tmp_path / "codex" / ".git").write_text("gitdir: x", encoding="utf-8")
    assert m._peut_lancer_codex()[0]


def test_codex_sans_effet_n_est_pas_un_succes(tmp_path, monkeypatch):
    """DECLARE n'est pas ACHIEVED : le harness rend la SORTIE de codex, pas son verdict. Sans commit ni pointer_ref
    verifiable, la tache est close en ECHEC nomme ; le lancement a consomme le quota."""
    m = _mod()
    monkeypatch.setenv("LAFORGE_CODEX_WORKDIR", str(tmp_path / "codex"))
    (tmp_path / "jobs").mkdir()
    monkeypatch.setattr(m, "_HARNESS_JOBS", tmp_path / "jobs")
    monkeypatch.setattr(m, "_CODEX_QUOTA", tmp_path / "q.json")
    monkeypatch.setattr(m, "_etat_git", lambda wd: ("a" * 40, 0))
    monkeypatch.setattr(m, "_effet_observe",
                        lambda wd, avant: "[effet observe] commits produits : 0 ; fichiers non commites : 0")
    # Doublure au VRAI contrat : _attendre_harness(job, delai_s, attente_file_s=None, task_id=None) depuis d8abd05aa.
    monkeypatch.setattr(m, "_attendre_harness",
                        lambda job, delai, attente_file_s=None, task_id=None: {"ok": True, "output": "J'ai regarde le code."})
    clos = {}
    monkeypatch.setattr(m, "_clore_delegation",
                        lambda tid, tok, ok, detail, intent=None: clos.update(ok=ok, detail=detail))
    m._delegate_to_codex({"id": "t1", "description": "corrige X"}, "jeton")
    assert clos["ok"] is False and "AUCUN EFFET" in clos["detail"]
    j = json.loads(next((tmp_path / "jobs").glob("codex_*.json")).read_text(encoding="utf-8"))
    assert j["agent"] == "codex" and "-C" in j["args"] and j["cwd"] == str(tmp_path / "codex")
    assert m._quota_codex() == 1


def test_le_plafond_codex_se_juge_avant_de_prendre_la_tache():
    boucle = SOURCE.read_text(encoding="utf-8").split("def run_loop", 1)[1]
    # Le point de claim est _reclamer depuis b202705bd (claim atomique au nom du sujet) ; l'invariant ne change pas.
    assert boucle.index("_quota_codex()") < boucle.index("_reclamer("), \
        "une tache prise puis refusee pour quota serait brulee au lieu de rester pending"


@pytest.mark.parametrize("reponse, accuse", [
    ("I am searching the codebase. I will write the report once the scan is complete.", True),
    ("Je vais analyser le module et je reviens vers vous.", True),
    ('J\'ai ecrit le rapport. {"intent": "OK_DONE", "pointer_ref": "sandbox/swarm/x.md"}', False),
])
def test_un_accuse_de_reception_est_reconnu(reponse, accuse):
    """Cas reel du 2026-09-20 (bb:delegate_agy_sans_garde_accuse) : un detail au FUTUR rendu en
    OK_DONE. La garde du repli s'applique desormais au chemin principal."""
    m = _mod()
    vu = '"pointer_ref"' not in reponse and m._est_accuse_reception(reponse)
    assert vu is accuse, reponse


# Reponse REELLE d'AGY du 2026-10-01 (job_8655d91d) : il s'arrete a bon droit, et l'enveloppe du CLI
# disait SUCCESS -- la delegation l'avait transmis en OK_DONE.
REPONSE_AGY = ('J\'ai ecrit le fichier de test. Cependant je me suis arrete car BypassSandbox redevient '
               'necessaire.\n```json\n{\n  "intent": "NEED_HUMAN_APPROVAL",\n  "pointer_ref": "x.md"\n}\n```')


@pytest.mark.parametrize("reponse, attendu", [
    (REPONSE_AGY, "NEED_HUMAN_APPROVAL"),
    ('{"intent": "ERR_TIMEOUT"}', "ERR_TIMEOUT"),
    ('consigne : {"intent": "NEED_CLARIFY"} ... rendu final {"intent": "OK_DONE"}', None),   # le DERNIER compte
    ("travail fait, commits 3a4b5c6", None),
])
def test_l_intent_declare_par_l_agent_prime_sur_l_enveloppe(reponse, attendu):
    assert _mod()._intent_rendu(reponse) == attendu

# Reponse REELLE d'AGY du 2026-10-01 (job_43e8ddab) : OK_DONE sur un fichier jamais ecrit (absent du
# worktree comme de l'arbre partage ; l'effet observe disait 4 fichiers non commites avant ET apres).
REPONSE_ADDDIR = ('```json\n{\n  "intent": "OK_DONE",\n  "status_code": 200,\n'
                  '  "pointer_ref": "sandbox/swarm/reponse_agy_adddir_2026-10-01.md"\n}\n```\n')

def test_un_fichier_declare_mais_absent_se_dit(tmp_path, monkeypatch):
    m = _mod()
    racine, wt = tmp_path / "Nokido", tmp_path / "wt"
    racine.mkdir(); wt.mkdir()
    monkeypatch.setattr(m, "ROOT", racine)
    assert "fichier declare absent" in (m._artefact_declare_absent(REPONSE_ADDDIR, str(wt)) or "")
    cible = wt / "sandbox" / "swarm" / "reponse_agy_adddir_2026-10-01.md"
    cible.parent.mkdir(parents=True)
    cible.write_text("ok", encoding="utf-8")
    assert m._artefact_declare_absent(REPONSE_ADDDIR, str(wt)) is None, "present dans le worktree"

@pytest.mark.parametrize("reponse", [
    "travail fait, pas de pointeur",
    '{"intent": "OK_DONE", "pointer_ref": "tasks.db:job_x"}',
    '{"intent": "OK_DONE", "pointer_ref": "https://exemple.org/x.md"}',
    '{"intent": "OK_DONE", "pointer_ref": "bb_cle_sans_chemin"}',
    # 16/10, essai partage n°2 : AGY a livre (2643362ce) et le juge l'a classe ERR_INTERNAL -- « fichier declare
    # absent : bb:architecture_rules/... ». Un pointeur bb:zone/cle designe le TABLEAU NOIR, pas un fichier.
    '{"intent": "OK_DONE", "pointer_ref": "bb:architecture_rules/decision_owner_x_20261016"}',
])
def test_un_pointeur_non_verifiable_n_accuse_pas(reponse, tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    assert m._artefact_declare_absent(reponse, str(tmp_path)) is None

def test_un_commit_declare_se_verifie_et_l_illisible_n_accuse_pas(tmp_path, monkeypatch):
    m = _mod()
    # le tmp de pytest vit DANS le depot Nokido (sandbox/workspace/tmp) : sans plafond, git y remonte
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    depot = tmp_path / "depot"      # depot et non-depot FRERES : un sous-dossier du depot y appartiendrait
    depot.mkdir()
    _git(depot, "init", "-q")
    (depot / "a.txt").write_text("a", encoding="utf-8")
    _git(depot, "add", "a.txt")
    _git(depot, "commit", "-q", "-m", "base")
    sha = m._etat_git(str(depot))[0]
    vrai = '{"intent": "OK_DONE", "pointer_ref": "agent/antigravity@%s"}' % sha[:9]
    faux = '{"intent": "OK_DONE", "pointer_ref": "agent/antigravity@deadbeef0"}'
    assert m._artefact_declare_absent(vrai, str(depot)) is None
    assert "commit declare introuvable" in (m._artefact_declare_absent(faux, str(depot)) or "")
    pas_un_depot = tmp_path / "vide"
    pas_un_depot.mkdir()
    assert m._artefact_declare_absent(faux, str(pas_un_depot)) is None, "git illisible : n'accuse pas"
