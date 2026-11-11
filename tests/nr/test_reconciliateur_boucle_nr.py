"""NR 2026-11-06 : boucle automatique du reconciliateur de worktree jusqu'au commit local.

CONTRAT verifie sur un vrai depot git jetable :
1. travail orphelin -> branche preserve/<agent>/<court>, alpha intacte ;
2. tache en vol -> rien ;
3. statut illisible -> rien et signale ;
4. deuxieme passage -> aucun doublon ;
5. aucun appel push ni merge dans alpha (compteur strict = 0).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_worktree as fw  # noqa: E402


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "NokidoTest"
    env["GIT_AUTHOR_EMAIL"] = "nr@example.invalid"
    env["GIT_COMMITTER_NAME"] = "NokidoTest"
    env["GIT_COMMITTER_EMAIL"] = "nr@example.invalid"
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        env=env,
    )


@pytest.fixture(autouse=True)
def _machine_sans_pression(request, monkeypatch):
    """Isole ces tests de la RAM reelle du poste, sauf celui qui eprouve la garde elle-meme."""
    if request.node.name != "test_v2_garde_ressources_cpu_et_capteur_muet":
        monkeypatch.setattr(fw, "_lire_pression_systeme", lambda: (0.1, 0.1))


@pytest.fixture()
def depot_jetable(tmp_path):
    """Cree un depot git principal (alpha) et l'arborescence nokido_worktrees.

    Noms de dossiers COURTS (7/11, CI job_d9e2c3a3500b) : le basetemp de la CI de reference fait deja ~174 car.
    (`sandbox/workspace/tmp/nokido_proof/<id>/artefacts/ci_<compte>/bt/popen-gwN/pytest<nom>_<8>`). Avec `depot/` et
    `nokido_worktrees/`, un worktree `antigravity_task123` passait la borne de git pour Windows (PATH_MAX - 40) :
    `git worktree add` mourait en « fatal: '$GIT_DIR' too big » (rc 128) AVANT le reconciliateur, 4 tests rouges sur
    11 -- exactement ceux dont le nom de worktree depasse 14 car. Le code ne lit aucun de ces deux noms (`root` et
    `wt_root` sont passes) ; les noms d'agent et de tache, qui portent l'intention, sont intacts."""
    depot = tmp_path / "d"
    depot.mkdir()
    _git(["init", "-b", "alpha"], cwd=depot)
    _git(["config", "user.name", "NokidoTest"], cwd=depot)
    _git(["config", "user.email", "nr@example.invalid"], cwd=depot)

    # Initial commit sur alpha
    readme = depot / "README.md"
    readme.write_text("# Nokido Alpha\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=depot)
    _git(["commit", "-m", "chore: init alpha"], cwd=depot)

    wt_root = tmp_path / "w"  # role de nokido_worktrees ; nom court, cf. docstring
    (wt_root / "taches").mkdir(parents=True)

    # Sandbox et tasks.db factice
    sandbox = depot / "sandbox"
    sandbox.mkdir()
    tasks_db = sandbox / "tasks.db"
    import sqlite3
    conn = sqlite3.connect(str(tasks_db))
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, description TEXT)"
    )
    conn.commit()
    conn.close()

    return {
        "depot": depot,
        "wt_root": wt_root,
        "tasks_db": tasks_db,
        "tmp_path": tmp_path,
    }


def test_travail_orphelin_preserve_et_alpha_intacte(depot_jetable, monkeypatch):
    """Travail orphelin dans un worktree -> branche preserve/<agent>/<court>, alpha intacte."""
    depot = depot_jetable["depot"]
    wt_root = depot_jetable["wt_root"]
    tasks_db = depot_jetable["tasks_db"]

    # Creer un worktree orphelin de tache pour agy
    wt_agy = wt_root / "taches" / "antigravity_task123"
    _git(["worktree", "add", "-b", "tache/antigravity/task123", str(wt_agy), "alpha"], cwd=depot)

    # Ajouter du travail orphelin non committe
    nouveau_fichier = wt_agy / "app_nouveau.py"
    nouveau_fichier.write_text("print('orphelin')\n", encoding="utf-8")

    alpha_avant = _git(["rev-parse", "alpha"], cwd=depot).stdout.strip()

    # Activer l'interrupteur
    monkeypatch.setenv("NOKIDO_RECONCILIATEUR_ACTIF", "1")

    alertes = []
    def faux_alerter(sujet, gravite, detail, emetteur):
        alertes.append({"sujet": sujet, "gravite": gravite, "detail": detail, "emetteur": emetteur})
        return "emise"

    monkeypatch.setattr(fw, "alerter_owner_reconciliation", faux_alerter)

    bilan = fw.balayer_et_reconcilier(
        root=depot,
        wt_root=wt_root,
        tasks_db=tasks_db,
    )

    # Verifications
    alpha_apres = _git(["rev-parse", "alpha"], cwd=depot).stdout.strip()
    assert alpha_avant == alpha_apres, "alpha ne doit JAMAIS etre modifiee par la reconciliation"

    branches = _git(["branch"], cwd=depot).stdout
    assert "preserve/antigravity/task123" in branches, f"la branche preserve doit exister : {branches}"

    # Verifier que le commit preserve contient le fichier
    contenu_branche = _git(["show", "preserve/antigravity/task123:app_nouveau.py"], cwd=depot).stdout
    assert "print('orphelin')" in contenu_branche

    assert len(alertes) == 1
    assert "reconciliateur:lot_pret:antigravity:task123" in alertes[0]["sujet"]
    assert "forge_merge_gate" in alertes[0]["detail"]


def test_tache_en_vol_ne_touche_a_rien(depot_jetable, monkeypatch):
    """Worktree avec tache en vol (running) -> aucun commit, aucune modification."""
    depot = depot_jetable["depot"]
    wt_root = depot_jetable["wt_root"]
    tasks_db = depot_jetable["tasks_db"]

    wt_vol = wt_root / "taches" / "claude_taskvol"
    _git(["worktree", "add", "-b", "tache/claude/taskvol", str(wt_vol), "alpha"], cwd=depot)
    (wt_vol / "travail_en_cours.py").write_text("# en cours\n", encoding="utf-8")

    # Inscrire la tache comme 'running' dans tasks.db
    import sqlite3
    conn = sqlite3.connect(str(tasks_db))
    conn.execute("INSERT INTO tasks (id, agent, status) VALUES ('taskvol', 'CLAUDE', 'running')")
    conn.commit()
    conn.close()

    monkeypatch.setenv("NOKIDO_RECONCILIATEUR_ACTIF", "1")
    alertes = []
    monkeypatch.setattr(fw, "alerter_owner_reconciliation", lambda *a, **k: alertes.append(a))

    bilan = fw.balayer_et_reconcilier(root=depot, wt_root=wt_root, tasks_db=tasks_db)

    branches = _git(["branch"], cwd=depot).stdout
    assert "preserve/claude/taskvol" not in branches, "une tache en vol ne doit pas etre preservee/touchee"
    assert len(alertes) == 0


def test_statut_illisible_signale_et_non_touche(depot_jetable, monkeypatch):
    """Worktree dont le statut git est illisible -> non touche, et signale."""
    depot = depot_jetable["depot"]
    wt_root = depot_jetable["wt_root"]
    tasks_db = depot_jetable["tasks_db"]

    wt_casse = wt_root / "taches" / "mistral_taskcasse"
    _git(["worktree", "add", "-b", "tache/mistral/taskcasse", str(wt_casse), "alpha"], cwd=depot)

    monkeypatch.setenv("NOKIDO_RECONCILIATEUR_ACTIF", "1")
    alertes = []
    def faux_alerter(sujet, gravite, detail, emetteur):
        alertes.append({"sujet": sujet, "gravite": gravite, "detail": detail, "emetteur": emetteur})
        return "emise"
    monkeypatch.setattr(fw, "alerter_owner_reconciliation", faux_alerter)

    # Simuler git status qui echoue
    def faux_git_status(args, cwd):
        if args[:2] == ["status", "--porcelain"]:
            return subprocess.CompletedProcess(args, 1, "", "fatal: git status failed")
        return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True, errors="replace")

    monkeypatch.setattr(fw, "_git", faux_git_status)

    bilan = fw.balayer_et_reconcilier(root=depot, wt_root=wt_root, tasks_db=tasks_db)

    branches = _git(["branch"], cwd=depot).stdout
    assert "preserve/mistral/taskcasse" not in branches
    # Doit avoir signale l'etat illisible
    assert any("illisible" in a["sujet"] or "illisible" in a["detail"] for a in alertes)


def test_deuxieme_passage_aucun_doublon(depot_jetable, monkeypatch):
    """Deuxieme passage sur un travail deja preserve -> idempotent, aucun doublon."""
    depot = depot_jetable["depot"]
    wt_root = depot_jetable["wt_root"]
    tasks_db = depot_jetable["tasks_db"]

    wt_agy = wt_root / "taches" / "gemini_taskrep"
    _git(["worktree", "add", "-b", "tache/gemini/taskrep", str(wt_agy), "alpha"], cwd=depot)
    (wt_agy / "fic.py").write_text("ok\n", encoding="utf-8")

    monkeypatch.setenv("NOKIDO_RECONCILIATEUR_ACTIF", "1")
    alertes = []
    monkeypatch.setattr(fw, "alerter_owner_reconciliation", lambda s, g, d, e: alertes.append(s))

    bilan1 = fw.balayer_et_reconcilier(root=depot, wt_root=wt_root, tasks_db=tasks_db)
    assert len(alertes) == 1

    # Deuxieme passage
    bilan2 = fw.balayer_et_reconcilier(root=depot, wt_root=wt_root, tasks_db=tasks_db)
    assert len(alertes) == 1, "aucun doublon d'alerte lors du deuxieme passage"


def test_aucun_appel_push_ni_merge_dans_alpha(depot_jetable, monkeypatch):
    """Compteur strict : interdiction absolue de push et de merge dans alpha."""
    depot = depot_jetable["depot"]
    wt_root = depot_jetable["wt_root"]
    tasks_db = depot_jetable["tasks_db"]

    wt_agy = wt_root / "taches" / "antigravity_taskstrict"
    _git(["worktree", "add", "-b", "tache/antigravity/taskstrict", str(wt_agy), "alpha"], cwd=depot)
    (wt_agy / "strict.py").write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setenv("NOKIDO_RECONCILIATEUR_ACTIF", "1")
    monkeypatch.setattr(fw, "alerter_owner_reconciliation", lambda *a, **k: "emise")

    commandes_git = []
    vrai_run = subprocess.run

    def espion_run(cmd, *a, **kw):
        if isinstance(cmd, list) and len(cmd) > 1 and cmd[0] == "git":
            commandes_git.append(cmd)
            # Verifier les interdits immediatement
            if "push" in cmd:
                pytest.fail(f"INTERDIT: git push execute ! ({cmd})")
            if "merge" in cmd and "alpha" in cmd:
                pytest.fail(f"INTERDIT: git merge dans alpha execute ! ({cmd})")
        return vrai_run(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", espion_run)

    bilan = fw.balayer_et_reconcilier(root=depot, wt_root=wt_root, tasks_db=tasks_db)

    # Verification des compteurs
    pushes = [c for c in commandes_git if "push" in c]
    merges_alpha = [c for c in commandes_git if "merge" in c and "alpha" in c]
    assert len(pushes) == 0, f"aucun push autorise : {pushes}"
    assert len(merges_alpha) == 0, f"aucun merge dans alpha autorise : {merges_alpha}"


# ==============================================================================
# TESTS NR V2 (7 points de consigne 2026-11-07)
# ==============================================================================

def test_v2_tache_en_vol_tri_etat_et_base_illisible(depot_jetable, monkeypatch):
    """Point 1 & 7 : tri-etat pour _tache_est_en_vol (VRAI / FAUX / INCONNU).
    Base absente ou illisible -> INCONNU.
    Tache pending -> comptee comme en vol (VRAI)."""
    depot = depot_jetable["depot"]
    tasks_db = depot_jetable["tasks_db"]

    # 1. Base absente -> INCONNU
    assert fw._tache_est_en_vol("task1", "agy", tasks_db=depot / "nonexistent.db") == "INCONNU"

    # 2. Base corrompue / illisible -> INCONNU
    corrompue = depot / "corrompue.db"
    corrompue.write_text("fichier corrompu qui n'est pas du sqlite\n", encoding="utf-8")
    assert fw._tache_est_en_vol("task1", "agy", tasks_db=corrompue) == "INCONNU"

    # 3. Tache pending -> comptee comme en vol (VRAI)
    import sqlite3
    conn = sqlite3.connect(str(tasks_db))
    conn.execute("INSERT INTO tasks (id, agent, status) VALUES ('task_pending', 'MISTRAL', 'pending')")
    conn.commit()
    conn.close()
    assert fw._tache_est_en_vol("task_pending", "mistral", tasks_db=tasks_db) is True

    # 4. Tache running / claimed / assigned -> VRAI
    conn = sqlite3.connect(str(tasks_db))
    conn.execute("INSERT INTO tasks (id, agent, status) VALUES ('task_running', 'AGY', 'running')")
    conn.commit()
    conn.close()
    assert fw._tache_est_en_vol("task_running", "agy", tasks_db=tasks_db) is True

    # 5. Aucune tache en vol -> FAUX
    assert fw._tache_est_en_vol("task_inconnue", "autre", tasks_db=tasks_db) is False


def test_v2_garde_ressources_cpu_et_capteur_muet(monkeypatch):
    """Point 2 : garde_ressources_au_rouge s'abstient si le capteur leve ou est muet,
    et lit aussi le CPU."""
    # 1. Capteur qui leve -> abstention (True = rouge)
    def faux_read_full_exception(h):
        raise RuntimeError("capteur endocrine en panne")
    monkeypatch.setattr("nokido_agent.app.forge_endocrine.read_full", faux_read_full_exception, raising=False)
    # La mesure directe prend le relais : muette aussi, c'est l'abstention. Sans cela le test dependait de la RAM du poste.
    monkeypatch.setattr("psutil.virtual_memory", faux_read_full_exception, raising=False)
    assert fw.garde_ressources_au_rouge() is True

    # 2. CPU eleve -> True
    monkeypatch.setattr(fw, "_lire_pression_systeme", lambda: (0.1, 0.9))  # RAM 10%, CPU 90%
    assert fw.garde_ressources_au_rouge() is True

    # 3. RAM elevee -> True
    monkeypatch.setattr(fw, "_lire_pression_systeme", lambda: (0.8, 0.2))  # RAM 80%, CPU 20%
    assert fw.garde_ressources_au_rouge() is True

    # 4. Calme -> False
    monkeypatch.setattr(fw, "_lire_pression_systeme", lambda: (0.3, 0.3))  # RAM 30%, CPU 30%
    assert fw.garde_ressources_au_rouge() is False


def test_v2_branche_courante_intacte_et_non_ecrasement_preserve(depot_jetable, monkeypatch):
    """Point 3 : preserver sans deplacer la branche courante du worktree,
    et ne jamais ecraser une branche preserve existante (suffixer _1, _2...)."""
    depot = depot_jetable["depot"]
    wt_root = depot_jetable["wt_root"]
    tasks_db = depot_jetable["tasks_db"]

    wt_agy = wt_root / "taches" / "antigravity_t3"
    _git(["worktree", "add", "-b", "tache/antigravity/t3", str(wt_agy), "alpha"], cwd=depot)
    (wt_agy / "fic1.py").write_text("v1\n", encoding="utf-8")

    monkeypatch.setenv("NOKIDO_RECONCILIATEUR_ACTIF", "1")
    monkeypatch.setattr(fw, "alerter_owner_reconciliation", lambda *a, **k: "emise")

    branche_avant = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=wt_agy).stdout.strip()
    assert branche_avant == "tache/antigravity/t3"

    # Passage 1 : cree preserve/antigravity/t3
    res1 = fw.reconcilier_worktree_orphelin(wt_agy, root=depot, tasks_db=tasks_db)
    assert res1["action"] == "preserve"
    assert res1["branche"] == "preserve/antigravity/t3"

    branche_apres1 = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=wt_agy).stdout.strip()
    assert branche_apres1 == "tache/antigravity/t3", "La branche courante du worktree NE DOIT PAS avoir bouge !"

    # Nouveau travail dans le meme worktree
    (wt_agy / "fic2.py").write_text("v2\n", encoding="utf-8")

    # Passage 2 : ne doit pas ecraser preserve/antigravity/t3 mais creer preserve/antigravity/t3_1
    res2 = fw.reconcilier_worktree_orphelin(wt_agy, root=depot, tasks_db=tasks_db)
    assert res2["action"] == "preserve"
    assert res2["branche"] == "preserve/antigravity/t3_1"
    assert _git(["rev-parse", "--verify", "preserve/antigravity/t3"], cwd=depot).returncode == 0
    assert _git(["rev-parse", "--verify", "preserve/antigravity/t3_1"], cwd=depot).returncode == 0


def test_v2_status_porcelain_z_chemins_speciaux(depot_jetable, monkeypatch):
    """Point 5 : git status porcelain -z gere les chemins avec espaces, guillemets et renommages."""
    depot = depot_jetable["depot"]
    wt_root = depot_jetable["wt_root"]
    tasks_db = depot_jetable["tasks_db"]

    wt_agy = wt_root / "taches" / "antigravity_tspaces"
    _git(["worktree", "add", "-b", "tache/antigravity/tspaces", str(wt_agy), "alpha"], cwd=depot)

    # Fichier avec espace et caracteres speciaux
    fichier_espace = wt_agy / "fichier avec espaces.py"
    fichier_espace.write_text("print('espaces')\n", encoding="utf-8")

    monkeypatch.setenv("NOKIDO_RECONCILIATEUR_ACTIF", "1")
    monkeypatch.setattr(fw, "alerter_owner_reconciliation", lambda *a, **k: "emise")

    res = fw.reconcilier_worktree_orphelin(wt_agy, root=depot, tasks_db=tasks_db)
    assert res["action"] == "preserve"
    contenu = _git(["show", f"{res['branche']}:fichier avec espaces.py"], cwd=depot).stdout
    assert "print('espaces')" in contenu


def test_v2_registre_illisible_journalise_et_pas_de_re_alerte(depot_jetable, monkeypatch):
    """Point 6 : si le registre est illisible, on journalise et on ne re-alerte pas."""
    depot = depot_jetable["depot"]
    reg_path = depot / "sandbox" / "reconciliateur_lots.json"
    reg_path.write_text("{ ce json est totalement corrompu ]", encoding="utf-8")

    alertes = []
    monkeypatch.setattr(fw, "alerter_owner_reconciliation", lambda s, g, d, e: alertes.append(s))

    lots, illisible = fw._charger_registre_reconciliation(reg_path)
    assert illisible is True

    # Si le registre est illisible, balayer_et_reconcilier doit s'abstenir de re-alerter en double
    monkeypatch.setenv("NOKIDO_RECONCILIATEUR_ACTIF", "1")
    bilan = fw.balayer_et_reconcilier(root=depot, wt_root=depot_jetable["wt_root"], tasks_db=depot_jetable["tasks_db"])
    assert bilan["retenu"] is True
    assert bilan["raison"] == "registre_illisible"


def test_v2_verrou_et_intervalle_boucle(depot_jetable, monkeypatch):
    """Point 4 : une seule instance a la fois (verrou) et intervalle minimal respecte."""
    depot = depot_jetable["depot"]
    monkeypatch.setenv("NOKIDO_RECONCILIATEUR_ACTIF", "1")

    # 1. Deux appels immediats : le deuxieme doit etre saute pour intervalle
    b1 = fw.reconcilier_orphelins_boucle(root=depot, intervalle_min_s=60.0)
    assert b1["actif"] is True
    assert b1.get("saute_intervalle") is not True

    b2 = fw.reconcilier_orphelins_boucle(root=depot, intervalle_min_s=60.0)
    assert b2.get("saute_intervalle") is True

    # 2. Concurrence : verrou actif -> saute_verrou
    # Simuler verrou tenu
    verrou_file = depot / "sandbox" / "reconciliateur_boucle.lock"
    verrou_file.write_text("lock", encoding="utf-8")

    def faux_prendre_verrou(*a, **k):
        return None  # Ne peut pas acquerir le verrou

    monkeypatch.setattr(fw, "_acquerir_verrou_reconciliateur", faux_prendre_verrou)
    b3 = fw.reconcilier_orphelins_boucle(root=depot, intervalle_min_s=0.0)
    assert b3.get("saute_concurrence") is True
