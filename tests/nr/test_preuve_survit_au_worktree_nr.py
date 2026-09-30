# -*- coding: utf-8 -*-
"""NR — la destruction de l'environnement de preuve ne detruit pas la preuve.

MESURE du 2026-09-11, CI de reference complete (job_9c3776e036d8) : la generation
`GEN-00013.json` a ete ecrite DANS le worktree de preuve. Or ce worktree est
jetable par conception — `remove_proof` le supprime. La preuve vivait donc a
l'endroit exact qu'on detruit apres l'avoir produite.

LE PASSEUR EXISTE DEJA (`tools/forge_generation_inscrire.py`, 2026-09-09) et sa
docstring anticipait precisement ce cas : « sans quoi la preuve reste prisonniere de
l'endroit ou elle a ete produite ». Ce qui manquait n'etait donc pas l'outil, mais
que le PRODUCTEUR depose ailleurs que dans l'arbre jetable.

CONTRAT VISE :

    PROOF_WORKTREE  = environnement de calcul JETABLE
    PROOF_DIR       = preuve DURABLE

et, en consequence directe :

    avant les tests   proof worktree propre
    apres la capture  proof worktree propre — le juge n'ecrit pas dans ce qu'il mesure
    apres destruction la preuve reste lisible

Ce dernier point est le seul qui compte vraiment : une preuve qui ne survit pas a
son propre contexte n'est pas une preuve, c'est une trace d'execution.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (l.47)
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


def test_le_producteur_de_generation_suit_PROOF_DIR(monkeypatch, tmp_path):
    """Sinon la preuve nait dans l'arbre qu'on s'apprete a detruire."""
    proof_dir = tmp_path / "artefacts"
    monkeypatch.setenv("NOKIDO_PROOF_DIR", str(proof_dir))
    g = _charger("forge_generation_nr_proof", "app/forge_generation.py")
    assert str(proof_dir) in str(g.DOSSIER), (
        "les generations s'ecrivent encore dans l'arbre juge (%s)" % g.DOSSIER)
    assert str(proof_dir) in str(g.DOSSIER_ATTENTE), (
        "le depot de repli reste dans l'arbre juge (%s)" % g.DOSSIER_ATTENTE)


def test_la_numerotation_continue_la_sequence_versionnee(monkeypatch, tmp_path):
    """Une preuve qu'on ne peut pas INSCRIRE n'est pas une preuve exploitable.

    MESURE du 2026-09-11, CI de reference complete : en deplacant les generations
    vers PROOF_DIR, j'ai aussi deplace la SEQUENCE -- le numero derive du contenu du
    repertoire, et PROOF_DIR est vierge a chaque execution. Le juge a donc produit
    `GEN-00001`, alors que `docs/generations/GEN-00001.json` existe deja avec un
    autre contenu (statut CANDIDATE contre STABLE). Le passeur etant APPEND-ONLY, il
    aurait refuse la divergence et la preuve serait restee inexploitable.

    La distinction qui corrige cela : la SEQUENCE appartient a l'etat PRODUIT (elle
    est versionnee), l'ARTEFACT appartient au jugement. Le juge lit donc la sequence
    la ou elle vit, et ecrit son artefact ailleurs.
    """
    proof = tmp_path / "artefacts"
    monkeypatch.setenv("NOKIDO_PROOF_DIR", str(proof))
    g = _charger("forge_generation_nr_seq", "app/forge_generation.py")

    versionnees = tmp_path / "versionnees"
    versionnees.mkdir()
    (versionnees / "GEN-00012.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(g, "DOSSIER_SEQUENCE", versionnees)

    assert g._prochain_numero() == 13, (
        "la numerotation est repartie de zero dans le repertoire de preuve : le nom "
        "produit entrerait en collision avec une generation deja versionnee, et le "
        "passeur append-only refuserait de l'inscrire")


def test_hors_mode_preuve_les_generations_restent_versionnees(monkeypatch):
    """Anti-faux-positif. `docs/generations/` est une preuve DURABLE et versionnee :
    un run ordinaire doit continuer de l'alimenter, sinon on corrigerait un defaut
    en en creant un autre."""
    monkeypatch.delenv("NOKIDO_PROOF_DIR", raising=False)
    g = _charger("forge_generation_nr_normal", "app/forge_generation.py")
    assert str(g.DOSSIER).replace("\\", "/").endswith("docs/generations"), g.DOSSIER
    assert "sandbox/generations_en_attente" in str(g.DOSSIER_ATTENTE).replace("\\", "/")


@pytest.fixture()
def atelier(tmp_path, monkeypatch):
    """Depot jetable + worktree de preuve reel."""
    w = _charger("forge_worktree_nr_survie", "tools/forge_worktree.py")
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
    return w, d, sha


def test_la_preuve_survit_a_la_destruction_du_worktree(atelier):
    """LE critere. Un artefact depose hors du worktree doit rester lisible apres
    `git worktree remove` -- c'est ce qui distingue une preuve d'une trace."""
    w, _d, sha = atelier
    res = w.create_proof(sha, execution_id="survie")
    assert not res.get("error"), res
    proof = Path(res["path"])
    proof_dir = proof.parent / "artefacts"
    proof_dir.mkdir(parents=True, exist_ok=True)

    preuve = proof_dir / "GEN-TEMOIN.json"
    preuve.write_text('{"generation": "GEN-TEMOIN", "sha": "%s"}' % sha, encoding="utf-8")
    dans_le_worktree = proof / "docs" / "generations" / "GEN-TEMOIN.json"

    r = w.remove_proof(sha, execution_id="survie")
    assert r.get("status") == "removed", r
    assert not proof.exists(), "le worktree n'a pas ete detruit : le test ne prouve rien"
    assert preuve.exists(), (
        "la preuve a disparu avec le worktree : elle vivait a l'endroit meme qu'on "
        "detruit apres l'avoir produite")
    assert not dans_le_worktree.exists()
    assert "GEN-TEMOIN" in preuve.read_text(encoding="utf-8")


def test_detruire_le_worktree_ne_touche_pas_le_repertoire_de_preuve(atelier):
    """`remove_proof` supprime l'arbre de calcul, jamais les artefacts a cote."""
    w, _d, sha = atelier
    res = w.create_proof(sha, execution_id="voisinage")
    proof = Path(res["path"])
    art = proof.parent / "artefacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / "junit.xml").write_text("<testsuite/>", encoding="utf-8")

    w.remove_proof(sha, execution_id="voisinage")
    assert art.is_dir() and (art / "junit.xml").exists(), (
        "la suppression du worktree a emporte le repertoire de preuve voisin")
