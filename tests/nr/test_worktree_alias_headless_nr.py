# -*- coding: utf-8 -*-
"""NR (31/10, choix owner « alias + refus ») : une identite *_HEADLESS n'ecrit JAMAIS dans l'arbre partage.

Preuve 31/10 (logs/actes_agents.jsonl + logs/mcp_audit.log) : le 27/10 a 02:23:53 et 02:24:13, VIBE_HEADLESS
(ring 1) appelait governed_edit content= sur docs/enquetes/consolidator_debit_disque_20261026.md (44 car.) puis
app/forge_byte_router.py (3 car. : « ... », 314 lignes ecrasees) -- DANS L'ARBRE PARTAGE : forge_worktree ne
connaissait que CLAUDE_HEADLESS, ANTIGRAVITY, MISTRAL et OPENCODE_*. Reste 4 jours, CI de reference bloquee.
Regle : alias identite -> worktree de l'executeur (VIBE_HEADLESS -> mistral, CODEX_HEADLESS -> codex,
AGY_HEADLESS / ANTIGRAVITY_HEADLESS -> antigravity) ; toute AUTRE identite *_HEADLESS est REFUSEE tant que son
worktree n'existe pas (creation = geste owner). Owner et identites non executrices : inchanges.
"""
# pylint: disable=missing-function-docstring
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_worktree as W  # noqa: E402


def _wt(tmp_path, *noms):
    for n in noms:
        d = tmp_path / n
        d.mkdir()
        (d / ".git").write_text("gitdir: ailleurs", encoding="utf-8")
    return tmp_path


def test_vibe_headless_ecrit_dans_le_worktree_mistral(tmp_path):
    r = W.cible_ecriture("VIBE_HEADLESS", "", _wt(tmp_path, "mistral"))
    assert r["cible"] == "WORKTREE" and r["racine"].name == "mistral", r


@pytest.mark.parametrize("ident,wt", [("CODEX_HEADLESS", "codex"), ("AGY_HEADLESS", "antigravity"),
                                      ("ANTIGRAVITY_HEADLESS", "antigravity"), ("vibe_headless", "mistral"),
                                      ("CLAUDE_HEADLESS", "claude_headless")])
def test_alias_vers_le_worktree_de_l_executeur(tmp_path, ident, wt):
    r = W.cible_ecriture(ident, "", _wt(tmp_path, wt))
    assert r["cible"] == "WORKTREE" and r["racine"].name == wt, r


def test_alias_sans_worktree_refuse_jamais_partage(tmp_path):
    assert W.cible_ecriture("VIBE_HEADLESS", "", tmp_path)["cible"] == "REFUS"


@pytest.mark.parametrize("ident", ["GEMINI_HEADLESS", "CLINE_HEADLESS", "ROO_HEADLESS", "COPILOT_HEADLESS"])
def test_autre_headless_sans_worktree_refuse(tmp_path, ident):
    r = W.cible_ecriture(ident, "", _wt(tmp_path, "mistral", "codex"))
    assert r["cible"] == "REFUS" and r["raison"], r


@pytest.mark.parametrize("ident", ["CLAUDE", "CIRCADIAN", "TRAY", "SERVICES", ""])
def test_owner_et_identites_non_executrices_inchanges(tmp_path, ident):
    assert W.cible_ecriture(ident, "", tmp_path)["cible"] == "PARTAGE"
