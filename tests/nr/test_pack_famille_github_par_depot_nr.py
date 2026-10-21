"""NR -- une source GitHub a pour FAMILLE son depot (owner/repo), unite de licence du pack (20/10).

La veille physiologie (OpenStax Anatomy and Physiology 2e, CC BY 4.0 au commit b0058a743b) est en base sous
`github:openstax/osbooks-anatomy-physiology/modules/<m>/index.cnxml` (4 577 chunks, vectorises le 20/10). Le pack public
se decoupe par famille = par licence (decision owner 20/10) ; or `famille_source` rendait « github » pour TOUTE source
GitHub : un depot CC BY et un depot sous une autre licence tombaient dans le meme composant. La licence est celle du
DEPOT : la famille d'une source `github:` est `github:<owner>/<repo>`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("pack_famille_github_nr", RACINE / "tools" / "forge_knowledge_pack_export.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("source, famille", [
    ("github:openstax/osbooks-anatomy-physiology/modules/m46685/index.cnxml", "github:openstax/osbooks-anatomy-physiology"),
    ("github:owner/repo", "github:owner/repo"),
    ("github:owner/repo/README.md", "github:owner/repo"),
])
def test_une_source_github_a_pour_famille_son_depot(source, famille):
    assert _module().famille_source(source) == famille


def test_les_autres_familles_ne_bougent_pas():
    m = _module()
    assert m.famille_source("rfc:rfc1349") == "rfc"
    assert m.famille_source("docset:Docker#Install") == "docset:Docker"
    assert m.famille_source("session:2026-06-12:solution") == "session"
