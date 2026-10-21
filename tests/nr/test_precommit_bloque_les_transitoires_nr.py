"""NR -- le pre-commit BLOQUE un fichier transitoire ou un verrou orphelin mis en index.

Demande owner (registre, racine R7, demande_b623ecc7915c, instruite par AGY le 17/10) : « RED verifiant que
tools/forge_git_gate.py precommit bloque avec code non nul tout commit contenant des fichiers staged temporaires ou de
verrouillage runtime (*.lock orphelins hors requirements-ci.lock et vendor.lock, *.tmp, *.swp) ».
Cas frais du meme jour : l'executeur a committe le marqueur de worktree `.nokido.agent` sur la branche d'OPENCODE_GPTOSS
(3c9e89e0c, puis 422690f59, 38f0fa758) -- retire a la main a l'integration. Un marqueur d'identite LOCAL n'a rien a
faire dans l'historique.
Contrat : un fichier AJOUTE transitoire (*.tmp, *.swp, *.swo, *~) ou verrou (*.lock hors liste) est bloque ; un verrou
deja SUIVI qui change n'est pas un orphelin ; `.nokido.agent` est toujours bloque ; le garde est BLOQUANT dans
_precommit (avec le mecanisme de derogation des autres gardes bloquants).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import forge_git_gate as G  # noqa: E402


class _Sortie:
    """Doublure au contrat de subprocess.CompletedProcess que rend le vrai _git."""

    def __init__(self, stdout):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


def test_les_transitoires_ajoutes_sont_bloques():
    ajoutes = ["a.tmp", "x/b.swp", "c.swo", "notes.md~", "sandbox/hub.lock", "requirements-ci.lock", "vendor.lock",
               "tools/ok.py", ".nokido.agent"]
    assert sorted(G._fichiers_transitoires(ajoutes=ajoutes, modifies=[])) == sorted(
        ["a.tmp", "x/b.swp", "c.swo", "notes.md~", "sandbox/hub.lock", ".nokido.agent"])


def test_un_verrou_suivi_qui_change_n_est_pas_un_orphelin():
    assert G._fichiers_transitoires(ajoutes=[], modifies=["deno.lock", "uv.lock", "tools/x.py"]) == []


def test_le_marqueur_de_worktree_est_bloque_meme_modifie():
    assert G._fichiers_transitoires(ajoutes=[], modifies=["sous/.nokido.agent"]) == ["sous/.nokido.agent"]


def test_le_garde_lit_l_index_et_rend_un_code_bloquant(monkeypatch, capsys):
    monkeypatch.setattr(G, "_git", lambda args: _Sortie("A\ta.tmp\nM\tdeno.lock\nA\ttools/x.py\n"))
    assert G._transitoires_gate(["a.tmp", "deno.lock", "tools/x.py"]) != 0
    assert "a.tmp" in capsys.readouterr().out
    monkeypatch.setattr(G, "_git", lambda args: _Sortie("M\tdeno.lock\nA\ttools/x.py\n"))
    assert G._transitoires_gate(["deno.lock", "tools/x.py"]) == 0


def test_le_precommit_appelle_le_garde_comme_bloquant():
    src = inspect.getsource(G._precommit)
    assert "_transitoires_gate(" in src
    assert '_bloquant_ou_derogation("transitoires"' in src
