# -*- coding: utf-8 -*-
"""NR 2026-09-23 — l'ingestion d'un dump se fait EN FLUX, a l'identique.

Mesure : `read_text` du dump entier + `list(blocs)` sur des dumps de 950 Mo a fait
tuer l'ingestion de veille a 7 138 Mo de RSS. `_blocs_fichiers_flux` lit ligne a
ligne ; ce NR prouve qu'il rend EXACTEMENT les memes blocs que `_blocs_fichiers`,
et que `ingest_file` ne charge plus le dump entier.
"""
import sqlite3
from pathlib import Path

import pytest

from nokido_agent.tools import forge_gitingest_sdk_ingest as gi

SEP = gi.SEPARATOR
EQ = "=" * 30

CAS = {
    "format_a_preambule_fin_sans_saut": (
        "preambule ignore\n" + EQ + "\nFILE: a/b.py\n" + EQ + "\ncode1\n\n"
        + "=" * 25 + "\nFILE: c.md\n" + "=" * 25 + "\ntexte\nfin"),
    "format_a_en_tete": EQ + "\nFILE: x.py\n" + EQ + "\nprint(1)\n",
    "format_b_veille": (
        "x/_PROVENANCE\nrepo: u\n\n" + SEP + "\nx/a.py\nprint(1)\n\n" + SEP
        + "\nx/b.md\nligne avec " + SEP + " collee\nsuite\n\n" + SEP + "\n\n"
        + SEP + "\nx/c.txt\nfin"),
    "format_b_ligne_de_100_egal": "x/d.py\n" + "=" * 100 + "\ncorps\n",
    "format_b_crlf": "x/e.py\r\nprint(2)\r\n\r\n" + SEP + "\r\nx/f.py\r\nfin\r\n",
    "vide": "",
}


@pytest.mark.parametrize("nom", sorted(CAS))
def test_flux_rend_les_memes_blocs_que_l_ancien(tmp_path, nom):
    p = tmp_path / ("gitingest_veille_%s.txt" % nom)
    p.write_bytes(CAS[nom].encode("utf-8"))
    attendu = list(gi._blocs_fichiers(p.read_text(encoding="utf-8", errors="replace"), p))
    assert list(gi._blocs_fichiers_flux(p)) == attendu


def test_ingest_file_ne_charge_plus_le_dump_entier(tmp_path, monkeypatch):
    p = tmp_path / "gitingest_veille_z.txt"
    p.write_text(CAS["format_b_veille"], encoding="utf-8")

    def _interdit(*_a, **_k):
        raise AssertionError("read_text du dump entier : c'est ce qui a tue le job a 7 Go")
    monkeypatch.setattr(Path, "read_text", _interdit)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, text TEXT, "
                 "domain TEXT, created_at INTEGER)")
    conn.execute("CREATE TABLE rag_fts (chunk_id, text, source, domain)")
    ins, skip = gi.ingest_file(p, conn)
    assert ins > 0 and skip == 0
    assert gi.ingest_file(p, conn) == (0, ins)      # rejeu : que des skip
