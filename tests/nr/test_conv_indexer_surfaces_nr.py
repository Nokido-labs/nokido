# -*- coding: utf-8 -*-
"""NR — Couverture des surfaces cognitives par forge_conv_indexer et visibilité des pannes warmup_rag.

Chantier clôture des roadmaps — Lot L1 (docs/CHANTIER_CLOTURE_ROADMAPS.md#L1). Tests 1-4 : AGY (6b1de7e50).
Prouve :
  1. Gemini CLI lit les sessions JSONL (chats/session-*.jsonl) en plus de .json.
  2. Codex CLI est indexé depuis ~/.codex/sessions/**/*.jsonl avec préfixe conv_codex.
  3. couverture() inclut codex et gemini jsonl.
  4. L'échec de conv_indexer dans warmup_rag émet un WARNING avec la cause (plus de DEBUG silencieux).
Ajouts à l'intégration (Claude, 2026-10-13), sur la forme RÉELLE mesurée sur le poste :
  5. Codex enveloppe chaque tour dans `payload` : la forme plate du test 2 n'existe pas sur le poste
     (0 morceau sur 26 sessions) ; `event_msg` doublonne les tours ; `developer` n'est pas un tour.
  6. Deux sessions du même mois ont des identifiants distincts (`stem[:16]` les confondait).
  7. Un tour plus long que CHUNK_MAX est découpé en suites, pas tronqué.
  8. index_all indexe TOUS les projets Gemini, pas le seul `laforge`.
Étanchéité absolue : dossiers temporaires (tmp_path), aucune lecture du vrai profil utilisateur.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def env_isole(tmp_path, monkeypatch):
    """Bac à sable hermétique pour conv_indexer — aucune lecture du vrai profil."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LAFORGE_OWNER_HOME", str(fake_home))

    db_path = tmp_path / "embeddings.db"
    con = sqlite3.connect(str(db_path))
    con.execute("CREATE TABLE IF NOT EXISTS rag_chunks (id TEXT PRIMARY KEY, source TEXT, text TEXT, "
                "domain TEXT, ingested_at TEXT, created_at INTEGER)")
    con.execute("CREATE TABLE IF NOT EXISTS rag_fts (chunk_id TEXT, source TEXT, text TEXT)")
    con.commit()
    con.close()

    import forge_conv_indexer as ci
    monkeypatch.setattr(ci, "OWNER_HOME", fake_home)
    monkeypatch.setattr(ci, "CLAUDE_HISTORY", fake_home / ".claude" / "projects")
    monkeypatch.setattr(ci, "GEMINI_HISTORY", fake_home / ".gemini" / "tmp")
    monkeypatch.setattr(ci, "AGY_HISTORY", fake_home / ".gemini" / "antigravity-cli" / "brain")
    monkeypatch.setattr(ci, "CODEX_HISTORY", fake_home / ".codex")
    monkeypatch.setattr(ci, "RAG_DB", db_path)
    return {"home": fake_home, "db": db_path, "ci": ci}


def test_gemini_cli_lit_session_jsonl_et_json(env_isole):
    ci = env_isole["ci"]
    chats_dir = env_isole["home"] / ".gemini" / "tmp" / "laforge" / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    (chats_dir / "session-01.json").write_text(json.dumps({"sessionId": "session-legacy-01", "messages": [
        {"type": "user", "content": "Question format JSON classique dans Gemini"},
        {"type": "gemini", "content": "Reponse format JSON classique dans Gemini"}]}), encoding="utf-8")
    f_jsonl = chats_dir / "session-02.jsonl"
    f_jsonl.write_text("\n".join(json.dumps(l) for l in (
        {"type": "user", "content": "Premier message utilisateur dans Gemini JSONL", "timestamp": "2026-10-13T10:00:00Z"},
        {"type": "gemini", "content": "Reponse du modele Gemini dans le fichier JSONL", "timestamp": "2026-10-13T10:00:30Z"},
    )), encoding="utf-8")

    morceaux_jsonl = list(ci.iter_gemini_chunks(f_jsonl))
    assert len(morceaux_jsonl) >= 1, "iter_gemini_chunks doit savoir lire un fichier .jsonl"
    src, txt, *extra = morceaux_jsonl[0]
    assert src.startswith("conv_gemini/"), f"source inattendue: {src}"
    assert "Gemini JSONL" in txt

    res = ci.index_gemini_sessions(project_name="laforge", limit_sessions=0)
    assert res.get("ok") is True, f"index_gemini_sessions a échoué: {res}"
    assert res.get("sessions") == 2, f"Attendu 2 sessions (json + jsonl), obtenu: {res.get('sessions')}"


