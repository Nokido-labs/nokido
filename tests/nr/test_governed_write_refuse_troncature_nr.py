# -*- coding: utf-8 -*-
"""NR (31/10, derogation owner tracee) : governed_write refuse une reecriture qui TRONQUE un fichier existant.

Preuve 31/10 (actes_agents.jsonl + mcp_audit.log) : le 27/10 02:24:13, VIBE_HEADLESS a appele governed_edit
content="..." sur app/forge_byte_router.py -- 314 lignes remplacees par 3 caracteres, verdict ok (« relecture disque
identique » : l'outil relit ce qu'il vient d'ecrire). Meme classe : 19/10 (forge_token_monitor 681 -> 71 lignes) et
21/10 (2 NR perdus par content=). Regle : un contenu PLACEHOLDER (« ... ») a la place d'un fichier non vide, ou une
reduction sous le quart d'un fichier d'au moins 50 lignes, est REFUSE (blocked=troncature) et le fichier reste
intact. Petits fichiers et creations : inchanges.
"""
# pylint: disable=missing-function-docstring,protected-access
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_governed_edit as ge  # noqa: E402


@pytest.fixture(autouse=True)
def _sans_verrou(monkeypatch):
    monkeypatch.setattr(ge, "_tree_lock_check_and_claim", lambda rel, agent: [])


def _fichier(tmp_path, n, nom="module.md"):
    p = tmp_path / nom
    p.write_text("".join("ligne %d du module\n" % i for i in range(n)), encoding="utf-8")
    return p


@pytest.mark.parametrize("contenu", ["...", "…", "  ...\n", "# ..."])
def test_placeholder_a_la_place_d_un_fichier_refuse(tmp_path, contenu):
    p = _fichier(tmp_path, 314)
    avant = p.read_text(encoding="utf-8")
    v = ge.governed_write(str(p), contenu, agent="VIBE_HEADLESS")
    assert v["ok"] is False and v["blocked"] == "troncature", v
    assert p.read_text(encoding="utf-8") == avant


def test_reduction_sous_le_quart_refusee(tmp_path):
    p = _fichier(tmp_path, 300)
    v = ge.governed_write(str(p), "".join("x %d\n" % i for i in range(40)), agent="CLAUDE")
    assert v["ok"] is False and v["blocked"] == "troncature"
    assert "300" in v["reason"] and "40" in v["reason"]


def test_reduction_moderee_acceptee(tmp_path):
    p = _fichier(tmp_path, 300)
    v = ge.governed_write(str(p), "".join("x %d\n" % i for i in range(200)), agent="CLAUDE")
    assert v["ok"] is True, v


def test_petit_fichier_et_creation_inchanges(tmp_path):
    p = _fichier(tmp_path, 20)
    assert ge.governed_write(str(p), "x\n", agent="CLAUDE")["ok"] is True
    neuf = tmp_path / "neuf.md"
    assert ge.governed_write(str(neuf), "...", agent="CLAUDE")["ok"] is True
