"""NR — le bisect gouverne.

Ce qu'on protege ici : les deux garde-fous qui font qu'un bisect designe un
coupable plutot qu'un innocent. Le premier est la synchronisation des
sous-depots a chaque etape (un pointeur neuf sur un contenu ancien rend un
verdict qui ne veut rien dire). Le second est l'isolement : bisect fait des
checkout, et les faire dans l'arbre de travail ferait basculer en vol le code
que le hub execute.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.274)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_un_test_nr_devient_une_commande_pytest():
    import forge_bisect as B

    cmd = B.construire_commande("nr:tests/nr/test_observabilite_nr.py")
    assert cmd[1:4] == ["-m", "pytest", "tests/nr/test_observabilite_nr.py"]


def test_les_criteres_connus_pointent_des_outils_qui_existent():
    """Un critere qui designe un fichier absent rendrait « mauvais » a CHAQUE
    etape, et bisect accuserait le premier commit venu."""
    import forge_bisect as B

    for nom, argv in B.CRITERES.items():
        cible = argv[1] if argv[0] == "-m" else argv[0]
        if cible.endswith(".py"):
            assert (ROOT / cible).exists(), f"critere {nom} : {cible} introuvable"


def test_une_commande_libre_est_respectee():
    import forge_bisect as B

    assert B.construire_commande("cmd:echo bonjour") == ["echo", "bonjour"]


def test_un_critere_inconnu_est_refuse():
    import forge_bisect as B

    with pytest.raises(SystemExit):
        B.construire_commande("nimportequoi")


def test_les_sousdepots_sont_detectes(tmp_path):
    import forge_bisect as B

    assert not B._a_des_sousdepots(str(tmp_path))
    (tmp_path / ".gitmodules").write_text("[submodule \"x\"]\n", encoding="utf-8")
    assert B._a_des_sousdepots(str(tmp_path))


def test_l_etape_synchronise_les_sousdepots_quand_il_y_en_a(tmp_path):
    """LE point de la methode : sans cette ligne, on teste l'ancien contenu avec
    le nouveau pointeur."""
    import forge_bisect as B

    chemin = B._script_etape(str(tmp_path), ["python", "-c", "pass"], sousdepots=True)
    contenu = Path(chemin).read_text(encoding="utf-8")
    assert "git submodule update --init --recursive" in contenu
    assert "python" in contenu


def test_l_etape_n_invente_pas_de_sousdepot(tmp_path):
    import forge_bisect as B

    chemin = B._script_etape(str(tmp_path), ["python", "-c", "pass"], sousdepots=False)
    assert "submodule" not in Path(chemin).read_text(encoding="utf-8")


def test_l_interpreteur_choisi_existe():
    import os

    import forge_bisect as B

    assert os.path.exists(B._python())


def test_l_etape_skip_le_commit_si_la_sync_echoue(tmp_path):
    """PRECONDITION DURE : si `git submodule update` echoue dans le script
    d'etape, il doit rendre 125 (git bisect = commit non testable), jamais
    laisser le test juger l'ancien contenu."""
    import forge_bisect as B

    chemin = B._script_etape(str(tmp_path), ["echo", "ok"], sousdepots=True)
    contenu = Path(chemin).read_text(encoding="utf-8")
    assert "submodule update" in contenu
    assert "125" in contenu  # exit 125 / exit /b 125 selon l'OS
    # Et sans sous-depots, aucune ligne submodule ne doit apparaitre.
    sans = B._script_etape(str(tmp_path), ["echo", "ok"], sousdepots=False)
    assert "submodule" not in Path(sans).read_text(encoding="utf-8")


def test_verdict_leve_si_composition_instable(monkeypatch):
    """_verdict ne rend jamais un booleen sur une composition non alignee :
    il leve CompositionInstable, que executer transforme en abort."""
    import forge_bisect as B

    monkeypatch.setattr(B, "_sync_sousdepots", lambda _a: (False, "pointeur != HEAD"))
    with pytest.raises(B.CompositionInstable):
        B._verdict("/tmp/x", ["echo", "ok"], sousdepots=True)


