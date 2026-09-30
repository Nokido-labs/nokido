"""NR — l'adaptateur dist ne fabrique plus d'orphelin, et lit son push sur le DISTANT.

Trois defauts mesures le 2026-09-19 sur C:/tmp/nokido-dist :

1. Codeberg refuse tant que le depot est prive (quota). Le clone echouait, et
   l'echec etait lu comme "empty/absent remote" avant un `git init` : historique
   ORPHELIN (merge-base rc=1, commit racine) pendant que github/main portait bien
   v0.2.0. Un REFUS n'est pas un VIDE.
2. Le miroir n'etait jamais essaye, alors qu'il portait l'historique.
3. Les deux `git push` tournaient en check=False sans qu'aucun verdict ne soit lu :
   un rejet non-fast-forward passait pour un succes. Et le rc d'un push MENT dans
   les deux sens (mesure 2026-08-29).

Plus une fuite : `run()` imprimait la commande entiere, donc l'URL avec son PAT,
dans une sortie qui part en journal de job archive ET indexe.
"""
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
fdp = importlib.import_module("forge_dist_publish")

# 2026-09-20 — le credential est SORTI de ces URL. La voie de publication refuse
# desormais une URL porteuse de jeton (il finirait dans .git/config et dans
# argv) : le jeton passe par l'environnement du sous-processus git. Ces fixtures
# portaient encore l'ancienne forme et faisaient echouer trois tests — le garde
# etait bon, c'est la fixture qui etait perimee. Le refus lui-meme garde sa
# preuve, juste en dessous : on ne troque pas un rouge contre un trou.
REMOTES = {"codeberg": "https://codeberg.org/n/d.git",
           "github": "https://github.com/n/d.git"}
REMOTES_AVEC_JETON = {"codeberg": "https://u:tok@codeberg.org/n/d.git",
                      "github": "https://u:tok@github.com/n/d.git"}


def _verbe_git(cmd):
    """Le verbe git et ses arguments, en sautant les `-c cle=valeur` de tete.

    La forme des commandes a change le 2026-09-20 : le jeton passe desormais par
    un `credential.helper` injecte en `-c`, donc `cmd[:2] == ["git", "clone"]` ne
    matche plus rien. Les assertions qui testaient une POSITION testaient la mise
    en forme, pas le comportement — et l'une d'elles etait un FAUX VERT LATENT :
    `not any(c[:2] == ["git", "init"])` serait reste vert meme si `git init`
    avait bel et bien ete appele, puisque `init` n'est plus en position 1.
    """
    i = 1
    while i + 1 < len(cmd) and cmd[i] == "-c":
        i += 2
    return cmd[i:]


def _faux_run(reponses, journal):
    """`reponses` : {(fragments de la commande): (rc, stdout)}. Defaut : rc=0, vide."""
    def _r(cmd, cwd=None, check=True, capture=False, env=None):
        journal.append(list(cmd))
        ligne = " ".join(cmd)
        for cle, (rc, out) in reponses.items():
            if all(frag in ligne for frag in cle):
                return SimpleNamespace(returncode=rc, stdout=out,
                                       stderr="refus simule" if rc else "")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return _r


@pytest.fixture(autouse=True)
def _coffre_neutralise(monkeypatch):
    """Le COFFRE ne doit decider d'aucun NR — sinon le test mesure la machine.

    `_etat_distant` et `push_remotes` passent `env=_env_git()` a `run(...)`.
    C'est un ARGUMENT : il est evalue AVANT que la substitution de `run` ne
    prenne effet, donc mocker `run` ne protege de rien. `_env_git` appelle
    `_jeton_github()`, qui sort en `SystemExit` quand le coffre est vide.

    Ces huit tests passaient sur un poste dont le coffre porte un jeton, et sont
    tombes sur le runner GitHub qui n'en a pas (run 35508916105, 2026-09-20) :

        SystemExit: [auth] REFUS : aucun jeton (GH_TOKEN, GITHUB_TOKEN) dans le
        coffre. Le depot dist est PRIVE ...

    On neutralise LE COFFRE, pas `_env_git` : cette derniere continue de
    s'executer pour de vrai, donc sa construction d'environnement reste couverte.
    `raising=True` est voulu — si `_jeton_github` disparaissait, ce garde doit
    tomber au lieu de se taire.
    """
    monkeypatch.setattr(fdp, "_jeton_github", lambda: "JETON_DE_TEST",
                        raising=True)


