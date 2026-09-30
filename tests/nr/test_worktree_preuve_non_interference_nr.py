# -*- coding: utf-8 -*-
"""NR P0 — un worktree d'agent ne peut pas contaminer la preuve d'un sha.

CE QUE CE TEST EMPECHE DE REVENIR (mesure du 2026-09-11 sur alpha 80035fe14) :

    GIT_TREE_CLEAN       = OUI   (0 fichier suivi modifie, 0 stage)
    CAPTURE_TREE_CLEAN   = NON   (70 entrees non suivies, appartenant a d'autres chantiers)

Le juge lisait l'arbre de TRAVAIL partage. Un agent qui n'avait rien pousse — 59
manifestes de veille, des caches de client, des sorties d'audit — suffisait donc a
empecher de capturer le sha d'un commit deja publie et deja vert. Le critere de
sortie de la phase 0 etait inatteignable pour une raison qui n'avait aucun rapport
avec le code juge.

LE REMEDE N'EST PAS UNE LISTE BLANCHE. Declarer ces familles « sures » ferait
dependre la preuve du contenu d'un arbre partage et demanderait une liste
d'exceptions sans fin (demain 74 manifestes, puis un cache, puis un fichier d'agent
imprevu). Et surtout ce serait FAUX : `tests/nr/_socle_capabilites_comptes.json` est
un fichier NON SUIVI qui est LU PAR UN TEST — un non-suivi peut donc changer un
resultat, ce qui interdit aussi bien `--untracked-files=no` que l'elargissement.

Le remede est un CHANGEMENT DE PERIMETRE : le juge n'inspecte plus l'arbre partage,
il inspecte un worktree bati depuis le sha, ou ces fichiers n'existent tout
simplement pas.

INVARIANT ARCHITECTURAL, pas convention de procedure :

    worktree d'agent  !=  worktree de preuve

et un SHA JUGE NE DEVIENT JAMAIS UNE BRANCHE : une preuve represente un etat
immuable, pas une nouvelle ligne de developpement. C'est ce qui distingue
`create()` (branche `wip/<agent>`, du travail) de `create_proof()` (tete detachee,
du jugement).

DEUX SENS, ET LE SECOND EST OBLIGATOIRE. Prouver qu'un arbre d'agent sale ne bloque
plus ne suffit pas : c'est aussi ce que produirait un garde DESARME. Le second sens
— un intrus DANS le worktree de preuve bloque bien la capture — est ce qui distingue
un garde repare d'un garde supprime.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (l.66)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
MODULE = RACINE / "tools" / "forge_worktree.py"


def _charger():
    """Charge forge_worktree par UN SEUL chemin d'import.

    Deux noms d'import donneraient deux objets distincts, et un monkeypatch sur
    l'un laisserait l'autre intact — faux vert deja paye le 2026-09-10.
    """
    spec = importlib.util.spec_from_file_location("forge_worktree_nr", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(args, cwd):
    return subprocess.run(["git", "-c", "safe.directory=*", *args], cwd=str(cwd),
                          capture_output=True, text=True, errors="replace", timeout=120)


@pytest.fixture()
def depot(tmp_path):
    """Un VRAI depot git jetable a deux commits — fixture a la forme reelle.

    Un faux objet ne prouverait rien ici : c'est le comportement de `git worktree`
    qui est en cause, pas notre facon de l'appeler.
    """
    d = tmp_path / "depot"
    d.mkdir()
    if _git(["init", "-q", "-b", "alpha"], d).returncode != 0:
        pytest.skip("git init indisponible sous ce compte — propriete NON VERIFIEE")
    _git(["config", "user.email", "nr@nokido.local"], d)
    _git(["config", "user.name", "NR"], d)
    (d / "produit.txt").write_text("v1\n", encoding="utf-8")
    _git(["add", "produit.txt"], d)
    _git(["commit", "-q", "-m", "v1"], d)
    sha1 = _git(["rev-parse", "HEAD"], d).stdout.strip()
    (d / "produit.txt").write_text("v2\n", encoding="utf-8")
    _git(["commit", "-qam", "v2"], d)
    sha2 = _git(["rev-parse", "HEAD"], d).stdout.strip()
    return d, sha1, sha2


@pytest.fixture()
def mod(depot, tmp_path, monkeypatch):
    d, _s1, _s2 = depot
    m = _charger()
    monkeypatch.setattr(m, "ROOT", d)
    monkeypatch.setattr(m, "WT_ROOT", tmp_path / "worktrees_agents")
    if hasattr(m, "PROOF_ROOT"):
        monkeypatch.setattr(m, "PROOF_ROOT", tmp_path / "worktrees_preuve")
    return m


def test_le_module_expose_un_mode_preuve(mod):
    """Sans ce mode, le juge n'a pas d'autre choix que l'arbre partage."""
    assert hasattr(mod, "create_proof"), (
        "forge_worktree n'expose pas create_proof : le worktree de preuve n'existe pas, "
        "le juge lit donc l'arbre de travail partage")
    assert hasattr(mod, "PROOF_ROOT"), "PROOF_ROOT n'est pas declaree"


