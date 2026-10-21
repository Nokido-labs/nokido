"""NR -- le pack RFC porte, pour CHAQUE RFC, sa legende d'origine mot pour mot (IETF TLP 5.0, 2026-10-20).

Audit AGY (536584cee, docs/audit/ietf_tlp_fragments_20261020.md) : la TLP 5.0 section 3.c.iii permet de redistribuer
des fragments verbatim d'une RFC, attribues a l'IETF et a leur RFC ; au-dela d'un cinquieme d'une RFC reproduit (notre
cas : le pack la livre entiere), ses legendes, notices et mentions d'auteurs doivent l'accompagner (3.c.iii.y, 6.b.i).
Chaque RFC du miroir local (data/rfc_mirror) porte deja ces textes : la section « Copyright Notice » (RFC recentes) ou
« Full Copyright Statement » (avant 2009), et « Authors' Addresses ». On les reprend TELS QUELS : c'est exactement la
legende d'origine, sans rien reecrire. Une RFC dont la legende est illisible est ECARTEE du pack et comptee -- doute =
s'abstenir, jamais une notice inventee.
"""
from __future__ import annotations

import importlib.util
import tarfile
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]

RECENTE = """Internet Engineering Task Force (IETF)                  R. Fielding, Ed.
Request for Comments: 9110                                         Adobe
Category: Standards Track                                      June 2022

Copyright Notice

   Copyright (c) 2022 IETF Trust and the persons identified as the
   document authors.  All rights reserved.

Fielding, et al.             Standards Track                    [Page 2]

RFC 9110                     HTTP Semantics                    June 2022

   This document is subject to BCP 78 and the IETF Trust's Legal
   Provisions Relating to IETF Documents.

Table of Contents

   1.  Introduction

Authors' Addresses

   Roy T. Fielding (editor)
   Adobe
"""
ANCIENNE = """Network Working Group                                         J. Postel
Request for Comments: 1349                                           ISI

Full Copyright Statement

   Copyright (C) The Internet Society (1999).  All Rights Reserved.

Author's Address

   Jon Postel
"""
SANS_LEGENDE = "Request for Comments: 1\n\nIntroduction\n\n   Rien de legal ici.\n"


def _module():
    spec = importlib.util.spec_from_file_location("pack_rfc_notice_nr", RACINE / "tools" / "forge_knowledge_pack_export.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_les_sections_legales_sont_reprises_verbatim_et_sans_les_pieds_de_page():
    s = _module().sections_legales_rfc(RECENTE)
    assert "Copyright (c) 2022 IETF Trust and the persons identified as the" in s["copyright"]
    assert "This document is subject to BCP 78" in s["copyright"], "la section continue apres le saut de page"
    assert "[Page 2]" not in s["copyright"] and "RFC 9110  " not in s["copyright"], "pied et en-tete de page retires"
    assert "Table of Contents" not in s["copyright"]
    assert "Roy T. Fielding (editor)" in s["auteurs"]


def test_une_rfc_ancienne_porte_son_full_copyright_statement():
    s = _module().sections_legales_rfc(ANCIENNE)
    assert "Copyright (C) The Internet Society (1999)" in s["copyright"]
    assert "Jon Postel" in s["auteurs"]


def test_sans_legende_la_notice_est_absente_jamais_inventee():
    m = _module()
    assert m.sections_legales_rfc(SANS_LEGENDE)["copyright"] is None
    assert m.notice_rfc(1, SANS_LEGENDE) is None
    n = m.notice_rfc(9110, RECENTE)
    assert n.startswith("RFC 9110") and "https://www.rfc-editor.org/rfc/rfc9110" in n and "IETF Trust" in n


def _vec(i):
    v = np.zeros(1024, dtype=np.float32)
    v[i] = 1.0
    return v.tobytes()


def test_le_pack_rfc_joint_la_notice_de_chaque_rfc_et_ecarte_celle_sans_legende(tmp_path):
    import sqlite3
    m = _module()
    miroir = tmp_path / "rfc_mirror"
    miroir.mkdir()
    (miroir / "rfc9110.txt").write_text(RECENTE, encoding="utf-8")
    (miroir / "rfc1.txt").write_text(SANS_LEGENDE, encoding="utf-8")
    base = tmp_path / "rag.db"
    con = sqlite3.connect(base)
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, domain TEXT, text TEXT, "
                "embedding BLOB, active INTEGER)")
    texte = "HTTP est un protocole sans etat de la couche application, decrit par cette specification. "
    con.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?)", [
        ("r1", "rfc:rfc9110", "reference", texte + "un", _vec(1), 1),
        ("r2", "rfc:rfc1", "reference", texte + "deux", _vec(2), 1),
    ])
    con.commit()
    con.close()
    composant = {"id": "knowledge-rfc", "construit": "rag_pack_source", "famille": "rfc", "licence": "IETF-TLP-5.0",
                 "conditions": "fragments verbatim attribues ; legendes et auteurs de chaque RFC joints",
                 "preuve": "https://trustee.ietf.org/license-info/"}
    st = m.exporter_source(base, composant, tmp_path / "out", "1.0.0", miroir_rfc=miroir)
    assert st["retenus"] == 1 and st["ecartes"].get("legende_rfc_absente") == 1, st
    with tarfile.open(st["out_path"]) as t:
        notice = t.extractfile("NOTICE.txt").read().decode("utf-8")
    assert "Copyright (c) 2022 IETF Trust and the persons identified as the" in notice
    assert "Roy T. Fielding (editor)" in notice and "RFC 1 " not in notice
