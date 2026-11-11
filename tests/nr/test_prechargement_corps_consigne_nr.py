# fake
import re
import pytest
from pathlib import Path
from tools.forge_task_executor import precharger_corps_consigne, ROOT

def test_securite_refus_hors_depot(tmp_path: Path):
    # Chemin hors depot
    f = tmp_path / "externe.py"
    f.write_text("def secret_externe(): pass\n", encoding="utf-8")
    consigne = f"Regarde dans {f} secret_externe et corrige."
    res = precharger_corps_consigne(consigne, workdir=tmp_path)
    assert "[PRECHARGEMENT refuse: externe.py]" in res
    # Le corps extrait ne doit pas etre present
    assert "def secret_externe():" not in res

def test_securite_refus_env_et_dossiers_interdits():
    # .env sous le depot
    f_env = ROOT / ".env"
    consigne = f"Inspecte {f_env}:1 et dis-moi."
    res = precharger_corps_consigne(consigne)
    assert "[PRECHARGEMENT refuse: .env]" in res

    # sandbox
    f_sb = ROOT / "sandbox" / "test_fake.py"  # fake
    consigne2 = f"Inspecte {f_sb} test_fake et dis-moi."
    res2 = precharger_corps_consigne(consigne2)
    assert "[PRECHARGEMENT refuse: test_fake.py]" in res2

def test_securite_refus_traversal_points():
    # '..' tentant de sortir
    f_trav = ROOT / "tools" / ".." / ".." / "secret.py"  # fake
    consigne = f"Inspecte {f_trav} hack"
    res = precharger_corps_consigne(consigne)
    assert "[PRECHARGEMENT refuse: secret.py]" in res

def test_securite_refus_motifs_sensibles():
    # Fichier contenant 'secret', 'token', 'key'
    f_sec = ROOT / "tools" / "test_secret_keeper.py"  # fake
    consigne = f"Inspecte {f_sec} algo"
    res = precharger_corps_consigne(consigne)
    assert "[PRECHARGEMENT refuse: test_secret_keeper.py]" in res

def test_precharger_corps_fonction_depot():
    # Fichier valide du depot
    f = ROOT / "tools" / "forge_task_executor.py"
    consigne = f"Regarde dans {f} _absolutiser_chemins et verifie."
    res = precharger_corps_consigne(consigne)
    assert "[PRECHARGEMENT" in res
    assert "def _absolutiser_chemins" in res
    assert "base = str(workdir).rstrip" in res

def test_precharger_corps_ligne_depot(tmp_path: Path):
    wd = tmp_path / "wt"
    (wd / "tools").mkdir(parents=True)
    (wd / "tools" / "m.py").write_text("def f():\n    a = 1\n    return a\n", encoding="utf-8")
    res = precharger_corps_consigne("Corrige tools/m.py:2", workdir=wd)
    assert "[PRECHARGEMENT" in res
    assert "def f():" in res and "return a" in res

def test_cible_fonction_inexistante_donne_introuvable():
    # _RE_CIBLE_FONCTION avec un symbole qui n'existe pas dans le fichier
    f = ROOT / "tools" / "forge_task_executor.py"
    consigne = f"Inspecte {f} fonction_totalement_imaginaire_xyz"
    res = precharger_corps_consigne(consigne)
    assert "[PRECHARGEMENT introuvable:" in res
    assert "fonction_totalement_imaginaire_xyz" in res

_ENTETE = "\n\n[PRECHARGEMENT corps de code cites dans la consigne]"
_SUFFIXE = "\n... [tronque]\n```"


def _worktree(tmp_path: Path) -> Path:
    wd = tmp_path / "wt"
    (wd / "tools").mkdir(parents=True)
    lignes = "".join(f"    x{i} = {i}  # remplissage\n" for i in range(20))
    (wd / "tools" / "mod.py").write_text("def cible():\n" + lignes + "    return 1\n", encoding="utf-8")
    return wd


def test_cible_absolue_sous_racine_depot_reecrite_vers_worktree(tmp_path: Path):
    wd = _worktree(tmp_path)
    # Precondition : le corps ne peut venir QUE de la reecriture vers `wd`. L'ancienne forme `ROOT not in wd.parents`
    # supposait tmp_path hors du depot ; or le basetemp de la CI de reference vit SOUS le depot
    # (sandbox/workspace/tmp/nokido_proof/..., CI job_d9e2c3a3500b, 7/11) et la precondition y rougissait seule.
    # Ce qu'elle protegeait : que la cible n'existe pas a la racine (sinon le corps viendrait du depot sans reecriture)
    # et que le worktree ne soit pas la racine elle-meme. C'est ce qui est verifie, dans tout emplacement de tmp_path.
    assert not (ROOT / "tools" / "mod.py").exists()
    assert wd.resolve() != ROOT.resolve()
    res = precharger_corps_consigne(f"Regarde {ROOT / 'tools' / 'mod.py'} cible", workdir=wd)
    assert "refuse" not in res
    assert "def cible():" in res


def test_cible_absolue_dans_worktree_acceptee(tmp_path: Path):
    wd = _worktree(tmp_path)
    res = precharger_corps_consigne(f"Regarde {wd / 'tools' / 'mod.py'} cible", workdir=wd)
    assert "def cible():" in res and "refuse" not in res


def test_autre_worktree_refuse(tmp_path: Path):
    wd = _worktree(tmp_path)
    autre = tmp_path / "autre"
    (autre / "tools").mkdir(parents=True)
    (autre / "tools" / "mod.py").write_text("def cible():\n    return 2\n", encoding="utf-8")
    res = precharger_corps_consigne(f"Regarde {autre / 'tools' / 'mod.py'} cible", workdir=wd)
    assert "[PRECHARGEMENT refuse: mod.py]" in res
    assert "return 2" not in res