def test_la_racine_de_preuve_suit_l_environnement(monkeypatch, tmp_path):
    """Le juge doit pouvoir travailler la ou SON compte a le droit d'ecrire.

    MESURE du 2026-09-11, `icacls` sur la racine du superrepo :

        LaForgeTrusted     (RX)              lecture et execution, PAS d'ecriture
        LaForgeSbxOffline  (RX) + (OI)(CI)(R)  lecture seule
        user / SYSTEM / Administrateurs (F)

    Le premier emplacement choisi pour PROOF_ROOT etait donc inaccessible en
    ecriture a TOUS les comptes d'execution, quel que soit le canal — ce n'etait pas
    un probleme de compte mal choisi mais d'emplacement mal choisi. `C:/tmp` et le
    `sandbox/` du depot sont eux inscriptibles (mesure du meme jour), d'ou une
    racine qui se declare au lieu de se supposer.
    """
    cible = tmp_path / "racine_du_juge"
    monkeypatch.setenv("NOKIDO_PROOF_ROOT", str(cible))
    m = _charger()
    assert Path(str(m.PROOF_ROOT)) == cible, (
        "PROOF_ROOT ignore NOKIDO_PROOF_ROOT : le juge ne peut pas etre place la ou "
        "son compte ecrit, il a lu %s" % m.PROOF_ROOT)


def test_les_deux_racines_sont_disjointes(mod):
    """INVARIANT : un worktree de preuve ne vit jamais sous la racine des agents,
    sinon un agent nomme « proof » entrerait en collision avec le juge."""
    wt = Path(str(mod.WT_ROOT)).resolve()
    pr = Path(str(mod.PROOF_ROOT)).resolve()
    assert wt != pr, "WT_ROOT et PROOF_ROOT sont la meme racine"
    assert not str(pr).startswith(str(wt) + "\\") and not str(pr).startswith(str(wt) + "/"), (
        "PROOF_ROOT (%s) vit SOUS WT_ROOT (%s) : l'invariant n'est pas structurel" % (pr, wt))


def test_le_proof_est_detache_et_ne_cree_aucune_branche(mod, depot):
    """Un sha juge represente un etat IMMUABLE : il ne devient pas une ligne de dev."""
    d, sha1, _sha2 = depot
    avant = set(_git(["branch", "--format=%(refname:short)"], d).stdout.split())
    res = mod.create_proof(sha1)
    assert res.get("error") is None, "create_proof a echoue : %s" % res.get("error")
    proof = Path(res["path"])
    tete = _git(["rev-parse", "HEAD"], proof).stdout.strip()
    assert tete == sha1, "le worktree de preuve ne porte pas le sha demande"
    sym = _git(["symbolic-ref", "-q", "HEAD"], proof)
    assert sym.returncode != 0, "HEAD n'est pas detachee : le sha est devenu une branche"
    apres = set(_git(["branch", "--format=%(refname:short)"], d).stdout.split())
    assert apres == avant, "create_proof a cree une branche : %s" % (apres - avant)


def test_un_worktree_agent_sale_n_empeche_pas_la_preuve(mod, depot):
    """SENS 1 — le cas qui bloquait : un agent n'a rien pousse et son arbre est sale."""
    d, sha1, _sha2 = depot
    (d / "produit.txt").write_text("travail non pousse\n", encoding="utf-8")   # fichier SUIVI modifie
    (d / "artefact_non_suivi.json").write_text("{}", encoding="utf-8")          # fichier NON SUIVI
    sale = _git(["status", "--porcelain"], d).stdout.strip()
    assert sale, "le pre-requis du test n'est pas rempli : l'arbre d'agent devrait etre sale"

    proof = Path(mod.create_proof(sha1)["path"])
    propre = _git(["status", "--porcelain"], proof).stdout.strip()
    assert propre == "", (
        "le worktree de preuve est contamine par l'arbre d'agent :\n%s" % propre)


