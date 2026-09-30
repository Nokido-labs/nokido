# -*- coding: utf-8 -*-
"""NR phase 3 — le captureur juge un WORKTREE DE PREUVE, pas l'arbre partage.

SUITE DU P0. `forge_worktree.create_proof(sha)` fabrique un arbre immuable et
propre ; il reste a ce que le JUGE accepte de le regarder. Tant que le captureur
lit la racine du poste, l'isolation ne sert a rien : la mesure du 2026-09-11 donne
`CAPTURE=False` sur l'arbre partage (119 entrees, 72 bloquantes) et `CAPTURE=True`
sur un worktree de preuve du MEME sha.

CE QUE CE TEST INTERDIT, ET C'EST LE PLUS IMPORTANT : que la phase 3 se resume a
« ne plus rien refuser ». Le garde conservateur doit SURVIVRE — sur un arbre de
travail partage, un fichier inattendu bloque toujours. Un juge plus permissif
n'est pas un juge repare.

TROIS REFUS QUE LE JUGE DOIT SAVOIR NOMMER, parce qu'ils ne se valent pas :

    proof_root absent          on n'a rien a juger
    HEAD != target_sha         le juge se trompe de SUJET — pire que pas de juge
    HEAD attachee a une branche  ce n'est pas un etat immuable, donc pas une preuve

Le dernier point n'est pas de la pedanterie : une branche bouge. Capturer un sha
depuis un worktree attache, c'est promettre qu'on a juge X alors qu'on a juge
« ce que la branche montrait a cet instant ».
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (l.44)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]


def _charger(nom: str, rel: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(args, cwd):
    return subprocess.run(["git", "-c", "safe.directory=*", *args], cwd=str(cwd),
                          capture_output=True, text=True, errors="replace", timeout=180)


@pytest.fixture()
def ci():
    return _charger("ci_local_nr_p3", "tools/ci_local.py")


@pytest.fixture()
def atelier(tmp_path, monkeypatch):
    """Depot jetable + worktree de preuve reel — fixture a la forme reelle."""
    w = _charger("forge_worktree_nr_p3", "tools/forge_worktree.py")
    d = tmp_path / "depot"
    d.mkdir()
    if _git(["init", "-q", "-b", "alpha"], d).returncode != 0:
        pytest.skip("git init indisponible sous ce compte — propriete NON VERIFIEE")
    _git(["config", "user.email", "nr@nokido.local"], d)
    _git(["config", "user.name", "NR"], d)
    (d / "produit.txt").write_text("v1\n", encoding="utf-8")
    _git(["add", "produit.txt"], d)
    _git(["commit", "-q", "-m", "v1"], d)
    sha = _git(["rev-parse", "HEAD"], d).stdout.strip()

    monkeypatch.setattr(w, "ROOT", d)
    monkeypatch.setattr(w, "WT_ROOT", tmp_path / "agents")
    monkeypatch.setattr(w, "PROOF_ROOT", tmp_path / "preuve")
    res = w.create_proof(sha)
    assert not res.get("error"), "create_proof a echoue : %s" % res.get("error")
    return w, d, sha, Path(res["path"])


def test_le_captureur_expose_le_mode_worktree(ci):
    assert hasattr(ci, "capture_depuis_worktree"), (
        "ci_local n'expose pas capture_depuis_worktree : le juge ne peut regarder "
        "qu'une racine de poste, donc l'isolation du P0 ne lui sert a rien")


def test_un_proof_propre_est_capturable(ci, atelier):
    _w, _d, sha, proof = atelier
    ok, motif, ctx = ci.capture_depuis_worktree(proof, target_sha=sha)
    assert ok is True, "un worktree de preuve propre doit etre capturable — %s" % motif
    assert ctx.get("target_sha") == sha
    assert ctx.get("detached") is True


def test_un_proof_sali_est_refuse(ci, atelier):
    """Le garde n'a pas ete desarme, il a change de perimetre."""
    _w, _d, sha, proof = atelier
    (proof / "intrus.txt").write_text("x", encoding="utf-8")
    ok, motif, _ctx = ci.capture_depuis_worktree(proof, target_sha=sha)
    assert ok is False, "un intrus dans le worktree de preuve doit bloquer la capture"
    assert "intrus.txt" in motif, "le refus doit NOMMER ce qui bloque, il a dit : %s" % motif


