"""Non-regression : la disponibilite par canal, et l'interdiction d'inventer une absence.

Demande owner 2026-09-01. Un chunk n'est pas `available: true/false` : il l'est PAR
CANAL, et l'absence d'un signal a plusieurs causes qu'un booleen confond. Le routeur doit
distinguer « pas pertinent » de « pas encore vectorise » de « ne le sera JAMAIS ».

Mesure qui fonde ce besoin : sur 772 264 chunks sans embedding, 626 646 (81,1 %) sont
refuses par `forge_tier_guard` et n'auront jamais de vecteur. Les lire comme PENDING
surestimait la dette d'un facteur cinq et ferait attendre le routeur pour rien.

Les tests portent sur l'EFFET :
  1. lexical disponible + vecteur PENDING ;
  2. lexical disponible + vecteur REFUSED_BY_POLICY ;
  3. les deux disponibles ;
  4. absence reelle d'information -> UNKNOWN, jamais une absence fabriquee ;
  5. GARDE D'EQUIVALENCE : le vrai trigger `forge_tier_guard` est cree dans la base
     jetable, et on verifie que « l'UPDATE d'embedding passe » <=> « tier() dit
     vectorisable ». Recopier un CASE sans cette garde ferait une SECONDE VERITE ;
  6. `annoter` ne touche NI aux scores NI a l'ordre -- cette couche rend le retrieval
     observable, elle ne le modifie pas.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "app",):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_db_path  # noqa: E402
import forge_memory_availability as dispo  # noqa: E402

# DDL RELEVE le 2026-09-01 dans sqlite_master de RAG/embeddings.db. C'est LUI l'autorite :
# la fonction `tier()` n'en est qu'un miroir, et le test ci-dessous les confronte.
DDL_TIER_GUARD = """
CREATE TRIGGER forge_tier_guard
BEFORE UPDATE OF embedding ON rag_chunks
FOR EACH ROW
WHEN NEW.embedding IS NOT NULL
 AND (CASE WHEN NEW.source LIKE 'gitingest%' THEN 'external-lib'
   WHEN NEW.source LIKE '%.pdf' OR NEW.domain IN ('nagios_core','vitis_ai') THEN 'external-doc'
   WHEN NEW.domain IN ('gitingest','gitingest_litellm','sdk_gitingest','laforge_digest') THEN 'cold-legacy'
   WHEN NEW.domain = 'code' THEN 'external-pr'
   WHEN NEW.domain = 'mcp_result' THEN 'tool-output'
   WHEN NEW.domain = 'longmemeval' THEN 'eval-data'
   WHEN NEW.domain = 'conv' OR NEW.source LIKE 'conv%' THEN 'conversation'
   WHEN NEW.source LIKE 'session:%' OR NEW.source LIKE 'anchor%'
        OR NEW.domain IN ('autonomous','episodic_memory','longterm_memory','rag') THEN 'laforge-memory'
   WHEN NEW.source LIKE 'http%' THEN 'web-crawl'
   WHEN NEW.source LIKE 'app/%' OR NEW.source LIKE 'tools/%' OR NEW.source LIKE 'ctf/%'
        OR NEW.source LIKE 'proxy_deno/%' THEN 'laforge-code'
   ELSE 'laforge' END) NOT IN ('laforge', 'laforge-code', 'laforge-memory', 'web-crawl')
BEGIN
  SELECT RAISE(IGNORE);