def test_un_proof_existant_sur_un_autre_sha_est_RAFRAICHI(mod, depot):
    """Le juge doit obtenir le sha DEMANDE, sans fabriquer un second worktree.

    Cette propriete vient de `ci_local.preparer_reference`, ecrit le 2026-09-09 :
    « un worktree reste au commit ou on l'a laisse, et mesurer sur du code perime
    dirait vrai sur le mauvais objet ». Lors de la convergence vers un createur
    unique, c'est le comportement a GARDER — refuser l'incoherence, comme le
    faisait la premiere version de create_proof, obligerait l'appelant a nettoyer
    a la main ou a multiplier les arbres.
    """
    _d, sha1, sha2 = depot
    un = mod.create_proof(sha1, execution_id="exec-fixe")
    assert not un.get("error"), un
    chemin1 = Path(un["path"])

    deux = mod.create_proof(sha2, execution_id="exec-fixe")
    assert not deux.get("error"), "le rafraichissement a echoue : %s" % deux.get("error")
    assert Path(deux["path"]) == chemin1, "un second worktree a ete cree au lieu d'un refresh"
    tete = _git(["rev-parse", "HEAD"], chemin1).stdout.strip()
    assert tete == sha2, "le worktree porte encore %s au lieu du sha demande %s" % (tete[:12], sha2[:12])
    assert _git(["symbolic-ref", "-q", "HEAD"], chemin1).returncode != 0, "HEAD n'est plus detachee"
    assert deux.get("status") in ("rafraichi", "exists"), deux


def test_deux_executions_ne_se_volent_pas_leur_worktree(mod, depot):
    """Deux juges peuvent mesurer le MEME sha en meme temps.

    Un emplacement unique et global (le `sandbox/ci_reference_wt` historique) les
    ferait se marcher dessus : le second `checkout --force` deplacerait l'arbre que
    le premier est en train de mesurer.
    """
    _d, sha1, _sha2 = depot
    a = mod.create_proof(sha1, execution_id="juge-A")
    b = mod.create_proof(sha1, execution_id="juge-B")
    assert not a.get("error") and not b.get("error"), (a, b)
    assert Path(a["path"]) != Path(b["path"]), (
        "deux executions partagent le meme worktree de preuve : %s" % a["path"])
    for chemin in (a["path"], b["path"]):
        assert _git(["rev-parse", "HEAD"], Path(chemin)).stdout.strip() == sha1


def test_une_racine_non_inscriptible_est_DITE_et_ne_leve_pas(mod, depot, tmp_path):
    """Le module rend des dicts : un refus doit en etre un, pas une exception.

    MESURE du 2026-09-11 : sur le depot reel, `PROOF_ROOT.mkdir()` a leve
    `PermissionError [WinError 5]` — le compte sandbox n'ecrit pas dans le profil
    owner, donc creer le worktree est un geste OWNER. C'est un refus legitime, mais
    il remontait en exception et cassait l'appelant, la ou tout le reste du module
    rend `{"error": ...}`. Un outil dit son refus ; il n'explose pas chez celui qui
    l'appelle, sinon l'ACL se lit comme une panne.
    """
    d, sha1, _sha2 = depot
    obstacle = tmp_path / "racine_impossible"
    obstacle.write_text("je suis un fichier, pas un repertoire\n", encoding="utf-8")
    mod.PROOF_ROOT = obstacle          # mkdir() dessus ne peut pas aboutir

    res = mod.create_proof(sha1)       # ne doit PAS lever
    assert isinstance(res, dict), "create_proof doit rendre un dict, meme en refus"
    assert res.get("error"), "un refus d'ecriture doit etre NOMME dans le resultat"


def test_un_intrus_dans_le_proof_bloque_bien_la_capture(mod, depot):
    """SENS 2 — sans lui, on ne distingue pas un garde repare d'un garde desarme."""
    d, sha1, _sha2 = depot
    proof = Path(mod.create_proof(sha1)["path"])
    assert _git(["status", "--porcelain"], proof).stdout.strip() == ""
    (proof / "intrus.txt").write_text("je ne devrais pas etre la\n", encoding="utf-8")
    apres = _git(["status", "--porcelain"], proof).stdout.strip()
    assert apres != "", "un fichier depose dans le worktree de preuve passe inapercu"
    assert "intrus.txt" in apres