def test_un_sha_qui_ne_correspond_pas_est_refuse_et_nomme(ci, atelier):
    """Se tromper de sujet est pire que ne pas juger : un verdict serait attribue
    a un sha qui n'a jamais ete mesure."""
    _w, _d, _sha, proof = atelier
    faux = "0" * 40
    ok, motif, _ctx = ci.capture_depuis_worktree(proof, target_sha=faux)
    assert ok is False
    assert "sha" in motif.lower(), "le refus doit dire que le sujet ne correspond pas : %s" % motif


def test_un_proof_absent_est_refuse_et_nomme(ci, tmp_path):
    ok, motif, _ctx = ci.capture_depuis_worktree(tmp_path / "nexiste_pas", target_sha=None)
    assert ok is False
    assert motif, "un refus sans motif ne se distingue pas d'un silence"


def test_l_arbre_partage_reste_juge_severement(ci, atelier):
    """LE test anti-desarmement : l'ancien chemin doit continuer de refuser."""
    _w, d, _sha, _proof = atelier
    (d / "inattendu.txt").write_text("x", encoding="utf-8")
    porcelain = _git(["status", "--porcelain"], d).stdout
    ok, motif = ci.capture_autorisee(ci._lire_porcelain(porcelain))
    assert ok is False, "l'arbre de travail partage doit rester juge severement"
    assert "inattendu.txt" in motif


def test_preparer_reference_DELEGUE_au_createur_canonique(ci, monkeypatch, tmp_path):
    """CONVERGENCE — une seule fonction contient la logique de creation.

    Deux implementations d'un worktree detache coexistaient : `create_proof`
    (forge_worktree, 2026-09-11) et `preparer_reference` (ci_local, 2026-09-09).
    Deux createurs, c'est deux endroits ou corriger un piege, et la garantie qu'ils
    divergeront — l'un refusait l'incoherence quand l'autre rafraichissait.

    On mesure la DELEGATION, pas une ressemblance de texte : un faux module est
    injecte, et `preparer_reference` doit passer par lui.
    """
    import sys as _sys
    import types as _types

    vu = {}

    faux = _types.ModuleType("forge_worktree")

    def create_proof(target_sha, execution_id=None, **kw):
        vu["appel"] = {"target_sha": target_sha, "execution_id": execution_id}
        return {"sha": target_sha, "path": str(tmp_path / "proof_factice"),
                "status": "created", "detached": True}

    faux.create_proof = create_proof
    faux.PROOF_ROOT = tmp_path / "racine_factice"
    monkeypatch.setitem(_sys.modules, "forge_worktree", faux)

    res = ci.preparer_reference("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")

    assert vu.get("appel"), (
        "preparer_reference n'a PAS appele forge_worktree.create_proof : deux "
        "createurs de worktree de preuve coexistent encore")
    assert vu["appel"]["target_sha"].startswith("deadbeef")
    assert res.get("ok") is True, res
    assert res.get("worktree") == str(tmp_path / "proof_factice")


def test_ci_local_ne_cree_plus_de_worktree_lui_meme(ci):
    """Complement STRUCTUREL du test de delegation : le test ci-dessus prouve que
    le chemin passe par le createur canonique, celui-ci prouve qu'aucun second
    chemin ne subsiste a cote. Les deux ensemble, jamais l'un seul — une regex
    seule se fait contourner, un espion seul ne voit pas ce qu'il n'emprunte pas.
    """
    import inspect
    import re as _re
    source = inspect.getsource(ci)
    # `git worktree add` ne doit plus figurer dans ci_local, sous aucune forme.
    restes = _re.findall(r'"worktree"\s*,\s*"add"|worktree\s+add', source)
    assert not restes, (
        "ci_local cree encore un worktree lui-meme (%d site(s)) : la logique doit "
        "vivre UNIQUEMENT dans forge_worktree" % len(restes))