def test_codex_cli_source_jsonl_prefixe_conv_codex(env_isole):
    ci = env_isole["ci"]
    sessions_dir = env_isole["home"] / ".codex" / "sessions" / "2026" / "10"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    f_codex = sessions_dir / "session-codex-alpha.jsonl"
    f_codex.write_text("\n".join(json.dumps(l) for l in (
        {"role": "user", "content": "Instruction pour Codex CLI d'analyser le code", "timestamp": 1791900000},
        {"role": "assistant", "content": "Analyse detaillee generee par Codex CLI pour Nokido", "timestamp": 1791900060},
    )), encoding="utf-8")

    morceaux = list(ci.iter_codex_chunks(f_codex))
    assert len(morceaux) >= 1
    src, txt, *extra = morceaux[0]
    assert src.startswith("conv_codex/"), f"Préfixe incorrect pour Codex: {src}"
    assert "Codex CLI" in txt
    entree = next((s for s in ci.SOURCES if s.get("prefixe") == "conv_codex"), None)
    assert entree is not None and "jsonl" in entree.get("motif", "")
    res = ci.index_codex_sessions(sessions_dir=env_isole["home"] / ".codex" / "sessions")
    assert res.get("ok") is True and res.get("sessions") == 1 and res.get("inserted") >= 1


def test_couverture_inclut_codex_et_gemini_jsonl(env_isole):
    ci = env_isole["ci"]
    chats_dir = env_isole["home"] / ".gemini" / "tmp" / "laforge" / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    (chats_dir / "session-g.jsonl").write_text("{}", encoding="utf-8")
    codex_dir = env_isole["home"] / ".codex" / "sessions" / "sub"
    codex_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "session-c.jsonl").write_text("{}", encoding="utf-8")

    cov = ci.couverture()
    assert cov["gemini_cli_jsonl"]["n"] >= 1, cov
    assert cov["codex_cli"]["n"] >= 1, cov


def test_warmup_rag_echec_conv_indexer_en_warning(monkeypatch, caplog):
    import forge_rag_warmup as rw

    async def faux_warmup():
        return 1
    monkeypatch.setattr(rw, "_warmup_app_index", faux_warmup)

    def faux_index_all(*a, **kw):
        raise RuntimeError("Panne simulee du moteur RAG lors de l'indexation conv")

    import forge_conv_indexer as ci
    monkeypatch.setattr(ci, "index_all", faux_index_all)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_conv_indexer", ci)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        rw.warmup_rag(force=True, batch_size=32)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "conv_indexer" in r.message]
    assert len(warnings) >= 1, "Un WARNING doit être émis lors de l'échec de conv_indexer"
    assert "Panne simulee" in warnings[0].message, warnings[0].message


def _codex_reel(dossier: Path, uuid: str, tours) -> Path:
    """Session Codex au format RÉEL du poste (mesuré le 2026-10-13) : en-tête, consignes `developer`,
    tours enveloppés dans `payload`, chaque tour répété par un `event_msg`."""
    lignes = [
        {"timestamp": "2026-09-18T15:56:51Z", "type": "session_meta", "payload": {"id": uuid, "cwd": "x"}},
        {"timestamp": "2026-09-18T15:56:52Z", "type": "response_item", "payload": {
            "type": "message", "role": "developer",
            "content": [{"type": "input_text", "text": "Consignes systeme du harnais, jamais un tour a indexer"}]}},
    ]
    for role, texte in tours:
        bloc = "input_text" if role == "user" else "output_text"
        lignes.append({"timestamp": "2026-09-18T15:57:00Z", "type": "response_item", "payload": {
            "type": "message", "role": role, "content": [{"type": bloc, "text": texte}]}})
        lignes.append({"timestamp": "2026-09-18T15:57:00Z", "type": "event_msg", "payload": {
            "type": "user_message" if role == "user" else "agent_message", "message": texte}})
    f = dossier / f"rollout-2026-09-18T17-56-51-{uuid}.jsonl"
    f.write_text("\n".join(json.dumps(l) for l in lignes), encoding="utf-8")
    return f


