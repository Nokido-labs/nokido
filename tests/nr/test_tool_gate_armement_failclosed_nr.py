"""NR — l'armement du tool_gate ne doit jamais se DÉSARMER sur un inconnu.

Mesure du 2026-09-12 (audit adversarial, étape M1 « prouver enforced ») :

    ENV LAFORGE_THIN_CLIENT_ENFORCE : <absent>
    sentinelle C:/tmp/nokido_thin_enforce : True
    _enforce_on() : True   <- armé UNIQUEMENT par un fichier hors dépôt

`forge_tool_gate` est le composant qui refuse les écritures natives (Write/Edit)
sur le dépôt Nokido. Son armement repose sur :

    env == "1"                         -> armé
    sinon Path("C:/tmp/...").exists()  -> armé si le fichier est là
    sinon / exception                  -> DÉSARMÉ

Trois chemins de désarmement, dont un silencieux : `except Exception: return
False`. Un chemin illisible (ACL, I/O, disque plein, volume démonté) n'est pas
« pas armé », c'est un INCONNU — et un inconnu ne doit jamais valoir ALLOW.
C'est l'invariant G1 de l'audit (`NO_VERDICT / UNAVAILABLE -> DENY`), et la
première ligne de la constitution sémantique (`UNKNOWN` ≠ `NO`).

Le second défaut est de conception : l'enforcement dépend d'un artefact NON
VERSIONNÉ dans un répertoire temporaire accessible à tout process. Un `del` le
désarme, et rien ne le dit. Le corps a déjà payé ce motif avec la copie figée
`C:\\tmp\\wake_llama_native.py`, antérieure de six semaines au code du dépôt.

ÉTAT ATTENDU DE CE FICHIER : `test_inconnu_ne_desarme_pas` est ROUGE tant que le
correctif n'est pas posé. C'est voulu — le NR précède le correctif.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

tg = pytest.importorskip("forge_tool_gate")


def _recharger():
    """Le module relit son environnement à l'import : on le recharge pour que le
    monkeypatch porte sur l'objet réellement utilisé, pas sur une copie."""
    return importlib.reload(tg)


def test_l_armement_est_lisible():
    """Contrôle positif : sans lui, un test vert ne prouverait rien."""
    m = _recharger()
    assert hasattr(m, "_enforce_on"), "le point d'armement a changé de nom"
    assert isinstance(m._enforce_on(), bool)


def test_env_explicite_arme(monkeypatch):
    """La voie explicite reste la voie explicite."""
    m = _recharger()
    monkeypatch.setenv("LAFORGE_THIN_CLIENT_ENFORCE", "1")
    assert m._enforce_on() is True


def test_inconnu_ne_desarme_pas(monkeypatch):
    """ROUGE ATTENDU avant correctif.

    Le support de la sentinelle est ILLISIBLE — ni présent ni absent : inconnu.
    Un garde qui répond « pas armé » à cette question fabrique une autorisation
    à partir d'une panne de lecture.
    """
    m = _recharger()
    monkeypatch.delenv("LAFORGE_THIN_CLIENT_ENFORCE", raising=False)

    class _CheminIllisible(type(Path("."))):
        def exists(self, *a, **k):
            raise PermissionError("support illisible (ACL / volume demonte)")

    monkeypatch.setattr(m, "Path", lambda *a, **k: _CheminIllisible("C:/tmp/x"))
    assert m._enforce_on() is True, (
        "FAIL-OPEN : une sentinelle ILLISIBLE desarme le gate. "
        "Un inconnu doit valoir DENY, jamais ALLOW."
    )


def test_l_armement_ne_depend_pas_d_un_artefact_hors_depot(monkeypatch):
    """ROUGE ATTENDU avant correctif.

    Sans variable et sans sentinelle, l'état doit rester PROTÉGÉ. Faire dépendre
    l'enforcement d'un fichier non versionné de `C:/tmp` le rend effaçable par
    n'importe quel process, sans trace.
    """
    m = _recharger()
    monkeypatch.delenv("LAFORGE_THIN_CLIENT_ENFORCE", raising=False)

    class _Absent(type(Path("."))):
        def exists(self, *a, **k):
            return False

    monkeypatch.setattr(m, "Path", lambda *a, **k: _Absent("C:/tmp/x"))
    assert m._enforce_on() is True, (
        "FAIL-OPEN : l'absence d'un fichier de C:/tmp desarme le gate. "
        "Le desarmement doit etre EXPLICITE, jamais un defaut."
    )