def test_les_sorties_de_run_quittent_l_arbre_juge_en_mode_preuve(monkeypatch, tmp_path):
    """PROOF_DIR doit etre CONSOMME, pas seulement transmis.

    MESURE du 2026-09-11, premier run `--reference` reel : le worktree de preuve
    avait bien recu les gates (`tests/nr/vitalite_gardes.json` y etait ecrit), mais
    PROOF_DIR restait VIDE — 0 entree. Le repertoire etait passe au sous-processus
    et personne ne l'utilisait : un mecanisme present mais non cable est une dette
    de cablage, jamais une securite.

    Et le registre de vitalite est un cliquet COMMITE : l'ecrire dans un worktree
    detache qui sera detruit n'a aucun sens, en plus de salir l'arbre que la capture
    s'apprete a juger. Il ne bloquait la capture que parce que la liste blanche le
    tolere — une tolerance n'est pas une justification.
    """
    proof_dir = tmp_path / "artefacts"
    monkeypatch.setenv("NOKIDO_PROOF_DIR", str(proof_dir))
    m = _charger("ci_local_nr_proofdir", "tools/ci_local.py")

    assert str(proof_dir) in str(m.VITALITE), (
        "le registre de vitalite s'ecrit encore dans l'arbre juge (%s) alors que "
        "PROOF_DIR est declare" % m.VITALITE)
    assert str(proof_dir) in str(m.VITALITE_ATTENTE), (
        "le depot de repli de la vitalite reste dans l'arbre juge : %s" % m.VITALITE_ATTENTE)
    # Le registre n'etait que la moitie du probleme : apres l'avoir sorti, `git
    # status` du worktree juge portait encore `?? sandbox/ci_<compte>/` — basetemp
    # pytest, rapport JUnit, gitconfig. La capture l'acceptait (sandbox/ est une
    # sortie declaree), mais une TOLERANCE n'est pas une justification.
    assert str(proof_dir) in str(m._racine_artefacts("uncompte")), (
        "les artefacts de run (basetemp, JUnit, gitconfig) restent dans l'arbre "
        "juge : %s" % m._racine_artefacts("uncompte"))


def test_hors_mode_preuve_le_registre_reste_le_cliquet_commite(monkeypatch):
    """Anti-faux-positif : sans PROOF_DIR, rien ne bouge. Le registre est un cliquet
    versionne, il doit continuer de vivre dans `tests/nr/` pour les runs ordinaires."""
    monkeypatch.delenv("NOKIDO_PROOF_DIR", raising=False)
    m = _charger("ci_local_nr_normal", "tools/ci_local.py")
    assert str(m.VITALITE).replace("\\", "/").endswith("tests/nr/vitalite_gardes.json"), m.VITALITE
    # Le basetemp par compte reste NECESSAIRE hors mode preuve : deux comptes ne
    # peuvent pas le partager (mesure 2026-09-03, 7 731 « failed on setup »).
    assert "/sandbox/ci_uncompte" in str(m._racine_artefacts("uncompte")).replace("\\", "/"), (
        m._racine_artefacts("uncompte"))