# ── synchronisation des sous-depots : EFFET, pas texte ───────────────────────
# MESURE 2026-08-18 : cette suite tuait 1 mutant sur 12 (8,3 %). La cause etait
# ici — un test qui lisait `inspect.getsource` et cherchait « ls-tree » dans la
# chaine. Muter `!=` en `==` laisse le texte intact, donc un tel test ne rougit
# JAMAIS. Meme famille que [sonde != preuve] : on execute, on ne relit pas.

class _Retour:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _faux_git(reponses: dict, journal: list | None = None):
    """Repond selon le premier mot de la commande git (update / ls-tree / rev-parse)."""
    def _appel(args, cwd=None, timeout=600):
        if journal is not None:
            journal.append((tuple(args), cwd))
        for cle, rep in reponses.items():
            if cle in args:
                return rep(args, cwd) if callable(rep) else rep
        return _Retour()
    return _appel


def test_sync_refuse_quand_submodule_update_echoue(monkeypatch):
    import forge_bisect as B

    monkeypatch.setattr(B, "_git", _faux_git({"submodule": _Retour(1, "", "reseau coupe")}))
    ok, motif = B._sync_sousdepots("/arbre")
    assert ok is False
    assert "submodule update rc=1" in motif and "reseau coupe" in motif


def test_sync_refuse_quand_ls_tree_est_muet(monkeypatch):
    import forge_bisect as B

    monkeypatch.setattr(B, "_git", _faux_git({"ls-tree": _Retour(128, "", "")}))
    assert B._sync_sousdepots("/arbre") == (False, "ls-tree muet apres sync")


