# -*- coding: utf-8 -*-
"""NR - P0 : `agent_messages` hors de RAG/embeddings.db (2026-09-06).

Decision owner du 2026-09-05 (« il faut que les db soient scindees ») apres 16
morts du hub : `handle_notify` ecrivait la table EN SYNCHRONE dans le loop, dans
la base de 24,9 Go, busy_timeout 15 s. Contrats verrouilles ici, sans reseau ni
base reelle :
  1. `open_writer(path=...)` ouvre VRAIMENT ce chemin (un parametre ignore en
     silence = le piege `args=` du 31/08) ;
  2. `open_m2m()` cree table + index dans une base neuve ;
  3. `forge_m2m_db_split.copier/verifier` : copie fidele, ecart NOMME ;
  4. aucun fichier VIVANT du protocole M2M n'ouvre encore la table sur la grosse
     base (audit AST) — les fichiers non encore redirig es sont une dette datee,
     enumeree ci-dessous, pas un silence.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.150)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

dbp = pytest.importorskip("forge_db_path")

# PASSE 1 (2026-09-06, socle) : point d'acces, migration, audit, archive du hub
# hors du loop — mais AUCUN chemin bascule : le registry porte 13 autres SQL sur la
# table (archive d'args, whoami, eventbus, handle_inbox) et un seul site bascule =
# un hub qui ecrit d'un cote et lit de l'autre. PASSE 2 : tous ensemble (copie
# delta puis restart) — cet ensemble se remplit alors, et la dette se vide.
# PASSE 2 (2026-09-06) : les sites migrent vers m2m_path()/open_m2m() SOUS l'interrupteur
# (aucun changement de comportement tant que sandbox/m2m.switch n'existe pas). Un
# fichier passe de la dette aux VIVANTS des que l'audit le lit REDIRIGE, ou MIXTE
# parce qu'il ouvre encore la base du RAG pour D'AUTRES tables (nomme ci-dessous).
# MIXTE legitime : la table est redirigee, mais le fichier ouvre encore la base du RAG
# pour D'AUTRES tables (biblio_raw, opsec_state, rag_chunks, event_log, coagulation_events,
# goap_plans, routing_telemetry, watch_jobs, tasks...) ou n'en garde que le litteral.
# L'audit ne lit que des noms de fichiers : chacun de ceux-la a ete LU site par site.
MIXTES_LEGITIMES_2026_09_06 = {
    "app/forge_autonomous_loops.py", "app/forge_coagulation_cascade.py", "app/forge_goap.py",
    "app/forge_graph_explorer.py", "app/forge_health_diagnostic.py", "app/forge_mcp_registry.py",
    "app/forge_message_frame.py", "app/forge_network_dispatch.py", "app/forge_proprioception.py",
    "app/forge_sandbox_guard.py", "app/Nokido.py", "tools/claude_inbox_tick.py",
    "tools/claude_precompact.py", "tools/claude_session_start.py", "tools/cli_capture_lib.py",
    "tools/forge_boot_context.py", "tools/forge_bulk_import.py", "tools/forge_collab_broker.py",
    "tools/forge_log_retention.py", "tools/forge_m2m_debate_antiregression.py",
    "tools/forge_rescue.py", "tools/hub_lifecycle_hooks.py", "tools/nokido_hub.py",
    "tools/nokido_tui.py", "tools/rag_status_report.py",
}
VIVANTS_REDIRIGES: set[str] = MIXTES_LEGITIMES_2026_09_06 | {
    "tools/agent_notify.py", "tools/check_agent_msg.py", "tools/check_gemini_inbox.py",
    "tools/dispatch_migration_tasks.py", "tools/forge_benchmark_runner.py",
    "tools/forge_gemini_autonomous_agent.py", "tools/forge_job_notify.py",
    "tools/gemini_cli_daemon.py", "tools/gemini_notify.py", "tools/gemini_poll_daemon.py",
    "tools/multi_llm_daemon.py", "tools/read_claude_inbox.py", "tools/read_gemini_messages.py",
    "tools/send_agent_task.py",
}
# PASSE 2 livree le 2026-09-06 : plus aucune dette. Un fichier A_REDIRIGER est desormais
# une REGRESSION (nouveau site sur la grosse base), pas une dette a dater.
DETTE_CONNUE_2026_09_06: set[str] = set()


def test_l_interrupteur_decide_du_chemin_a_chaque_appel(tmp_path, monkeypatch):
    """PASSE 2 : « tous ensemble ou aucun » tient au niveau de l'INTERRUPTEUR.

    Les sites migrent vers m2m_path()/open_m2m() un par un ; tant que
    sandbox/m2m.switch n'existe pas, tous rendent la base du RAG (aucun changement
    de comportement) ; des qu'il existe, tous rendent la base M2M -- scripts, hooks,
    hub et daemons (apres leur redemarrage) ensemble. L'env prime (tests, migrations).
    """
    monkeypatch.delenv("LAFORGE_M2M_DB_PATH", raising=False)
    monkeypatch.setattr(dbp, "_M2M_SWITCH", tmp_path / "m2m.switch")
    monkeypatch.setattr(dbp, "_M2M_DEFAULT", tmp_path / "m2m.db")
    monkeypatch.setattr(dbp, "db_path", lambda: str(tmp_path / "rag.db"))
    assert dbp.m2m_path() == str(tmp_path / "rag.db") and not dbp.m2m_switch_actif()
    (tmp_path / "m2m.switch").write_text("", encoding="utf-8")
    assert dbp.m2m_path() == str(tmp_path / "m2m.db") and dbp.m2m_switch_actif()
    monkeypatch.setenv("LAFORGE_M2M_DB_PATH", str(tmp_path / "env.db"))
    assert dbp.m2m_path() == str(tmp_path / "env.db")


def test_open_m2m_ne_touche_pas_le_schema_de_la_base_du_rag(tmp_path, monkeypatch):
    """Avant la bascule, open_m2m() ouvre la base du RAG (gelee) : la table y existe
    deja, aucune ecriture de schema (index compris) ne doit y etre faite."""
    monkeypatch.delenv("LAFORGE_M2M_DB_PATH", raising=False)
    monkeypatch.setattr(dbp, "_M2M_SWITCH", tmp_path / "absent.switch")
    rag = tmp_path / "rag.db"
    c0 = sqlite3.connect(str(rag)); c0.execute("CREATE TABLE agent_messages(id TEXT PRIMARY KEY)"); c0.commit(); c0.close()
    monkeypatch.setattr(dbp, "db_path", lambda: str(rag))
    c = dbp.open_m2m(timeout=2.0)
    try:
        noms = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE tbl_name='agent_messages'")
                if not r[0].startswith("sqlite_autoindex")}   # l'index de la PK est a SQLite, pas a nous
    finally:
        c.close()
    assert noms == {"agent_messages"}, f"schema M2M ecrit dans la base du RAG : {noms}"


def test_le_copieur_refuse_une_cible_egale_a_la_source(tmp_path):
    split = pytest.importorskip("forge_m2m_db_split")
    src = tmp_path / "src.db"
    _source_fabriquee(src)
    r = split.copier(str(src), True, source=str(src))
    assert "erreur" in r and r["inseres"] == 0, "copier une base sur elle-meme doit etre REFUSE, pas lu comme deja fait"


def test_open_writer_honore_le_chemin(tmp_path):
    cible = tmp_path / "x.db"
    c = dbp.open_writer(timeout=2.0, path=str(cible))
    try:
        c.execute("CREATE TABLE t(a)")
    finally:
        c.close()
    assert cible.exists(), "open_writer(path=...) a ecrit ailleurs que sur le chemin demande"


def test_open_m2m_cree_le_schema_dans_une_base_neuve(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_M2M_DB_PATH", str(tmp_path / "m2m.db"))
    c = dbp.open_m2m(timeout=2.0)
    try:
        noms = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE tbl_name='agent_messages'")}
    finally:
        c.close()
    assert "agent_messages" in noms
    assert "idx_agent_messages_to" in noms and "idx_agent_messages_created_at" in noms


def _source_fabriquee(p: Path, n: int = 3) -> None:
    c = sqlite3.connect(str(p))
    for sql in dbp.M2M_SCHEMA:
        c.execute(sql)
    for i in range(n):
        c.execute("INSERT INTO agent_messages(id,from_agent,to_agent,method,payload,status,created_at)"
                  " VALUES(?,?,?,?,?,?,?)", (f"frm_{i}", "A", "B", "m", "{}", "unread", f"2026-09-06 00:00:0{i}"))
    c.commit()
    c.close()


def test_split_copie_puis_verifie_puis_nomme_un_ecart(tmp_path):
    split = pytest.importorskip("forge_m2m_db_split")
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _source_fabriquee(src)
    dry = split.copier(str(dst), False, source=str(src))
    assert dry["dry_run"] and not dst.exists(), "un dry-run ne cree rien"
    r = split.copier(str(dst), True, source=str(src))
    assert r["inseres"] == 3 and r["deja"] == 0
    assert split.copier(str(dst), True, source=str(src))["deja"] == 3, "idempotent (INSERT OR IGNORE)"
    v = split.verifier(str(dst), source=str(src))
    assert v["verdict"] == "OK" and v["manquants_dans_cible"] == 0, v
    c = sqlite3.connect(str(dst)); c.execute("UPDATE agent_messages SET status='read' WHERE id='frm_1'"); c.commit(); c.close()
    v2 = split.verifier(str(dst), source=str(src))
    assert v2["verdict"] == "ECART" and v2["differents_dans_echantillon"] == 1, "une ligne differente est NOMMEE"
    assert split.verifier(str(tmp_path / "absente.db"), source=str(src))["verdict"] == "CIBLE ABSENTE"


def test_aucun_fichier_vivant_n_ouvre_la_table_sur_la_grosse_base():
    audit = pytest.importorskip("forge_m2m_audit")
    a = audit.auditer()
    a_rediriger = set(a["par_etat"].get("A_REDIRIGER", []))
    fuites = sorted(a_rediriger & VIVANTS_REDIRIGES)
    assert not fuites, f"fichiers VIVANTS qui ouvrent encore agent_messages sur embeddings.db : {fuites}"
    inconnus = sorted(a_rediriger - VIVANTS_REDIRIGES - DETTE_CONNUE_2026_09_06)
    assert not inconnus, (
        f"nouveaux fichiers A_REDIRIGER hors de la dette connue : {inconnus} — "
        "les rediriger (forge_db_path.open_m2m) ou les ajouter a la dette AVEC une date"
    )
    # Un VIVANT lu MIXTE doit etre un mixte LU et nomme : sinon c'est une migration
    # a moitie faite (la table encore sur la grosse base dans une branche).
    mixtes = set(a["par_etat"].get("MIXTE", []))
    douteux = sorted((mixtes & VIVANTS_REDIRIGES) - MIXTES_LEGITIMES_2026_09_06)
    assert not douteux, f"vivants lus MIXTE sans lecture qui le justifie : {douteux}"
    redir = set(a["par_etat"].get("REDIRIGE", []))
    perdus = sorted(VIVANTS_REDIRIGES - redir - mixtes)
    assert not perdus, f"vivants declares rediriges que l'audit ne lit plus REDIRIGE/MIXTE : {perdus}"