def test_le_mode_reference_transmet_tout_le_contexte_au_sous_processus(ci, monkeypatch, tmp_path):
    """PHASE 7 — prouver le CHEMIN D'EXECUTION, pas seulement le repertoire courant.

    Le piege serait de croire qu'un `cwd=proof` suffit : un script lance depuis le
    bon repertoire peut tres bien referencer un `ROOT` calcule ailleurs, un
    PYTHONPATH herite, un chemin absolu ou un cache qui ramenent vers l'arbre
    partage. Trois choses sont donc verifiees ensemble :

      1. le binaire lance est le `ci_local.py` DU WORKTREE (donc son `ROOT`,
         derive de `__file__`, bascule avec lui) ;
      2. le `cwd` est le worktree ;
      3. l'environnement porte `NOKIDO_PROOF_WORKTREE` et `NOKIDO_TARGET_SHA`,
         sans quoi le juge du sous-processus rendrait `PROOF_ROOT_MISSING` et la
         chaine s'arreterait sans certifier.

    Et `--reference` ne doit pas etre repasse : c'est le drapeau retire qui borne
    la recursion, pas une sentinelle d'environnement qu'un sous-processus peut
    perdre.
    """
    faux_wt = tmp_path / "proof_wt"
    (faux_wt / "tools").mkdir(parents=True)
    (faux_wt / "tools" / "ci_local.py").write_text("# factice\n", encoding="utf-8")
    sha = "abc123def456abc123def456abc123def456abcd"

    monkeypatch.setattr(ci, "preparer_reference",
                        lambda *a, **k: {"ok": True, "worktree": str(faux_wt),
                                         "sha": sha, "motif": ""})
    vu = {}

    class _Res:
        returncode = 0

    def faux_run(cmd, **kw):
        vu["cmd"] = list(cmd)
        vu["kw"] = kw
        return _Res()

    monkeypatch.setattr(ci.subprocess, "run", faux_run)
    monkeypatch.setattr("sys.argv", ["ci_local.py", "--reference", sha])

    rc = ci.main()
    assert rc == 0
    assert vu, "le mode reference n'a lance aucun sous-processus"

    assert str(faux_wt) in vu["cmd"][1], (
        "le sous-processus ne lance pas le ci_local DU WORKTREE (%s) : son ROOT "
        "resterait celui de l'arbre partage" % vu["cmd"][1])
    assert str(vu["kw"].get("cwd")) == str(faux_wt), "cwd != worktree de preuve"
    assert "--reference" not in vu["cmd"], "le drapeau est repasse : recursion non bornee"

    env = vu["kw"].get("env")
    assert env is not None, (
        "aucun environnement transmis : le juge du sous-processus rendra "
        "PROOF_ROOT_MISSING et rien ne sera certifie")
    assert env.get("NOKIDO_PROOF_WORKTREE") == str(faux_wt)
    assert env.get("NOKIDO_TARGET_SHA") == sha
    assert env.get("NOKIDO_PROOF_DIR"), (
        "PROOF_DIR non transmis : les sorties de preuve iraient dans l'arbre juge")
    assert str(faux_wt) not in str(env.get("NOKIDO_PROOF_DIR")), (
        "PROOF_DIR est DANS le worktree juge (%s) : les JUnit, logs et rapports "
        "saliraient l'arbre que la capture s'apprete a juger"
        % env.get("NOKIDO_PROOF_DIR"))


def _espionner(ci, monkeypatch):
    """Remplace les deux juges par des espions. On mesure QUI est appele, pas ce
    qu'une regex trouve dans le source : un appel peut exister dans le texte et
    n'etre jamais atteint, ou l'inverse."""
    vu = {"worktree": [], "autorisee": 0}

    def faux_worktree(proof_root, target_sha=None, execution_id=None):
        vu["worktree"].append({"proof_root": str(proof_root),
                               "target_sha": target_sha,
                               "execution_id": execution_id})
        return True, "espion : capture acceptee", {"entrees": 0, "detached": True}

    def faux_autorisee(entrees):
        vu["autorisee"] += 1
        return True, "espion : NE DEVRAIT PAS ETRE APPELE par le juge de reference"

    monkeypatch.setattr(ci, "capture_depuis_worktree", faux_worktree)
    monkeypatch.setattr(ci, "capture_autorisee", faux_autorisee)
    return vu