def test_sync_refuse_un_pointeur_qui_ne_vaut_pas_le_head_reel(monkeypatch):
    """Le coeur du garde : `submodule update` peut rendre 0 en n'ayant rien
    aligne. Un pointeur neuf sur un contenu ancien passerait alors pour teste."""
    import forge_bisect as B

    lt = "160000 commit aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\tNokido\n"
    monkeypatch.setattr(B, "_git", _faux_git({
        "ls-tree": _Retour(0, lt),
        "rev-parse": _Retour(0, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"),
    }))
    ok, motif = B._sync_sousdepots("/arbre")
    assert ok is False
    assert "desynchronise" in motif and "aaaaaaaaaaaa" in motif and "bbbbbbbbbbbb" in motif


def test_sync_accepte_quand_le_head_egale_le_pointeur(monkeypatch):
    import forge_bisect as B

    sha = "a" * 40
    lt = f"160000 commit {sha}\tNokido\n"
    monkeypatch.setattr(B, "_git", _faux_git({
        "ls-tree": _Retour(0, lt),
        "rev-parse": _Retour(0, sha + "\n"),
    }))
    assert B._sync_sousdepots("/arbre") == (True, "")


def test_sync_ignore_les_lignes_qui_ne_sont_pas_des_gitlinks(monkeypatch):
    """Un blob ordinaire n'est pas un sous-depot : le confronter a un HEAD
    ferait echouer toute composition contenant un fichier normal."""
    import forge_bisect as B

    lt = ("100644 blob cccccccccccccccccccccccccccccccccccccccc\tREADME.md\n"
          "040000 tree dddddddddddddddddddddddddddddddddddddddd\tapp\n")
    monkeypatch.setattr(B, "_git", _faux_git({
        "ls-tree": _Retour(0, lt),
        "rev-parse": _Retour(1, "", "pas un depot"),
    }))
    assert B._sync_sousdepots("/arbre") == (True, "")


def test_sync_refuse_quand_le_sousdepot_ne_repond_pas(monkeypatch):
    import forge_bisect as B

    lt = f"160000 commit {'a' * 40}\tNokido\n"
    monkeypatch.setattr(B, "_git", _faux_git({
        "ls-tree": _Retour(0, lt),
        "rev-parse": _Retour(128, "", "not a git repository"),
    }))
    assert B._sync_sousdepots("/arbre")[0] is False


def test_git_interroge_l_arbre_demande_et_capture_sa_sortie(monkeypatch):
    """`cwd or ROOT` : sans arbre explicite on juge le depot principal, avec
    arbre on juge le worktree. Inverser cela ferait bisecter le mauvais arbre —
    et `capture_output=False` rendrait toute lecture de stdout vide."""
    import forge_bisect as B

    vus = {}

    def _faux_run(argv, **kw):
        vus.update(kw)
        vus["argv"] = argv
        return _Retour(0, "ok")

    monkeypatch.setattr(B.subprocess, "run", _faux_run)
    B._git(["status"], cwd="/le/worktree")
    assert vus["cwd"] == "/le/worktree"
    assert vus["capture_output"] is True and vus["text"] is True
    B._git(["status"])
    assert vus["cwd"] == B.ROOT


def test_le_worktree_vit_dans_un_scratch_durable_pas_dans_tmp():
    """Le worktree jetable ne doit PAS atterrir dans le temp systeme (C:/tmp,
    volatile, purge -- incident wrapper 2026-08-12), mais dans sandbox/ :
    gitignore, durable, vivant avec le depot. Et jamais dans ROOT lui-meme,
    sinon un checkout de bisect ferait basculer le code du hub en vol."""
    import forge_bisect as B

    assert "tempfile" not in B._SCRATCH.lower()
    assert B._SCRATCH.replace("\\", "/").endswith("sandbox/bisect")
    import inspect
    src = inspect.getsource(B.executer)
    assert "_SCRATCH" in src and "worktree" in src and "add" in src


def test_l_amorce_namespace_MORD_quand_le_script_est_lance_par_chemin():
    """MUTANT SURVIVANT tue le 2026-09-10 (genre `comparaison`, ligne 36).

    MEME ligne que dans `forge_release_lock` — l'amorce que la migration PyPI a
    injectee dans 973 fichiers :

        if _RACINE_AMORCE not in _sys_amorce.path:
            _sys_amorce.path.insert(0, _RACINE_AMORCE)

    Les deux survivants du cliquet n'etaient donc pas deux regressions mais UNE
    classe de code neuf sans garde. `sys.path[0]` vaut `tools/`, pas la racine :
    sans l'amorce, `from nokido_agent...` (L80) leve ModuleNotFoundError des que
    ce fichier est lance par chemin.

    Chemin REEL : interpreteur neuf, cwd tiers, aucun PYTHONPATH, chargement
    HORS `__main__`. Un `--help` ne mordrait pas — l'import vit dans une
    fonction.
    """
    import os
    import subprocess
    import tempfile

    script = ROOT / "tools" / "forge_bisect.py"
    programme = (
        "import importlib.util as u;"
        f"s=u.spec_from_file_location('_sous_test', r'{script}');"
        "m=u.module_from_spec(s); s.loader.exec_module(m);"
        "import nokido_agent.app.forge_python_bin;"
        "print('AMORCE_OK')"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONNOUSERSITE"] = "1"
    with tempfile.TemporaryDirectory() as ailleurs:
        # `errors="replace"` : un sous-processus peut cracher des octets non
        # decodables, et `_readerthread` meurt alors en plein vol (incident 47 Go
        # garde par le gate firehose). Un test qui explose sur l'encodage de sa
        # propre sortie ne mesure plus rien.
        r = subprocess.run([sys.executable, "-c", programme], cwd=ailleurs,
                           env=env, capture_output=True, text=True,
                           errors="replace", timeout=180)
    assert "AMORCE_OK" in r.stdout, (
        "l'amorce n'a pas mis la racine du depot dans sys.path : lance par "
        f"chemin, ce script ne peut pas importer nokido_agent (rc={r.returncode})\n"
        f"stdout={r.stdout[-500:]}\nstderr={r.stderr[-800:]}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
