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


def test_la_delegation_passe_par_le_worktree_et_l_effet():
    arbre = ast.parse(SOURCE.read_text(encoding="utf-8"))
    f = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "_delegate_to_agy")
    appels = {n.func.id for n in ast.walk(f) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert {"_workdir_agy", "_etat_git", "_effet_observe", "_intent_rendu",
            "_artefact_declare_absent", "_est_accuse_reception"} <= appels, appels


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