def test_le_juge_de_reference_recoit_proof_root_et_target_sha(ci, atelier, monkeypatch, capsys):
    """ETAPE 4 — la capacite existait deja ; ce test verifie qu'elle est CONSOMMEE.

    Un mecanisme present mais non cable est une dette de cablage, jamais une
    securite. Avant ce test, `_inscrire_generation` lisait encore la racine du
    poste : le P0 etait vrai et ne protegeait rien.
    """
    _w, _d, sha, proof = atelier
    vu = _espionner(ci, monkeypatch)
    monkeypatch.setattr(ci, "ROOT", proof)          # les tests ont tourne DANS le proof
    monkeypatch.setenv("NOKIDO_PROOF_WORKTREE", str(proof))
    monkeypatch.setenv("NOKIDO_TARGET_SHA", sha)

    ci._inscrire_generation([("un_gate", True)], partiel=False)
    capsys.readouterr()

    assert vu["worktree"], (
        "le juge de reference n'a PAS appele capture_depuis_worktree : la CI lit "
        "encore l'arbre partage, donc l'isolation du P0 ne la protege pas")
    appel = vu["worktree"][0]
    assert appel["proof_root"] == str(proof), "proof_root n'est pas transmis"
    assert appel["target_sha"] == sha, "target_sha n'est pas transmis"
    assert vu["autorisee"] == 0, (
        "capture_autorisee a ete appelee directement : un repli sur la racine "
        "partagee subsiste dans le chemin de capture")


def test_sans_proof_root_le_juge_REFUSE_au_lieu_de_retomber_sur_la_racine(ci, monkeypatch, capsys):
    """Le repli silencieux est le vrai danger : il rendrait un verdict certifiant
    a partir de l'arbre partage sans que personne ne le voie."""
    vu = _espionner(ci, monkeypatch)
    monkeypatch.delenv("NOKIDO_PROOF_WORKTREE", raising=False)
    monkeypatch.delenv("NOKIDO_TARGET_SHA", raising=False)

    ci._inscrire_generation([("un_gate", True)], partiel=False)
    sortie = capsys.readouterr().out

    assert vu["autorisee"] == 0, "repli sur la racine partagee en l'absence de proof_root"
    assert not vu["worktree"], "un juge sans proof_root ne doit rien juger du tout"
    assert "PROOF_ROOT_MISSING" in sortie, (
        "l'absence de proof_root doit etre NOMMEE, sinon elle se confond avec un "
        "run qui n'avait rien a capturer — sortie : %s" % sortie[:200])


def test_des_tests_joues_hors_du_proof_ne_certifient_pas(ci, atelier, monkeypatch, capsys):
    """Le faux vert que l'etape 4 pourrait fabriquer.

    Juger un arbre PROPRE ou rien n'a ete execute serait pire que le blocage
    actuel : la CI certifierait un sha sur la foi d'un worktree qui n'a jamais vu
    tourner un test. Tant que l'execution vit ailleurs (phase 7), la capture le DIT
    au lieu de certifier.
    """
    _w, d, sha, proof = atelier
    vu = _espionner(ci, monkeypatch)
    monkeypatch.setattr(ci, "ROOT", d)              # tests joues dans l'arbre PARTAGE
    monkeypatch.setenv("NOKIDO_PROOF_WORKTREE", str(proof))
    monkeypatch.setenv("NOKIDO_TARGET_SHA", sha)

    ci._inscrire_generation([("un_gate", True)], partiel=False)
    sortie = capsys.readouterr().out

    assert not vu["worktree"], "on ne capture pas un arbre ou rien n'a tourne"
    assert "TESTS_HORS_PROOF" in sortie, (
        "l'ecart entre l'arbre teste et l'arbre juge doit etre NOMME — sortie : %s"
        % sortie[:200])


def test_une_tete_attachee_n_est_pas_une_preuve(ci, atelier, tmp_path):
    """Une branche bouge : capturer depuis un worktree attache promettrait d'avoir
    juge un sha alors qu'on a juge ce que la branche montrait a cet instant."""
    _w, d, sha, _proof = atelier
    attache = tmp_path / "worktree_attache"
    r = _git(["worktree", "add", "-b", "wip/essai", str(attache), sha], d)
    if r.returncode != 0:
        pytest.skip("git worktree add indisponible ici — propriete NON VERIFIEE")
    ok, motif, ctx = ci.capture_depuis_worktree(attache, target_sha=sha)
    assert ok is False, "un worktree sur une BRANCHE n'est pas un etat immuable"
    assert ctx.get("detached") is False
    assert "detach" in motif.lower() or "branche" in motif.lower(), motif