def test_plafond_annonce_blocs_ecartes_et_taille_exacte(tmp_path: Path):
    wd = _worktree(tmp_path)
    consigne = f"Inspecte {wd / 'tools' / 'mod.py'} cible"
    plein = precharger_corps_consigne(consigne, workdir=wd, max_caracteres=10000)
    bloc = plein[len(consigne) + len(_ENTETE) + 1:]
    assert len(bloc) >= 350
    res = precharger_corps_consigne(consigne, workdir=wd, max_caracteres=150)
    m = re.search(r"(\d+) bloc\(s\) ecarte\(s\), (\d+) caractere\(s\) non inclus", res)
    assert m
    corps = res[len(consigne) + len(_ENTETE) + 1:res.index(_SUFFIXE)]
    assert len(corps) + len(_SUFFIXE) <= 150
    assert int(m.group(1)) == 0
    assert int(m.group(2)) == len(bloc) - len(corps)


def test_plafond_petit_respecte(tmp_path: Path):
    wd = _worktree(tmp_path)
    consigne = f"Inspecte {wd / 'tools' / 'mod.py'} cible"
    plein = precharger_corps_consigne(consigne, workdir=wd, max_caracteres=10000)
    bloc = plein[len(consigne) + len(_ENTETE) + 1:]
    # plafond 50 respecte (et non releve a 100) : bloc tronque, suffixe compris <= 50
    res = precharger_corps_consigne(consigne, workdir=wd, max_caracteres=50)
    corps = res[len(consigne) + len(_ENTETE) + 1:res.index(_SUFFIXE)]
    assert len(corps) + len(_SUFFIXE) <= 50
    m = re.search(r"(\d+) bloc\(s\) ecarte\(s\), (\d+) caractere\(s\) non inclus", res)
    assert m and int(m.group(1)) == 0 and int(m.group(2)) == len(bloc) - len(corps)
    # plafond trop petit pour le suffixe : bloc ecarte en entier
    res = precharger_corps_consigne(consigne, workdir=wd, max_caracteres=10)
    assert "def cible" not in res
    m = re.search(r"(\d+) bloc\(s\) ecarte\(s\), (\d+) caractere\(s\) non inclus", res)
    assert m and int(m.group(1)) == 1 and int(m.group(2)) == len(bloc)


def test_introuvable_consomme_budget(tmp_path: Path):
    wd = _worktree(tmp_path)
    consigne = "Inspecte tools/absent.py:10 puis tools/mod.py cible"
    ligne = "[PRECHARGEMENT introuvable: tools/absent.py:10 (fichier absent)]"
    plein = precharger_corps_consigne("Inspecte tools/mod.py cible", workdir=wd, max_caracteres=10000)
    bloc = plein[len("Inspecte tools/mod.py cible") + len(_ENTETE) + 1:]
    # budget = exactement la ligne introuvable : plus rien pour le bloc, ecarte en entier
    res = precharger_corps_consigne(consigne, workdir=wd, max_caracteres=len(ligne) + 1)
    assert ligne in res
    assert "def cible" not in res
    m = re.search(r"(\d+) bloc\(s\) ecarte\(s\), (\d+) caractere\(s\) non inclus", res)
    assert m and int(m.group(1)) == 1 and int(m.group(2)) == len(bloc)


@pytest.mark.parametrize("nom", [".ENV", ".Env.local"])
def test_refus_env_casse_variable(tmp_path: Path, nom):
    wd = _worktree(tmp_path)
    (wd / "config").mkdir()
    (wd / "config" / nom).write_text("def a():\n    return 'S'\n", encoding="utf-8")
    res = precharger_corps_consigne(f"Vois {wd / 'config' / nom}:1", workdir=wd)
    assert f"[PRECHARGEMENT refuse: {nom}]" in res
    assert "return 'S'" not in res


def test_refus_sandbox_casse_differente(tmp_path: Path):
    wd = _worktree(tmp_path)
    (wd / "SandBox").mkdir()
    (wd / "SandBox" / "x.py").write_text("def a():\n    return 'S'\n", encoding="utf-8")
    res = precharger_corps_consigne(f"Vois {wd / 'SandBox' / 'x.py'} a", workdir=wd)
    assert "[PRECHARGEMENT refuse: x.py]" in res
    assert "return 'S'" not in res


def test_refus_lien_symbolique_sortant(tmp_path: Path):
    wd = _worktree(tmp_path)
    dehors = tmp_path / "dehors.py"
    dehors.write_text("def a():\n    return 'S'\n", encoding="utf-8")
    lien = wd / "tools" / "lien.py"
    try:
        lien.symlink_to(dehors)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"lien symbolique impossible a creer: {e}")
    res = precharger_corps_consigne(f"Vois {lien} a", workdir=wd)
    assert "[PRECHARGEMENT refuse: lien.py]" in res
    assert "return 'S'" not in res

def test_idempotence_et_non_double_injection():
    f = ROOT / "tools" / "forge_task_executor.py"
    consigne = f"Regarde dans {f} _absolutiser_chemins et verifie."
    res1 = precharger_corps_consigne(consigne)
    # Deuxieme passage sur le texte deja precharge
    res2 = precharger_corps_consigne(res1)
    assert res1 == res2
    assert res2.count("[PRECHARGEMENT corps de code cites dans la consigne]") == 1
