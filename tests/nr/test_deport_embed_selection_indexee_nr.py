"""NR -- la selection de NokidoDeportEmbed passe par l'index partiel, jamais par un balayage de la table (2026-10-20).

Cause racine de l'oscillation du regulateur (enquete AGY du 20/10 : saturation DISQUE, NokidoDeportEmbed ~68 Mo/s) :
tools/forge_reindex_deport.py selectionne ses pages par `WHERE <CASE tier inline> AND (embedding IS NULL OR
length(embedding)=0)`. Plan MESURE sur la base reelle : `SCAN rag_chunks` -- la table de 46 Go relue a CHAQUE page de
2000 fragments. Sans le OR : `SCAN rag_chunks USING INDEX idx_emb_null_origin`. Le correctif existait deja dans le
corps : forge_tier_policy.hot_tier_clause(conn) rend la forme indexable `origin IN (...)` et l'index partiel
idx_emb_null_origin a ete pose le 25/07 pour CE cas (selection 1,07 s -> 0,00 s, forge_embed_auto_trigger s'en sert).
Physiologiquement : un hypermetabolisme (un organe qui relit tout le genome pour chaque proteine), pas d'abord un
defaut de regulation.

Ce qui est garde : `predicat_a_vectoriser(conn)` emprunte hot_tier_clause et `embedding IS NULL` seul ; son plan de
requete utilise idx_emb_null_origin ; il ne contient plus `length(embedding)`.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("reindex_deport_selection_nr", RACINE / "tools" / "forge_reindex_deport.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def base(tmp_path):
    con = sqlite3.connect(tmp_path / "rag.db")
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, domain TEXT, text TEXT, "
                "embedding BLOB, origin TEXT, active INTEGER DEFAULT 1)")
    con.execute("CREATE INDEX idx_emb_null_origin ON rag_chunks(origin) WHERE embedding IS NULL")
    con.executemany("INSERT INTO rag_chunks (id, source, domain, text, embedding, origin) VALUES (?,?,?,?,?,?)",
                    [("c%d" % i, "app/x%d.py" % i, "code_nokido", "texte %d" % i, None if i % 2 else b"v", "laforge-code")
                     for i in range(200)])
    con.commit()
    yield con
    con.close()


def test_le_predicat_emprunte_la_forme_indexable_et_l_index_partiel(base):
    m = _module()
    pred = m.predicat_a_vectoriser(base)
    assert "length(embedding)" not in pred
    assert "embedding IS NULL" in pred
    plan = " | ".join(str(r[-1]) for r in base.execute(
        "EXPLAIN QUERY PLAN SELECT id, text FROM rag_chunks WHERE %s LIMIT 2000" % pred).fetchall())
    assert "idx_emb_null_origin" in plan, plan


class _Fre:
    """Faux forge_rebuild_embeddings : aucun reseau, aucune base."""
    HF_TOKEN = DEEPINFRA = NVIDIA = CF_ACCOUNT = CF_KEY = ""
    PROVIDERS: list = []

    @staticmethod
    def _f(texts):
        return [[0.0] * 1024 for _ in texts]
    hf_embed = deepinfra_embed = nvidia_embed = cloudflare_embed = _f


def _noms(m, monkeypatch, valide):
    import nokido_agent.app.forge_secrets as fs
    monkeypatch.setattr(fs, "get_secret", lambda k, *a, **kw: "")
    for k in ("HF_TOKEN", "DEEPINFRA", "NVIDIA_NIM_API_KEY", "NVIDIA_API_KEY",
              "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_AI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    if valide:
        monkeypatch.setenv("LAFORGE_EMBED_MODAL_VALIDE", "1")
    else:
        monkeypatch.delenv("LAFORGE_EMBED_MODAL_VALIDE", raising=False)
    fre = _Fre()
    fre.PROVIDERS = []
    return m._apply_vault_keys_to_fre(fre), fre


def test_modal_reste_derriere_la_verification_des_vecteurs(monkeypatch):
    m = _module()
    noms, fre = _noms(m, monkeypatch, valide=False)
    assert "Modal" not in noms
    noms, fre = _noms(m, monkeypatch, valide=True)
    assert "Modal" in noms
    modal = [p for p in fre.PROVIDERS if p["name"] == "Modal"][0]
    # le demarrage a froid (~66 s) ne doit pas faire ecarter Modal a l'election
    assert modal["duree_max"] >= 120


def test_election_modal_froid_puis_cloudflare_429_sans_boucle(monkeypatch):
    m = _module()
    appels = []

    def modal(t):
        appels.append("modal")
        return [[0.0] * 1024 for _ in t]

    def cf(t):
        appels.append("cf")
        raise RuntimeError("HTTP 429 sur https://exemple :: quota")

    # Modal repond en 66 s (simule) : retenu, car sa tolerance depasse 66 s
    horloge = iter([0.0, 66.0])
    cands = [{"name": "Modal", "fn": modal, "duree_max": 150}, {"name": "Cloudflare", "fn": cf}]
    assert m._elire_provider(cands, 20, now=lambda: next(horloge))["name"] == "Modal"
    # Modal HS : Cloudflare 429 -> ecarte UNE fois, puis le local en dernier recours
    appels.clear()

    def modal_hs(t):
        raise RuntimeError("modal indisponible")

    local = {"name": "local", "fn": lambda t: [[0.0] * 1024 for _ in t]}
    cands = [{"name": "Modal", "fn": modal_hs, "duree_max": 150},
             {"name": "Cloudflare", "fn": cf}, local]
    assert m._elire_provider(cands, 20)["name"] == "local"
    assert appels == ["cf"]  # un seul appel Cloudflare : pas de boucle sur le 429


def test_un_provider_lent_sans_tolerance_reste_ecarte():
    m = _module()
    horloge = iter([0.0, 40.0])
    cands = [{"name": "X", "fn": lambda t: t}]
    assert m._elire_provider(cands, 20, now=lambda: next(horloge)) is None


def test_le_predicat_selectionne_les_fragments_sans_vecteur(base):
    m = _module()
    n = base.execute("SELECT count(*) FROM rag_chunks WHERE %s" % m.predicat_a_vectoriser(base)).fetchone()[0]
    assert n == 100