END
"""

# (source, domain) couvrant CHAQUE branche du CASE, dans les deux sens.
ECHANTILLON = [
    ("gitingest/x.py", "autre"), ("doc/manuel.pdf", "autre"), ("s", "nagios_core"),
    ("s", "vitis_ai"), ("s", "sdk_gitingest"), ("s", "laforge_digest"), ("s", "code"),
    ("s", "mcp_result"), ("s", "longmemeval"), ("s", "conv"), ("conv/abc", "autre"),
    ("session:auto_x", "autre"), ("anchor:x", "autre"), ("s", "episodic_memory"),
    ("s", "longterm_memory"), ("s", "autonomous"), ("s", "rag"),
    ("https://ex.org/p", "autre"), ("app/forge_x.py", "autre"), ("tools/x.py", "autre"),
    ("ctf/x.py", "autre"), ("proxy_deno/x.ts", "autre"), ("quelconque.txt", "veille_code"),
]


@pytest.fixture()
def base(tmp_path, monkeypatch):
    chemin = tmp_path / "embeddings.db"
    conn = sqlite3.connect(chemin)
    conn.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, "
                 "source TEXT, domain TEXT, embedding BLOB)")
    conn.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, source, domain, "
                 "content='rag_chunks', content_rowid='rowid')")
    conn.executescript(DDL_TIER_GUARD)
    conn.commit()
    conn.close()
    monkeypatch.setattr(forge_db_path, "db_path", lambda: str(chemin))
    return chemin


def _ins(chemin, cid, source, domain, avec_vecteur=False):
    conn = sqlite3.connect(chemin, isolation_level=None)
    try:
        conn.execute("INSERT INTO rag_chunks(id, text, source, domain, embedding) "
                     "VALUES (?,?,?,?,?)",
                     (cid, "texte " + cid, source, domain,
                      b"\x01" * 8 if avec_vecteur else None))
    finally:
        conn.close()


def test_lexical_disponible_et_vecteur_en_attente(base):
    _ins(base, "c1", "quelconque.txt", "veille_code")  # palier 'laforge' => vectorisable
    docs = dispo.annoter([{"id": "c1", "score": 0.9}], lexical_contrib={"c1"})
    assert docs[0]["availability"]["lexical"] == dispo.AVAILABLE
    assert docs[0]["availability"]["vector"] == dispo.PENDING
    assert docs[0]["availability"]["tier"] == "laforge"


def test_lexical_disponible_et_vecteur_refuse_par_politique(base):
    _ins(base, "c2", "conv/abc", "conv")
    docs = dispo.annoter([{"id": "c2", "score": 0.5}], lexical_contrib={"c2"})
    assert docs[0]["availability"]["vector"] == dispo.REFUSED_BY_POLICY, \
        "un palier refuse lu comme PENDING ferait attendre un vecteur interdit"
    assert docs[0]["availability"]["tier"] == "conversation"


def test_les_deux_canaux_disponibles(base):
    _ins(base, "c3", "app/forge_x.py", "nokido_code", avec_vecteur=True)
    docs = dispo.annoter([{"id": "c3", "score": 0.7}], lexical_contrib={"c3"})
    assert docs[0]["availability"]["lexical"] == dispo.AVAILABLE
    assert docs[0]["availability"]["vector"] == dispo.AVAILABLE


def test_absence_reelle_rend_unknown_et_non_une_absence(base):
    """Un id introuvable, et un chunk qui n'a pas matche : UNKNOWN dans les deux cas."""
    _ins(base, "c4", "quelconque.txt", "veille_code", avec_vecteur=True)
    docs = dispo.annoter([{"id": "inexistant", "score": 0.1},
                          {"id": "c4", "score": 0.2}], lexical_contrib=set())
    assert docs[0]["availability"]["vector"] == dispo.UNKNOWN
    assert docs[0]["availability"]["tier"] is None
    # c4 existe et porte un vecteur : ne pas avoir contribue au lexical ne doit PAS
    # se lire comme « absent de l'index ».
    assert docs[1]["availability"]["lexical"] == dispo.UNKNOWN
    assert docs[1]["availability"]["vector"] == dispo.AVAILABLE
    # Et une base injoignable rend UNKNOWN, jamais PENDING.
    assert dispo.statut_vectoriel(None, "app/x.py", "d") == dispo.UNKNOWN


def test_tier_est_equivalent_au_trigger_reel(base):
    """GARDE D'EQUIVALENCE : l'autorite est le trigger, `tier()` n'est qu'un miroir."""
    conn = sqlite3.connect(base, isolation_level=None)
    try:
        for i, (src, dom) in enumerate(ECHANTILLON):
            cid = f"t{i}"
            conn.execute("INSERT INTO rag_chunks(id, text, source, domain) "
                         "VALUES (?,?,?,?)", (cid, "t", src, dom))
            conn.execute("UPDATE rag_chunks SET embedding = ? WHERE id = ?",
                         (b"\x02" * 8, cid))
            passe = conn.execute("SELECT embedding IS NOT NULL FROM rag_chunks "
                                 "WHERE id = ?", (cid,)).fetchone()[0]
            attendu = dispo.tier(src, dom) in dispo.VECTORISABLES
            assert bool(passe) == attendu, (
                f"divergence sur ({src!r}, {dom!r}) : trigger={bool(passe)} "
                f"tier()={dispo.tier(src, dom)!r}")
    finally:
        conn.close()


def test_annoter_ne_touche_ni_aux_scores_ni_a_l_ordre(base):
    _ins(base, "a", "app/x.py", "d", avec_vecteur=True)
    _ins(base, "b", "conv/y", "conv")
    entree = [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.4}]
    avant = [(d["id"], d["score"]) for d in entree]

    sortie = dispo.annoter(entree, lexical_contrib={"b"})

    assert [(d["id"], d["score"]) for d in sortie] == avant, \
        "cette couche rend le retrieval observable, elle ne le modifie pas"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
