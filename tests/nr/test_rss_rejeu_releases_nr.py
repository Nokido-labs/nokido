"""NR 18/10 -- rejeu des releases perdues pendant le trou de la veille RSS (C_06b-4).

Contexte verifie (bb discovered_facts/c06_releases_perdues_verifie_20261018) : des releases ont ete SCELLEES
dans rss_watcher_state.json (seen) sans fragment en base ; fetch_github_release ne lit que /releases/latest
(7 j) : aucun chemin ne rattrapait un tag passe. Livraison OPENCODE_NEMOTRON (job_24ee0a6f, non commitee)
reprise et CORRIGEE : son anti-doublon passait un tag brut a MATCH (erreur FTS -> rangee « absent » ->
double ecriture) et son dry-run ecrivait le fichier d'etat.

Contrat :
- dry-run (defaut) : n'ingere rien, ne marque rien, n'ECRIT pas l'etat ;
- deja en base (par CONTENU, phrase FTS : tag ET nom) -> ignore et dit ;
- presence ILLISIBLE -> refus d'ingerer (UNKNOWN n'est pas « absent ») ;
- ingestion non prouvee -> pas de _mark_seen ; id mal forme -> refuse et dit, les autres continuent ;
- le drapeau CLI traverse le vrai point d'entree (sous-processus, id mal forme : aucun reseau, aucune ecriture).
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_rss_watcher as rw  # noqa: E402

REL = {"title": "v3.3.0", "body": "## Breaking\nchangement", "url": "https://github.com/openai/openai-python/releases/tag/v3.3.0"}


def _doubles(monkeypatch, present=False, verdict=None):
    appels = {"ingest": [], "mark": [], "save": []}
    monkeypatch.setattr(rw, "_load_state", lambda: {"seen": []})
    monkeypatch.setattr(rw, "_save_state", lambda s: appels["save"].append(1))
    monkeypatch.setattr(rw, "_mark_seen", lambda s, uid: appels["mark"].append(uid))
    monkeypatch.setattr(rw, "_deja_en_base", lambda *a, **k: present)
    monkeypatch.setattr(rw, "_release_github_par_tag", lambda repo, tag: dict(REL))
    monkeypatch.setattr(rw, "_release_pypi_version", lambda pkg, ver: {"summary": "s", "url": "https://pypi.org/project/x/1/"})

    def _ingest(**k):
        appels["ingest"].append(k)
        return verdict or (rw.INSERE, 2, "ok")

    monkeypatch.setattr(rw, "_ingest", _ingest)
    return appels


def test_dry_run_n_ingere_ne_marque_ni_n_ecrit(monkeypatch):
    a = _doubles(monkeypatch)
    res = rw.rejouer(["gh:openai/openai-python:v3.3.0", "pypi:uvicorn:0.52.4"])
    assert {v["action"] for v in res.values()} == {"A_INGERER"}
    assert a == {"ingest": [], "mark": [], "save": []}


def test_deja_en_base_ignore_et_dit(monkeypatch):
    a = _doubles(monkeypatch, present=True)
    res = rw.rejouer(["gh:openai/openai-python:v3.3.0"], dry_run=False)
    assert res["gh:openai/openai-python:v3.3.0"]["action"] == "IGNORE_DEJA_PRESENT"
    assert a["ingest"] == []


def test_presence_illisible_refuse_d_ingerer(monkeypatch):
    a = _doubles(monkeypatch, present=None)
    res = rw.rejouer(["gh:openai/openai-python:v3.3.0"], dry_run=False)
    assert res["gh:openai/openai-python:v3.3.0"]["action"] == "ILLISIBLE_REFUSE"
    assert a["ingest"] == [] and a["save"] == []


def test_ingestion_non_prouvee_ne_marque_pas(monkeypatch):
    a = _doubles(monkeypatch, verdict=(rw.REJETE, 0, "hub HTTP 403"))
    res = rw.rejouer(["gh:openai/openai-python:v3.3.0"], dry_run=False)
    assert res["gh:openai/openai-python:v3.3.0"]["action"] == "NON_INSERE"
    assert a["mark"] == [] and a["save"] == []


def test_mal_forme_refuse_les_autres_continuent_meme_format_que_la_veille(monkeypatch):
    a = _doubles(monkeypatch)
    res = rw.rejouer(["mauvais", "gh:sans-tag", "gh:openai/openai-python:v3.3.0"], dry_run=False)
    assert res["mauvais"]["action"] == res["gh:sans-tag"]["action"] == "REFUS_MAL_FORME"
    assert res["gh:openai/openai-python:v3.3.0"]["action"] == "INSERE"
    assert a["mark"] == ["gh:openai/openai-python:v3.3.0"] and a["save"] == [1]
    k = a["ingest"][0]
    assert k["domain"] == "watch_alerts" and k["source"] == REL["url"] and k["author"] == "openai/openai-python"
    assert k["text"] == "v3.3.0\n\n## Breaking\nchangement"


def test_deja_en_base_par_phrase_fts_reelle(tmp_path, monkeypatch):
    # Disposition REELLE mesuree le 18/10 (temoin positif fastapi 0.146.0) : la veille ecrit par store_chunks,
    # donc dans rag_chunks_fts ; rag_fts ne porte que d'anciens fragments. Chercher dans rag_fts rendait
    # « absent » une release ingeree le jour meme -> double ecriture.
    db = tmp_path / "e.db"
    con = sqlite3.connect(db)
    con.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)")
    con.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text)")
    con.execute("INSERT INTO rag_chunks_fts VALUES ('[watch_alerts:v3.3.0] openai/openai-python v3.3.0 (0d ago)')")
    con.execute("INSERT INTO rag_chunks_fts VALUES ('note libre sur openai-python v3.4.0 hors veille')")
    # changelog d'une release PLUS RECENTE qui CITE une autre version : ce n'est pas le fragment de celle-ci
    con.execute("INSERT INTO rag_chunks_fts VALUES ('[watch_alerts:v3.9.0] openai/openai-python v3.9.0 depuis v3.6.0')")
    # forme REELLE d'un fragment PyPI (mesuree le 18/10) : rien apres « watch_alerts: »
    con.execute("INSERT INTO rag_chunks_fts VALUES ('[watch_alerts:] PyPI uvicorn 0.52.4\n\nuvicorn 0.52.4: ASGI server')")
    # forme REELLE d'un tag a caracteres speciaux (mesuree apres le rejeu du 18/10) : en-tete = segment d'URL ENCODE
    con.execute("INSERT INTO rag_chunks_fts VALUES "
                "('[watch_alerts:langchain-core%3D%3D1.6.3] langchain-ai/langchain langchain-core==1.6.3 (rejeu)')")
    con.commit()
    con.close()
    monkeypatch.setattr(rw, "DB_PATH", db)
    assert rw._deja_en_base("v3.3.0", "openai-python") is True
    assert rw._deja_en_base("v3.4.0", "openai-python") is False, "hors watch_alerts : pas un fragment de veille"
    assert rw._deja_en_base("v3.6.0", "openai-python") is False, "cite dans le changelog d'une autre release"
    assert rw._deja_en_base("v3.9.0", "openai-python") is True
    assert rw._deja_en_base("0.52.4", "uvicorn", genre="pypi") is True, "en-tete PyPI sans version apres le ':'"
    assert rw._deja_en_base("0.53.0", "uvicorn", genre="pypi") is False
    assert rw._deja_en_base("langchain-core==1.6.3", "langchain") is True, "en-tete encode %3D%3D reconnu"
    assert rw._deja_en_base("langchain-core==1.6.9", "langchain") is False  # caracteres speciaux : pas d'erreur
    monkeypatch.setattr(rw, "DB_PATH", tmp_path / "absente.db")
    assert rw._deja_en_base("v3.3.0", "openai-python") is None, "base illisible = INCONNU, jamais absent"


def test_drapeau_cli_traverse_le_point_d_entree():
    r = subprocess.run([sys.executable, str(ROOT / "app" / "forge_rss_watcher.py"), "--rejouer", "mauvais-id"],
                       capture_output=True, text=True, errors="replace", timeout=60, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr[-800:]
    sortie = json.loads(r.stdout[r.stdout.index("{"):])
    assert sortie["mauvais-id"]["action"] == "REFUS_MAL_FORME"