# ---------------------------------------------------------------- fuite de secret

def test_une_url_porteuse_de_jeton_n_est_JAMAIS_imprimee():
    brut = "git clone https://user:ghp_UNJETONBIDON@codeberg.org/n/d.git /tmp/x"
    propre = fdp._sans_secret(brut)
    assert "ghp_UNJETONBIDON" not in propre
    assert "user" not in propre
    assert "codeberg.org/n/d.git" in propre, "on masque le credential, pas la destination"
    assert fdp._sans_secret("git clone https://codeberg.org/n/d.git") == \
        "git clone https://codeberg.org/n/d.git", "une URL sans credential reste lisible"


# ------------------------------------------------------- un refus n'est pas un vide

def test_un_remote_qui_refuse_est_ILLISIBLE_pas_VIDE(monkeypatch):
    monkeypatch.setattr(fdp, "run", _faux_run({("ls-remote",): (128, "")}, []))
    etat, detail = fdp._etat_distant(REMOTES["codeberg"])
    assert etat == "ILLISIBLE" and detail, "un refus muet se lirait comme un vide"


def test_un_remote_vraiment_vide_est_VIDE_et_un_remote_peuple_PORTE(monkeypatch):
    monkeypatch.setattr(fdp, "run", _faux_run({("ls-remote",): (0, "")}, []))
    assert fdp._etat_distant(REMOTES["github"])[0] == "VIDE"
    monkeypatch.setattr(fdp, "run", _faux_run(
        {("ls-remote",): (0, "9a75a53\trefs/heads/main\n")}, []))
    assert fdp._etat_distant(REMOTES["github"])[0] == "PORTE"


# ------------------------------------------------------------- pas d'orphelin

def test_un_remote_ILLISIBLE_REFUSE_au_lieu_d_initialiser(tmp_path, monkeypatch):
    """Le scenario EXACT du 2026-09-19 : codeberg refuse, et on initialisait."""
    journal = []
    monkeypatch.setattr(fdp, "run", _faux_run({("ls-remote",): (128, "")}, journal))
    with pytest.raises(SystemExit) as e:
        fdp.ensure_dist_repo(tmp_path / "d", REMOTES)
    motif = str(e.value)
    assert "ILLISIBLE" in motif and "orphelin" in motif
    assert "codeberg" in motif and "github" in motif, "nommer CHAQUE remote et son etat"
    assert not any(_verbe_git(c)[:1] == ["init"] for c in journal), \
        "initialiser par-dessus un historique non lu est precisement le defaut"


def test_le_MIROIR_est_essaye_quand_le_primaire_refuse(tmp_path, monkeypatch):
    journal = []
    monkeypatch.setattr(fdp, "run", _faux_run({
        ("ls-remote", "codeberg.org"): (128, ""),
        ("ls-remote", "github.com"): (0, "9a75a53\trefs/heads/main\n"),
    }, journal))

    fdp.ensure_dist_repo(tmp_path / "d", REMOTES)

    clones = [_verbe_git(c) for c in journal if _verbe_git(c)[:1] == ["clone"]]
    assert len(clones) == 1 and "github.com" in clones[0][1], \
        "le miroir portait l'historique et n'etait jamais essaye"
    assert not any(_verbe_git(c)[:1] == ["init"] for c in journal)


