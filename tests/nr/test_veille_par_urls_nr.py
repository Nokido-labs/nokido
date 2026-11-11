# -*- coding: utf-8 -*-
"""NR (owner 2/11) : une veille sur des URL CONNUES passe par le workflow officiel (crawl4ai + ingestion + stockage).

Owner : « les veilles DOIVENT passer par Docker crawl4ai et searxng et tous les workflows d'ingestion deja mis en
place ». create_job ne prenait qu'un THEME : une liste d'URL precises (DOI, arXiv) ne pouvait qu'etre recherchee de
nouveau, ou ingeree par un script maison (fait le 2/11, a tort). create_job(theme, urls=[...]) seme les URL dans le
contexte de chaine (cle « refined », celle que lit l'etape crawl) et ne cree que crawl -> ingest -> store. Seules
des URL http(s) sont admises (le crawler ne doit jamais lire un fichier local). Aucune ecriture en base reelle."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_watch_agent as wa  # noqa: E402


class _Conn:
    def __init__(self):
        self.q = []

    def execute(self, sql, params=()):
        self.q.append((" ".join(sql.split()), params))
        return self


def _capturer(monkeypatch):
    import nokido_agent.app.forge_db_path as dbp
    conn = _Conn()
    monkeypatch.setattr(dbp, "write_retry", lambda tx: tx(conn))
    monkeypatch.setattr(wa, "_reveiller_consommateur", lambda: "SAUTE")
    return conn


def _noeuds(conn):
    return [p[3] for s, p in conn.q if s.startswith("INSERT INTO agent_chain_nodes")]


def test_veille_par_urls_seme_le_contexte_et_saute_la_recherche(monkeypatch):
    conn = _capturer(monkeypatch)
    urls = ["https://arxiv.org/abs/2601.21842", "https://dl.acm.org/doi/10.1145/192724.192731"]
    assert wa.create_job(theme="biblio methodes", urls=urls, agent="TEST").startswith("wj_")
    assert _noeuds(conn) == ["crawl", "ingest", "store"]
    ctx = next(json.loads(p[1]) for s, p in conn.q if s.startswith("INSERT INTO agent_chain_context"))
    assert [r["url"] for r in ctx["refined"]] == urls and ctx["theme"] == "biblio methodes"
    job = next(p for s, p in conn.q if s.startswith("INSERT INTO watch_jobs"))
    assert job[3] == "crawl", "l'etape initiale du job est le crawl"


def test_les_urls_designees_passent_le_seuil_de_pertinence_de_l_ingestion(monkeypatch):
    """2/11 : wj_01e3dd09dc -- crawl4ai attendu (68 s) et 7 URL crawlees, mais 0 ingeree : la chaine courte saute
    `refine`, qui note la pertinence ; l'ingestion ecarte tout `relevance` < _MIN_RELEVANCE_INGEST (0 par defaut).
    Une URL designee par l'owner est pertinente par definition."""
    conn = _capturer(monkeypatch)
    wa.create_job(theme="t", urls=["https://arxiv.org/abs/2601.21842"], agent="TEST")
    ctx = next(json.loads(p[1]) for s, p in conn.q if s.startswith("INSERT INTO agent_chain_context"))
    assert all(r["relevance"] >= wa._MIN_RELEVANCE_INGEST for r in ctx["refined"])


def test_sans_urls_la_chaine_reste_en_sept_etapes(monkeypatch):
    conn = _capturer(monkeypatch)
    wa.create_job(theme="t", agent="TEST")
    assert _noeuds(conn) == ["keywords", "verify_kw", "search", "refine", "crawl", "ingest", "store"]


@pytest.mark.parametrize("mauvaise", ["file:///C:/Windows/win.ini", "C:/secret.txt", "ftp://x.org/a", ""])
def test_seules_les_urls_http_sont_admises(monkeypatch, mauvaise):
    conn = _capturer(monkeypatch)
    with pytest.raises(ValueError):
        wa.create_job(theme="t", urls=["https://ok.org", mauvaise], agent="TEST")
    assert conn.q == [], "rien n'est ecrit quand une URL est refusee"