def test_codex_forme_reelle_enveloppee_dans_payload(env_isole):
    ci = env_isole["ci"]
    d = env_isole["home"] / ".codex" / "sessions" / "2026" / "09" / "18"
    d.mkdir(parents=True)
    uuid = "01a0b53c-1ee0-7e80-81a4-eb87077536b0"
    f = _codex_reel(d, uuid, [("user", "Question reelle posee a Codex sur le depot Nokido"),
                              ("assistant", "Reponse reelle de Codex sur le depot Nokido, detaillee")])
    morceaux = list(ci.iter_codex_chunks(f))
    textes = " ".join(t for _s, t, *_ in morceaux)
    assert "Question reelle" in textes and "Reponse reelle" in textes, morceaux
    assert "Consignes systeme" not in textes, "le role developer n'est pas un tour"
    assert textes.count("Question reelle") == 1, "les event_msg doublonnent les tours"
    assert all(s.startswith(f"conv_codex/{uuid}/") for s, *_ in morceaux), morceaux
    assert morceaux[0][2] is not None, "l'horodatage du tour est perdu"


def test_deux_sessions_du_meme_mois_ont_des_identifiants_distincts(env_isole):
    ci = env_isole["ci"]
    d = env_isole["home"] / ".codex" / "sessions" / "2026" / "09" / "18"
    d.mkdir(parents=True)
    a = _codex_reel(d, "01a0b4fe-145b-79d3-98eb-5fb14c5e0c8f", [("user", "Premiere session Codex du meme jour, assez longue")])
    b = _codex_reel(d, "01a0b4fe-a758-7c51-bd36-7ef7ba2c2baa", [("user", "Seconde session Codex du meme jour, assez longue")])
    sa = {s.rsplit("/", 1)[0] for s, *_ in ci.iter_codex_chunks(a)}
    sb = {s.rsplit("/", 1)[0] for s, *_ in ci.iter_codex_chunks(b)}
    assert sa and sb and sa.isdisjoint(sb), (sa, sb)
    res = ci.index_codex_sessions(sessions_dir=env_isole["home"] / ".codex" / "sessions")
    assert len(res["per_file"]) == 2, res["per_file"]

    g = env_isole["home"] / ".gemini" / "tmp" / "p" / "chats"
    g.mkdir(parents=True)
    for nom, sid in (("session-2026-07-29T19-46-4a28cb48.jsonl", "aaaa1111-2222"),
                     ("session-2026-07-30T10-00-bbbbbbbb.jsonl", "cccc3333-4444")):
        (g / nom).write_text(json.dumps({"sessionId": sid}) + "\n" + json.dumps(
            {"type": "user", "content": [{"text": "Message Gemini suffisamment long de la session " + sid}]}),
            encoding="utf-8")
    ids = {s.split("/")[1] for f in g.iterdir() for s, *_ in ci.iter_gemini_chunks(f)}
    assert ids == {"aaaa1111-2222", "cccc3333-4444"}, ids


def test_un_tour_long_est_decoupe_pas_tronque(env_isole):
    ci = env_isole["ci"]
    d = env_isole["home"] / ".codex" / "sessions"
    d.mkdir(parents=True)
    long = "x" * (ci.CHUNK_MAX * 2 + 123) + "FIN_DU_TOUR"
    f = _codex_reel(d, "01a0b53c-1ee0-7e80-81a4-eb87077536b1", [("assistant", long)])
    morceaux = list(ci.iter_codex_chunks(f))
    assert len(morceaux) >= 3, len(morceaux)
    assert all(len(t) <= ci.CHUNK_MAX for _s, t, *_ in morceaux)
    assert "".join(t for _s, t, *_ in morceaux).endswith("FIN_DU_TOUR"), "la fin du tour est perdue"
    assert len({s for s, *_ in morceaux}) == len(morceaux), "sources en double"


def test_index_all_couvre_tous_les_projets_gemini(env_isole, monkeypatch):
    ci = env_isole["ci"]
    for projet in ("laforge", "user"):
        c = env_isole["home"] / ".gemini" / "tmp" / projet / "chats"
        c.mkdir(parents=True)
        (c / f"session-{projet}.jsonl").write_text(json.dumps({"sessionId": projet}) + "\n" + json.dumps(
            {"type": "user", "content": "Message du projet " + projet + " qui doit etre indexe aussi"}),
            encoding="utf-8")
    for nom in ("index_claude_sessions", "index_agy_sessions", "index_desktop_sessions",
                "index_gemini_web_sessions", "index_codex_sessions"):
        monkeypatch.setattr(ci, nom, lambda *a, **k: {"ok": False})
    res = ci.index_all()
    assert res["gemini"].get("sessions") == 2, res["gemini"]


