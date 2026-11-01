"""NR : le bump du superrepo ne committe QUE les gitlinks (mesure 26/10).

forge_bump_superrepo --commit faisait `git commit -m ...` sans pathspec : un CLAUDE.md que l'owner avait INDEXE
dans le superrepo (non committe) est parti dans « chore(sm): bump gitlink Nokido » (a497850, 2 fichiers au lieu
d'un). Defait par reset --soft avant push. Le commit porte desormais le pathspec des seuls pointeurs.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_bump_superrepo as bump  # noqa: E402


def _enregistreur(monkeypatch):
    vus = []
    monkeypatch.setattr(bump, "git", lambda *a, **k: (vus.append(a) or SimpleNamespace(returncode=0, stdout="", stderr="")))
    return vus


def test_le_commit_passe_par_un_index_temporaire_sans_pathspec(monkeypatch):
    # 1/11 : le pathspec `commit -- Nokido` relisait l'arbre du submodule (pathspec non resolu sous LaForgeTrusted,
    # SUPPRESSION du gitlink si le dossier manque). Le commit passe par un index temporaire, sans pathspec.
    vus = []

    def faux(*a, **k):
        vus.append((a, k))
        sortie = "160000 %s 0\tNokido\n100644 %s 0\tCLAUDE.md\n" % ("2" * 40, "3" * 40) if a[:1] == ("ls-files",) else ""
        return SimpleNamespace(returncode=0, stdout=sortie, stderr="")

    monkeypatch.setattr(bump, "git", faux)
    bump._committer_pointeurs(["Nokido"], "chore(sm): bump", "corps")
    commit = [(a, k) for a, k in vus if a and a[0] == "commit"][0]
    assert "--" not in commit[0] and commit[1].get("index")
    # 1/11 : une LECTURE (ls-files) avec --work-tree et un CWD hors de l'arbre rend VIDE, rc=0 (prod LaForgeTrusted)
    lecture = [k for a, k in vus if a[:1] == ("ls-files",)][0]
    assert not lecture.get("arbre")
    poses = [a for a, k in vus if a[:1] == ("update-index",)]
    assert poses == [("update-index", "--add", "--cacheinfo", "160000,%s,Nokido" % ("2" * 40))]


def test_le_staging_vide_se_juge_sur_les_seuls_pointeurs(monkeypatch):
    """Comparaison des VALEURS (index :p contre HEAD:p), pas un diff : une lecture qui echoue rend « change »."""
    vus = []

    def faux(*a, **k):
        vus.append(a)
        return SimpleNamespace(returncode=0, stdout="sha_identique\n", stderr="")

    monkeypatch.setattr(bump, "git", faux)
    assert bump._pointeurs_inchanges(["Nokido", "netcfg-agent"]) is True
    assert ("rev-parse", ":Nokido") in vus and ("rev-parse", "HEAD:Nokido") in vus
    monkeypatch.setattr(bump, "git", lambda *a, **k: SimpleNamespace(returncode=128, stdout="", stderr="illisible"))
    assert bump._pointeurs_inchanges(["Nokido"]) is False   # UNKNOWN != NO : on ne conclut pas « inchange »


def _superrepo_avec_gitlink(tmp_path):
    import subprocess

    sup = tmp_path / "super"
    sup.mkdir()

    def g(*a):
        return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(sup), *a], check=True,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25).stdout

    g("init", "-q")
    (sup / "CLAUDE.md").write_text("owner v1\n", encoding="utf-8")
    g("add", "CLAUDE.md")
    g("update-index", "--add", "--cacheinfo", "160000,%s,Nokido" % ("1" * 40))
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "v1")
    g("update-index", "--cacheinfo", "160000,%s,Nokido" % ("2" * 40))     # pointeur bumpe dans l'index
    (sup / "CLAUDE.md").write_text("owner v2\n", encoding="utf-8")
    g("add", "CLAUDE.md")                                               # travail de l'owner indexe aussi
    return sup, g


def test_un_gitlink_indexe_n_est_pas_lu_inchange_meme_si_diff_ignore_les_submodules(monkeypatch, tmp_path):
    """Mesure 26/10 22 h : sous LaForgeTrusted, « index : Nokido -> f330cb06 » puis « rien de stage » -- le pointeur
    etait pourtant indexe (commite a la main, 0e1b376). Cause exacte NON identifiee (config du compte illisible
    d'ici) ; un mecanisme qui fait mentir `diff --cached --quiet` sur un vrai gitlink est reproduit ici."""
    sup, g = _superrepo_avec_gitlink(tmp_path)
    g("config", "diff.ignoreSubmodules", "all")
    monkeypatch.setattr(bump, "SUPERREPO", sup)
    monkeypatch.setattr(bump, "_auth", lambda: ([], None))
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    monkeypatch.chdir(ailleurs)                                         # comme LaForgeTrusted, hors de l'arbre
    assert bump._pointeurs_inchanges(["Nokido"]) is False


def test_chemin_reel_git_cwd_hors_du_superrepo(monkeypatch, tmp_path):
    """Chemin REEL (les tests precedents remplacaient git) : repertoire courant HORS du superrepo, comme sous
    LaForgeTrusted ; le commit ne porte que le pointeur et l'index de l'owner reste intact."""
    import subprocess

    sup = tmp_path / "super"
    sup.mkdir()

    def g(*a):
        subprocess.run(["git", "-c", "safe.directory=*", "-C", str(sup), *a], check=True, capture_output=True,
                       timeout=25)

    g("init", "-q")
    (sup / "Nokido").write_text("v1\n", encoding="utf-8")
    (sup / "CLAUDE.md").write_text("owner v1\n", encoding="utf-8")
    g("add", ".")
    g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "v1")
    (sup / "Nokido").write_text("v2\n", encoding="utf-8")
    (sup / "CLAUDE.md").write_text("owner v2\n", encoding="utf-8")
    g("add", "Nokido", "CLAUDE.md")                        # pointeur ET travail de l'owner indexes

    monkeypatch.setattr(bump, "SUPERREPO", sup)
    monkeypatch.setattr(bump, "_auth", lambda: ([], None))
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    monkeypatch.chdir(ailleurs)

    assert bump._pointeurs_inchanges(["Nokido"]) is False
    r = bump._committer_pointeurs(["Nokido"], "chore(sm): bump")
    assert r.returncode == 0, r.stderr
    montre = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(sup), "show", "--name-only", "--format=",
                             "HEAD"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=25).stdout.split()
    assert montre == ["Nokido"]                            # le commit ne porte QUE le pointeur
    reste = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(sup), "diff", "--cached", "--name-only"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25).stdout.split()
    assert reste == ["CLAUDE.md"]                          # l'index de l'owner est intact