def test_TOUS_les_remotes_prouves_vides_autorisent_la_premiere_publication(tmp_path, monkeypatch):
    """Le cas legitime doit rester possible : sinon on a ferme au lieu de gouverner."""
    journal = []
    monkeypatch.setattr(fdp, "run", _faux_run({("ls-remote",): (0, "")}, journal))
    fdp.ensure_dist_repo(tmp_path / "d", REMOTES)
    assert any(_verbe_git(c)[:1] == ["init"] for c in journal)


def test_une_URL_porteuse_de_credential_est_REFUSEE_a_la_publication(tmp_path,
                                                                     monkeypatch):
    """Le durcissement garde sa preuve — sinon nettoyer les fixtures le desarmait.

    Un jeton dans l'URL finirait dans `.git/config` ET dans `argv` : il doit
    passer par l'environnement du sous-processus git. Ce test est le pendant
    NEGATIF du nettoyage de `REMOTES` fait le 2026-09-20 : sans lui, on aurait
    rendu trois tests verts en retirant du meme coup la couverture du garde.
    """
    monkeypatch.setattr(fdp, "run", _faux_run({("ls-remote",): (0, "")}, []))
    with pytest.raises(SystemExit) as e:
        fdp.ensure_dist_repo(tmp_path / "d", REMOTES_AVEC_JETON)
    motif = str(e.value)
    assert "credential" in motif, motif
    assert "tok" not in motif, "le refus ne doit pas reimprimer le jeton : %s" % motif


# --------------------------------------------------- le verdict se lit sur le distant

@pytest.fixture
def _porte_ouverte(monkeypatch):
    monkeypatch.setitem(sys.modules, "forge_publication_gate",
                        SimpleNamespace(porte_publique=lambda: (True, "")))


def test_un_push_rejete_ne_passe_PAS_pour_un_succes(tmp_path, monkeypatch, _porte_ouverte):
    journal = []
    monkeypatch.setattr(fdp, "run", _faux_run({
        ("rev-parse", "HEAD"): (0, "21450f4aaaaaaaaa\n"),
        ("ls-remote",): (0, "9a75a53bbbbbbbbb\trefs/heads/main\n"),  # distant != local
    }, journal))
    with pytest.raises(SystemExit) as e:
        fdp.push_remotes(tmp_path, REMOTES, "0.20.2", do_push=True)
    assert "aucun remote ne porte le commit local" in str(e.value)


def test_un_ls_remote_refuse_donne_ILLISIBLE_jamais_PUBLIE(tmp_path, monkeypatch,
                                                           _porte_ouverte, capsys):
    journal = []
    monkeypatch.setattr(fdp, "run", _faux_run({
        ("rev-parse", "HEAD"): (0, "21450f4aaaaaaaaa\n"),
        ("ls-remote",): (128, ""),
    }, journal))
    with pytest.raises(SystemExit):
        fdp.push_remotes(tmp_path, REMOTES, "0.20.2", do_push=True)
    sortie = capsys.readouterr().out
    assert "ILLISIBLE" in sortie and "NON PROUVEE" in sortie
    assert "PUBLIE  " not in sortie.replace("NON PUBLIE", "")


def test_un_push_REUSSI_est_reconnu_malgre_un_rc_menteur(tmp_path, monkeypatch,
                                                         _porte_ouverte, capsys):
    """Mesure 2026-08-29 : rc=1 sur un push qui avait PUBLIE (credential store)."""
    journal = []
    monkeypatch.setattr(fdp, "run", _faux_run({
        ("rev-parse", "HEAD"): (0, "21450f4aaaaaaaaa\n"),
        ("push",): (1, ""),                       # le rc ment
        ("ls-remote",): (0, "21450f4aaaaaaaaa\trefs/heads/main\n"),
    }, journal))
    fdp.push_remotes(tmp_path, REMOTES, "0.20.2", do_push=True)  # ne leve pas
    assert "PUBLIE" in capsys.readouterr().out