def test_couverture_dit_illisible_et_pas_zero(env_isole, monkeypatch):
    """UNKNOWN != NO : sous LaForgeTrusted, Gemini et Codex sortaient n=0 (ACL) alors que 70 sessions
    existent. Une racine non listable sort ILLISIBLE avec n=None ; une racine absente, ABSENT."""
    ci = env_isole["ci"]
    assert ci._etat_racine(env_isole["home"] / "n_existe_pas") == "ABSENT"
    (env_isole["home"] / ".codex" / "sessions").mkdir(parents=True)
    assert ci._etat_racine(env_isole["home"] / ".codex") == "OK"
    vrai = ci._etat_racine
    monkeypatch.setattr(ci, "_etat_racine",
                        lambda r: "ILLISIBLE" if r == ci.CODEX_HISTORY else vrai(r))
    cov = ci.couverture()
    assert cov["codex_cli"]["n"] is None and cov["codex_cli"]["etat"] == "ILLISIBLE", cov["codex_cli"]
    assert cov["gemini_cli_jsonl"] == {"n": 0, "etat": "ABSENT"}, cov["gemini_cli_jsonl"]


def test_dernier_passage_date_et_ecrit(env_isole, tmp_path):
    """La tache tourne sans console : le dernier passage est une preuve datee, ecrite sur disque."""
    ci = env_isole["ci"]
    cible = tmp_path / "logs" / "dernier.json"
    assert ci.ecrire_dernier_passage({"total_inserted": 3}, cible) is True
    d = json.loads(cible.read_text(encoding="utf-8"))
    assert d["resultat"]["total_inserted"] == 3 and d["fin"][:4].isdigit() and d["compte"]


def test_chemin_reel_coverage_par_le_point_d_entree(tmp_path):
    """`--coverage`, lance tel que trusted_script le lance (sous-processus), sur un profil factice."""
    import os
    import subprocess
    env = dict(os.environ, LAFORGE_OWNER_HOME=str(tmp_path), PYTHONNOUSERSITE="1")
    r = subprocess.run([sys.executable, str(ROOT / "app" / "forge_conv_indexer.py"), "--coverage"],
                       capture_output=True, text=True, errors="replace", timeout=60, env=env, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr[-800:]
    cov = json.loads(r.stdout[r.stdout.index("{"):])
    assert cov["codex_cli"] == {"n": 0, "etat": "ABSENT"}, cov


def test_tache_nocturne_versionnee_coherente():
    """La tache se pose depuis un XML du depot (seule creation permise par bash_guard) : elle vise le
    vrai module, sans console, activee, et rattrape un passage manque (poste eteint a 03:00)."""
    import xml.etree.ElementTree as ET
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    racine = ET.parse(ROOT / "tools" / "tasks" / "Nokido-ConvIndex.xml").getroot()
    commande = racine.find("t:Actions/t:Exec/t:Command", ns).text
    arguments = racine.find("t:Actions/t:Exec/t:Arguments", ns).text
    assert commande.lower().endswith("pythonw.exe"), commande
    # 14/10 (owner : « 03:00 n'est que tres rarement atteint, un cycle plus court, autoregule ») : la tache lance
    # le MODE INCREMENTAL (delta + porte d'autoregulation), toutes les 15 min et a l'ouverture de session.
    args = arguments.replace("\\", "/")
    assert '/app/forge_conv_indexer.py" --incremental' in args, arguments
    assert (ROOT / "app" / "forge_conv_indexer.py").exists()
    assert racine.find("t:Settings/t:Enabled", ns).text == "true"
    assert racine.find("t:Settings/t:StartWhenAvailable", ns).text == "true"
    assert racine.find("t:Settings/t:MultipleInstancesPolicy", ns).text == "IgnoreNew"
    intervalles = [e.text for e in racine.iter("{%s}Interval" % ns["t"])]
    assert intervalles and all(i == "PT15M" for i in intervalles), intervalles
    assert racine.find("t:Triggers/t:LogonTrigger", ns) is not None, "pas de passe a l'ouverture de session"


def test_ligne_non_json_ecartee_et_dite(env_isole, caplog):
    """Gate recidive : une ligne corrompue n'est plus avalee en silence ; un objet non-dict (liste)
    faisait planter `msg.get` et perdre la session Claude entiere."""
    ci = env_isole["ci"]
    f = env_isole["home"] / "s.jsonl"
    f.write_text("\n".join([
        "{tronque",
        json.dumps([1, 2]),
        json.dumps({"type": "user", "message": {"role": "user", "content": "Question complete et lisible apres la corruption"}}),
    ]), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        morceaux = list(ci.iter_claude_chunks(f))
    assert any("Question complete" in t for _s, t, *_ in morceaux), morceaux
    dits = [r.message for r in caplog.records if "ecartee" in r.message]
    assert dits and "2 ligne(s)" in dits[0], dits
