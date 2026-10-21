"""Non-regression : les EMETTEURS de la couche epistemique.

Defaut mesure le 2026-08-26 : tout etait ecrit, rien ne tournait.
  * `chunk_claims` et `claim_reevaluations` : 0 ligne, six lecteurs ;
  * `forge_rag_truth.superseder` : aucun appelant — deux assertions contradictoires
    coexistaient sans qu'aucune ne soit fermee ;
  * `validate_and_promote` : aucun appelant — un brouillon ne devenait jamais verifie ;
  * `cluster_aware_retrieve` : aucun chemin reel, et son retrieval interne etait un
    balayage LIKE sur 1,3 M de lignes (celui qui a tue le hub le 23/08) ;
  * `core_memory` : creee sans retention (signale par le gate au commit d5df30950).

Ce fichier verrouille les emetteurs poses ce jour-la. Hermetique : base temporaire,
LLM double par des fonctions, aucun ecrivain reel — `forge_db_path.open_writer` est
detourne vers la base de test.
"""

from __future__ import annotations

import ast
import json
import sqlite3
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.197)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

_RACINE = Path(__file__).resolve().parents[2]
for _d in (_RACINE / "app", _RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_epistemic_extract_claims as consol  # noqa: E402
import forge_epistemic_retrieve as retrieve  # noqa: E402
import forge_memory_archival as arch  # noqa: E402
import forge_rag_truth as verite  # noqa: E402

T0 = "2026-07-01T00:00:00+00:00"
T1 = "2026-08-01T00:00:00+00:00"
T2 = "2026-09-01T00:00:00+00:00"
LARGE = 36500.0  # fenetre en jours : tout le corpus de test est « recent »

# Textes > 200 caracteres (perimetre de l'extracteur), partageant des mots pour que
# le check semantique de la porte mesure un vrai ancrage.
TXT_VIEUX = ("[user] Le hub Nokido ecoute sur le port 8765 pour son API principale, "
             "et c'est ce port que les clients MCP doivent viser pour toute requete "
             "d'orchestration ; le superviseur, lui, reste sur un autre port dedie.")
TXT_NEUF = ("Depuis la version 18, le hub Nokido ecoute sur le port 8766 pour son API "
            "principale ; les clients MCP doivent viser ce port pour toute requete "
            "d'orchestration, l'ancien port 8765 etant desormais celui du superviseur.")
TXT_BROUILLON = ("[assistant] Le hub Nokido ecoute sur le port 8766 pour son API "
                 "principale et les clients MCP visent ce port pour leurs requetes "
                 "d'orchestration ; c'est ce que la documentation indique aujourd'hui, "
                 "et le superviseur garde son propre port.")
TXT_AUTRE = ("[assistant] La lune de Jupiter nommee Europe possede un ocean sous sa "
             "croute de glace, ce qui en fait une cible privilegiee pour la recherche "
             "d'une vie extraterrestre dans le systeme solaire externe, selon la NASA.")

# Ordre VOULU : le fait recent d'abord — TXT_NEUF cite aussi l'ancien port en passant,
# et une doublure qui rendait la premiere cle trouvee attribuait au neuf l'assertion
# du vieux (paye le 2026-08-26 : 7 tests rouges sur une doublure, pas sur le code).
CLAIMS = {
    "8766": [{"text": "Nokido hub listens on port 8766 for its main API",
              "predicates": ["nokido", "hub", "port", "api", "8766"], "confidence": 0.9, "is_technical": 1}],
    "8765": [{"text": "Nokido hub listens on port 8765 for its main API",
              "predicates": ["nokido", "hub", "port", "api", "8765"], "confidence": 0.9, "is_technical": 1}],
}


def _extracteur(texte: str):
    for cle, claims in CLAIMS.items():
        if cle in texte:
            return list(claims)
    return []


def test_les_textes_de_test_sont_dans_le_perimetre_de_lextracteur():
    """Garde sur la doublure : un texte < 200 caracteres n'est jamais selectionne, et
    le test qui s'y appuie echouerait pour une raison qui n'a rien a voir."""
    for t in (TXT_VIEUX, TXT_NEUF, TXT_BROUILLON):
        assert len(t) > 200, t[:40]
    assert _extracteur(TXT_VIEUX)[0]["predicates"][-1] == "8765"
    assert _extracteur(TXT_NEUF)[0]["predicates"][-1] == "8766"
    assert _extracteur(TXT_BROUILLON)[0]["predicates"][-1] == "8766"


def _juge_contradiction(ancienne: str, nouvelle: str):
    if "8765" in ancienne and "8766" in nouvelle:
        return {"relation": "contradicts", "confidence": 0.92, "rationale": "port change"}
    if "8766" in ancienne and "8766" in nouvelle:
        return {"relation": "supports", "confidence": 0.9, "rationale": "same port"}
    return {"relation": "unrelated", "confidence": 0.9, "rationale": ""}


TABLES = (
    "CREATE TABLE rag_chunks ("
    " id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT, role_hint TEXT, author TEXT,"
    " ingested_at TEXT, meta TEXT, active INTEGER DEFAULT 1, epistemic_weight REAL DEFAULT 0.5,"
    " superseded_by TEXT)",
    "CREATE TABLE chunk_claims ("
    " id TEXT PRIMARY KEY, chunk_id TEXT NOT NULL, text TEXT NOT NULL, predicates TEXT,"
    " confidence_authored REAL DEFAULT 0.5, is_technical INTEGER DEFAULT 1,"
    " abstract_embedding BLOB, extracted_by TEXT,"
    " extracted_at TEXT DEFAULT (datetime('now', 'utc')))",
    "CREATE TABLE claim_reevaluations ("
    " older_claim_id TEXT NOT NULL, newer_claim_id TEXT NOT NULL, reevaluation_type TEXT NOT NULL,"
    " confidence REAL DEFAULT 0.5, rationale TEXT, detected_by TEXT,"
    " detected_at TEXT DEFAULT (datetime('now', 'utc')),"
    " PRIMARY KEY (older_claim_id, newer_claim_id))",
)
INSERT_CHUNK = ("INSERT INTO rag_chunks (id, text, source, domain, role_hint, ingested_at, meta) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)")


def _meta(level, valid_from):
    return json.dumps({"consensus_level": level, "valid_from": valid_from,
                       "valid_to": None, "superseded_by": None})


@pytest.fixture()
def base(tmp_path, monkeypatch):
    db = tmp_path / "epistemique.db"
    conn = sqlite3.connect(str(db))
    for ddl in TABLES:
        conn.execute(ddl)
    conn.executemany(INSERT_CHUNK, [
        ("vieux", TXT_VIEUX, "conv://owner/s1", arch._TIER_PROMU, "owner:user:promu", T0, _meta("verified", T0)),
        ("neuf", TXT_NEUF, "https://docs.example/hub", "watch_veille", "veille", T1, "{}"),
    ])
    conn.commit()
    conn.close()

    import forge_db_path

    monkeypatch.setattr(forge_db_path, "open_writer",
                        lambda *a, **k: sqlite3.connect(str(db), isolation_level=None), raising=False)
    # Le VRAI write_retry (seul open_writer, qu'il appelle, est double) : la doublure `lambda op: op()` contredisait
    # son contrat `op(conn)` -- ce test passait pendant qu'en prod 28 fermetures sur 28 rendaient « ecriture refusee
    # (TypeError) » (autonomous_loop_audit, epistemic_consolidation, mesure 16/10).
    return db


def _lire(db, sql, *args):
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _ecrire(db, sql, *args):
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _meta_de(db, cid):
    return json.loads(_lire(db, "SELECT meta FROM rag_chunks WHERE id = ?", cid)[0][0] or "{}")


# ------------------------------------------------------------ extraction 3 etats

def test_lextraction_ecrit_enfin_des_assertions(base):
    r = consol.process_batch(limit=10, extracteur=_extracteur, db_path=base, fenetre_j=LARGE)
    assert r["candidats"] == 2 and r["avec_claims"] == 2
    assert r["claims_inseres"] == 2 and len(r["claim_ids"]) == 2
    assert _lire(base, "SELECT COUNT(*) FROM chunk_claims")[0][0] == 2


def test_un_llm_muet_est_compte_muet_jamais_aucune_assertion(base):
    r = consol.process_batch(limit=10, extracteur=lambda t: None, db_path=base, fenetre_j=LARGE)
    assert r["muets"] == 2 and r["sans_claim"] == 0 and r["claims_inseres"] == 0
    statuts = {s for (s,) in _lire(base, "SELECT statut FROM epistemic_extraction_vue")}
    assert statuts == {"muet"}
    # pas re-soumis dans la foulee (RETRY_MUET_H), donc pas de boucle sur un backend couche
    r2 = consol.process_batch(limit=10, extracteur=lambda t: None, db_path=base, fenetre_j=LARGE)
    assert r2["candidats"] == 0


def test_un_texte_sans_assertion_est_compte_sans_claim(base):
    r = consol.process_batch(limit=10, extracteur=lambda t: [], db_path=base, fenetre_j=LARGE)
    assert r["sans_claim"] == 2 and r["muets"] == 0


def test_le_parseur_distingue_illisible_de_vide():
    assert consol._parser_claims("") is None
    assert consol._parser_claims("{ pas du json") is None
    assert consol._parser_claims('{"claims": []}') == []
    assert consol._parser_verdict('{"relation": "peut-etre"}') is None


# ---------------------------------------------------- contradiction -> supersession

def test_sans_juge_qualifie_aucune_fermeture_n_est_actee(base, monkeypatch):
    """16/10 : le juge local (qwen2.5-coder:1.5b) rendait 100 % `supersedes` (28/28, confiance 0,9-1,0, raison
    stereotypee) ; le rejeu de ses verdicts fermait des textes DIFFERENTS et des paires dans les DEUX sens (rejeu
    annule). Par defaut la reevaluation est ENREGISTREE, la fermeture SUSPENDUE et comptee -- jamais actee en silence."""
    monkeypatch.delenv("LAFORGE_EPISTEMIC_FERMER", raising=False)
    r = consol.consolider(limit=10, extracteur=_extracteur, juge=_juge_contradiction,
                          db_path=base, fenetre_j=LARGE)
    ree = r["reevaluation"]
    assert (ree["reevaluations"], r["fermees"], ree.get("fermetures_suspendues"), _meta_de(base, "vieux").get(
        "valid_to")) == (1, 0, 1, None)


def test_une_contradiction_reelle_ferme_lancienne_assertion(base, monkeypatch):
    """Le cas « A vrai hier, faux aujourd'hui », de bout en bout : extraction, jugement,
    `claim_reevaluations` ecrit, `superseder` appele — meta ET colonne. Fermeture AUTORISEE explicitement
    (LAFORGE_EPISTEMIC_FERMER=1 : un juge qualifie a ete designe)."""
    monkeypatch.setenv("LAFORGE_EPISTEMIC_FERMER", "1")
    r = consol.consolider(limit=10, extracteur=_extracteur, juge=_juge_contradiction,
                          db_path=base, fenetre_j=LARGE)
    ree = r["reevaluation"]
    assert ree["paires_jugees"] == 1, "la meme paire ne doit etre jugee qu'une fois"
    assert ree["reevaluations"] == 1 and ree["par_relation"] == {"contradicts": 1}
    assert r["fermees"] == 1 and ree["refusees_autorite"] == 0
    rows = _lire(base, "SELECT reevaluation_type, confidence FROM claim_reevaluations")
    assert rows == [("contradicts", 0.92)]
    m = _meta_de(base, "vieux")
    assert m["valid_to"] == T1 and m["superseded_by"] == "neuf"
    assert _lire(base, "SELECT superseded_by FROM rag_chunks WHERE id='vieux'")[0][0] == "neuf"
    assert verite.est_valide_a(m, T0) is True, "et a T0 ? doit garder une reponse"
    assert verite.est_valide_a(m, T2) is False
    assert _lire(base, "SELECT COUNT(*) FROM rag_chunks WHERE id='vieux'")[0][0] == 1, "efface"


def test_un_brouillon_ne_ferme_jamais_un_fait_verifie(base):
    """La contradiction est ENREGISTREE, pas ACTEE : l'autorite du nouveau est
    inferieure. Sans ce garde, une hallucination assistant fermerait un fait owner."""
    _ecrire(base, "DELETE FROM rag_chunks WHERE id = 'neuf'")
    _ecrire(base, INSERT_CHUNK, "brouillon", TXT_BROUILLON, "conv://agent/s2", arch._TIER_BROUILLON,
            "agent:assistant:brouillon", T1, _meta("draft", T1))
    r = consol.consolider(limit=10, extracteur=_extracteur, juge=_juge_contradiction,
                          db_path=base, fenetre_j=LARGE)
    ree = r["reevaluation"]
    assert ree["reevaluations"] == 1 and ree["refusees_autorite"] == 1 and r["fermees"] == 0
    m = _meta_de(base, "vieux")
    assert m["valid_to"] is None and m["superseded_by"] is None


def test_un_juge_muet_est_compte_muet_et_rien_nest_ecrit(base):
    r = consol.consolider(limit=10, extracteur=_extracteur, juge=lambda a, b: None,
                          db_path=base, fenetre_j=LARGE)
    assert r["reevaluation"]["juge_muet"] == 1 and r["muets"] == 1
    assert _lire(base, "SELECT COUNT(*) FROM claim_reevaluations")[0][0] == 0
    assert _meta_de(base, "vieux")["valid_to"] is None


# --------------------------------------------------------- corroboration -> porte

def test_la_porte_promeut_un_brouillon_corrobore_par_une_source_independante(base):
    _ecrire(base, "DELETE FROM rag_chunks WHERE id = 'vieux'")
    _ecrire(base, INSERT_CHUNK, "brouillon", TXT_BROUILLON, "conv://agent/s2", arch._TIER_BROUILLON,
            "agent:assistant:brouillon", T2, _meta("draft", T2))
    r = consol.consolider(limit=10, extracteur=_extracteur, juge=_juge_contradiction,
                          db_path=base, fenetre_j=LARGE)
    assert r["reevaluation"]["par_relation"] == {"supports": 1}
    assert r["promus"] == 1, r["reevaluation"]["raisons_refus"]
    m = _meta_de(base, "brouillon")
    assert m["consensus_level"] == "verified", "plafond VERIFIED, jamais GOLD par corroboration auto"
    assert any(s.get("agent") == "epistemic:corroboration" for s in m.get("verified_by", []))
    dom, role = _lire(base, "SELECT domain, role_hint FROM rag_chunks WHERE id='brouillon'")[0]
    assert dom == arch._TIER_PROMU and role.endswith(":promu")


def test_la_porte_refuse_une_corroboration_de_la_meme_source(base):
    _ecrire(base, INSERT_CHUNK, "brouillon", TXT_BROUILLON, "https://docs.example/hub",
            arch._TIER_BROUILLON, "agent:assistant:brouillon", T2, _meta("draft", T2))
    r = arch.promouvoir_brouillon("brouillon", "neuf", db_path=base)
    assert r["promu"] is False and "meme source" in r["raison"]
    assert _meta_de(base, "brouillon")["consensus_level"] == "draft"


def test_le_juge_n_est_jamais_appele_sur_deux_assertions_de_la_meme_source(base):
    """18/10 (mesure + decision owner « ne pas promouvoir ») : les 61 `supports` du juge qualifie etaient
    61 paires de textes IDENTIQUES issues de la MEME source re-ingeree. La porte les aurait refusees (test
    ci-dessus), mais en amont le juge etait PAYE pour chacune et le registre comptait des corroborations qui
    n'en sont pas. Une copie n'est pas un temoin : la paire est ecartee AVANT le juge, et l'ecart est COMPTE."""
    _ecrire(base, INSERT_CHUNK, "copie", TXT_NEUF, "https://docs.example/hub", "watch_veille", "veille", T2, "{}")
    appels = []

    def juge(ancienne, nouvelle):
        appels.append((ancienne, nouvelle))
        return {"relation": "supports", "confidence": 0.95, "rationale": "copie"}

    ext = consol.process_batch(limit=10, extracteur=_extracteur, db_path=base, fenetre_j=LARGE)
    b = consol.reevaluer(ext["claim_ids"], juge=juge, db_path=base, nom_juge="t")
    assert b.get("paires_meme_source", 0) >= 1, "l'ecart d'une paire de meme source doit etre COMPTE, pas muet"
    assert not [a for a, n in appels if a == n], "le juge a ete appele sur une assertion et sa propre copie"


def test_la_porte_refuse_un_brouillon_sans_ancrage_semantique(base):
    _ecrire(base, INSERT_CHUNK, "autre", TXT_AUTRE, "conv://agent/s3", arch._TIER_BROUILLON,
            "agent:assistant:brouillon", T2, _meta("draft", T2))
    r = arch.promouvoir_brouillon("autre", "neuf", db_path=base)
    assert r["promu"] is False and "Jaccard" in r["raison"], r["raison"]
    assert _meta_de(base, "autre")["consensus_level"] == "draft"


# ------------------------------------------------------ chemin vivant : as-of + conflits

def test_le_chemin_vivant_ecarte_les_assertions_fermees_et_le_dit(base, monkeypatch):
    monkeypatch.setenv("LAFORGE_EPISTEMIC_FERMER", "1")  # une fermeture suppose un juge qualifie (16/10)
    consol.consolider(limit=10, extracteur=_extracteur, juge=_juge_contradiction,
                      db_path=base, fenetre_j=LARGE)
    resultats = [{"id": "vieux", "content": TXT_VIEUX, "source": "rag:a"},
                 {"id": "neuf", "content": TXT_NEUF, "source": "rag:b"}]
    q = retrieve.qualifier_resultats(resultats, instant=T2, db_path=base)
    assert [c["id"] for c in q["retenus"]] == ["neuf"]
    assert [c["id"] for c in q["ecartes"]] == ["vieux"]
    assert q["illisible"] is None
    # « et a T0+ ? » : les deux valaient avant la fermeture
    q0 = retrieve.qualifier_resultats(resultats, instant="2026-07-15T00:00:00+00:00", db_path=base)
    assert {c["id"] for c in q0["retenus"]} == {"vieux", "neuf"}


def test_le_chemin_vivant_etiquette_un_conflit_non_resolu(base):
    """Un brouillon contredit un fait verifie : non acte (autorite), mais le fait
    verifie est SERVI ETIQUETE — l'agent voit qu'une refutation existe."""
    _ecrire(base, "DELETE FROM rag_chunks WHERE id = 'neuf'")
    _ecrire(base, INSERT_CHUNK, "brouillon", TXT_BROUILLON, "conv://agent/s2", arch._TIER_BROUILLON,
            "agent:assistant:brouillon", T1, _meta("draft", T1))
    consol.consolider(limit=10, extracteur=_extracteur, juge=_juge_contradiction,
                      db_path=base, fenetre_j=LARGE)
    q = retrieve.qualifier_resultats([{"id": "vieux", "content": TXT_VIEUX}], instant=T2, db_path=base)
    assert [c["id"] for c in q["retenus"]] == ["vieux"]
    assert "vieux" in q["conflits"] and q["conflits"]["vieux"][0]["type"] == "contradicts"


def test_le_chemin_vivant_ne_balaie_jamais_la_table(base, monkeypatch):
    def _interdit(*a, **k):
        raise AssertionError("LIKE sur rag_chunks — la forme qui a tue le hub le 23/08")

    monkeypatch.setattr(retrieve, "_fetch_top_k", _interdit)
    out = retrieve.cluster_aware_retrieve("", chunks=[{"id": "vieux", "content": TXT_VIEUX}], db_path=base)
    assert out["summary"]["consensus_count"] == 1


def test_une_base_absente_est_dite_illisible_pas_vide(tmp_path):
    q = retrieve.qualifier_resultats([{"id": "x", "content": "y"}], db_path=tmp_path / "absente.db")
    assert q["illisible"] and [c["id"] for c in q["retenus"]] == ["x"]
    assert not (tmp_path / "absente.db").exists(), "sqlite3.connect a fabrique une base vide"


# ----------------------------------------------------------- retention core_memory

def test_la_retention_de_core_memory_est_declaree_et_mesuree(tmp_path, monkeypatch):
    import forge_log_retention as ret

    racine = tmp_path / "corps"
    (racine / "RAG").mkdir(parents=True)
    db = racine / "RAG" / "embeddings.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE core_memory (agent_id TEXT PRIMARY KEY, persona TEXT, user_persona TEXT, "
                 "facts TEXT, updated_at TEXT)")
    conn.execute("CREATE TABLE conv_archives (id TEXT PRIMARY KEY, agent_id TEXT, archived_at TEXT)")
    conn.executemany("INSERT INTO core_memory VALUES (?, 'p', 'u', 'f', ?)", [
        ("mort", "2025-01-01T00:00:00+00:00"),
        ("vivant", "2025-01-01T00:00:00+00:00"),
        ("recent", "2099-01-01T00:00:00+00:00"),
    ])
    conn.execute("INSERT INTO conv_archives VALUES ('a1', 'vivant', '2099-01-01T00:00:00+00:00')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(ret, "ROOT", racine)

    sec = ret._purge_core_memory(dry=True)
    assert sec["core_memory_purged"] == 1 and sec["agents"] == ["mort"] and sec["dry_run"] is True
    assert sorted(a for (a,) in _lire(db, "SELECT agent_id FROM core_memory")) == ["mort", "recent", "vivant"]

    reel = ret._purge_core_memory(dry=False)
    assert reel["core_memory_purged"] == 1 and reel["restants"] == 2
    assert sorted(a for (a,) in _lire(db, "SELECT agent_id FROM core_memory")) == ["recent", "vivant"]


def test_la_retention_est_branchee_dans_le_cycle():
    src = (_RACINE / "tools" / "forge_log_retention.py").read_text(encoding="utf-8")
    assert '"core_memory": _purge_core_memory(dry)' in src
    assert '"epistemic_vue": _purge_epistemic_vue(dry)' in src
    assert '"epistemic_claims": _purge_epistemic_claims(dry)' in src


def test_la_purge_des_assertions_orphelines_est_mesuree(tmp_path, monkeypatch):
    """Le schema promet ON DELETE CASCADE ; sans PRAGMA foreign_keys la cascade ne joue
    jamais. La purge retire ce que la cascade aurait du retirer, et le compte."""
    import forge_log_retention as ret

    racine = tmp_path / "corps"
    (racine / "RAG").mkdir(parents=True)
    db = racine / "RAG" / "embeddings.db"
    conn = sqlite3.connect(str(db))
    for ddl in TABLES:
        conn.execute(ddl)
    conn.execute(INSERT_CHUNK, ("vivant", TXT_NEUF, "s", "watch_veille", "v", T1, "{}"))
    conn.executemany("INSERT INTO chunk_claims (id, chunk_id, text, predicates) VALUES (?, ?, ?, '[]')", [
        ("c_vivant", "vivant", "a"), ("c_orphelin", "disparu", "b"),
    ])
    conn.executemany("INSERT INTO claim_reevaluations (older_claim_id, newer_claim_id, reevaluation_type) "
                     "VALUES (?, ?, 'supports')", [("c_vivant", "c_orphelin"), ("c_vivant", "c_vivant")])
    conn.commit()
    conn.close()
    monkeypatch.setattr(ret, "ROOT", racine)

    sec = ret._purge_epistemic_claims(dry=True)
    assert sec["claims_orphelines"] == 1 and sec["dry_run"] is True
    assert _lire(db, "SELECT COUNT(*) FROM chunk_claims")[0][0] == 2
    reel = ret._purge_epistemic_claims(dry=False)
    assert reel["claims_orphelines"] == 1
    assert [c for (c,) in _lire(db, "SELECT id FROM chunk_claims")] == ["c_vivant"]
    assert _lire(db, "SELECT COUNT(*) FROM claim_reevaluations")[0][0] == 1, "la reevaluation orpheline reste"


# -------------------------------------------------------------------- cadence

def test_la_consolidation_a_une_cadence_declaree_avec_llm_local_et_garde_ram():
    """Un emetteur sans cadence retourne dormir — c'est exactement la dette."""
    src = (_RACINE / "app" / "forge_autonomous_loops.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    fonction = next((n for n in arbre.body if isinstance(n, ast.FunctionDef)
                     and n.name == "pat_epistemic_consolidation"), None)
    assert fonction is not None, "pattern absent"
    deco = fonction.decorator_list[0]
    assert isinstance(deco, ast.Call) and deco.args[0].value == "epistemic_consolidation"
    kw = {k.arg: k.value for k in deco.keywords}
    assert kw["requires_local_llm"].value is True
    corps = ast.get_source_segment(src, fonction)
    assert "_ram_gate(" in corps and "consolider(" in corps and "_local_llm_available()" in corps


# DECISION OWNER 17/10, option (A) : les RE-JUGEMENTS par un juge qualifie vont dans une base SEPAREE (aucun
# changement de schema de la grosse base) ; `reevaluer` relit les deux, le verdict du juge qualifie PRIME, l'ancien
# verdict reste en base (rien supprime). Sans base de re-jugement, une paire deja jugee par le juge local ne
# pouvait JAMAIS etre re-jugee (controle `deja` sur claim_reevaluations) -- le juge local degenere restait seul.
def _juge_qualifie(ancienne, nouvelle):
    return {"relation": "supports", "confidence": 0.3, "rationale": "juge qualifie (test)"}


def test_un_rejugement_qualifie_va_dans_la_base_separee_et_prime(base, tmp_path, monkeypatch):
    monkeypatch.delenv("LAFORGE_EPISTEMIC_FERMER", raising=False)
    consol.consolider(limit=10, extracteur=_extracteur, juge=_juge_contradiction, db_path=base, fenetre_j=LARGE)
    avant = _lire(base, "SELECT older_claim_id, newer_claim_id, reevaluation_type, detected_by "
                        "FROM claim_reevaluations")
    assert len(avant) == 1, avant
    ids = [r[0] for r in _lire(base, "SELECT id FROM chunk_claims")]
    rejug = tmp_path / "rejugements.db"

    b = consol.reevaluer(ids, juge=_juge_qualifie, db_path=base, nom_juge="qualifie", rejugement_db=rejug)
    assert b["paires_jugees"] >= 1 and b["reevaluations"] == 1, b
    # la grosse base n'a pas bouge : l'ancien verdict reste, rien n'est ajoute ni supprime
    assert _lire(base, "SELECT older_claim_id, newer_claim_id, reevaluation_type, detected_by "
                       "FROM claim_reevaluations") == avant
    neuf = _lire(rejug, "SELECT older_claim_id, newer_claim_id, reevaluation_type, detected_by "
                        "FROM claim_reevaluations")
    assert [(r[0], r[1]) for r in neuf] == [(avant[0][0], avant[0][1])], neuf
    assert neuf[0][2:] == ("supports", "qualifie"), neuf

    eff = consol.verdict_effectif(avant[0][0], avant[0][1], db_path=base, rejugement_db=rejug)
    assert eff and eff["relation"] == "supports" and eff["detected_by"] == "qualifie", eff

    # idempotent : un second re-jugement ne repose pas la question
    b2 = consol.reevaluer(ids, juge=_juge_qualifie, db_path=base, nom_juge="qualifie", rejugement_db=rejug)
    assert b2["paires_jugees"] == 0, b2


# DECISION OWNER 16/10 + item decision_owner_a_prendre_rejugement_epistemique : « faire re-juger les 36 supports par le
# juge QUALIFIE et mesurer les verdicts AVANT toute ouverture de promouvoir_brouillon ». `reevaluer` promouvait (et
# fermait, sous LAFORGE_EPISTEMIC_FERMER=1) des que le verdict etait sur : lancer la mesure l'aurait violee (18/10).
def test_mesure_seule_compte_sans_promouvoir_ni_fermer(base, tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_EPISTEMIC_FERMER", "1")
    consol.consolider(limit=10, extracteur=_extracteur, juge=_juge_contradiction, db_path=base, fenetre_j=LARGE)
    ids = [r[0] for r in _lire(base, "SELECT id FROM chunk_claims")]
    avant = _lire(base, "SELECT * FROM chunk_claims ORDER BY id")
    sur = {"relation": "supports", "confidence": 0.99, "rationale": "juge qualifie sur (test)"}
    b = consol.reevaluer(ids, juge=lambda a, n: sur, db_path=base, nom_juge="qualifie",
                         rejugement_db=tmp_path / "r1.db", mesure_seule=True)
    assert b["promotions_mesurees"] >= 1 and b["promus"] == 0 and b["promotions_refusees"] == 0, b
    contra = {"relation": "contradicts", "confidence": 0.99, "rationale": "juge qualifie sur (test)"}
    b2 = consol.reevaluer(ids, juge=lambda a, n: contra, db_path=base, nom_juge="qualifie",
                          rejugement_db=tmp_path / "r2.db", mesure_seule=True)
    assert b2["fermetures_mesurees"] >= 1 and b2["fermees"] == 0 and b2["fermetures_refusees"] == 0, b2
    assert _lire(base, "SELECT * FROM chunk_claims ORDER BY id") == avant, "la grosse base ne bouge pas"


def test_rejuger_supports_vise_les_supports_en_mesure_seule_vers_la_base_separee(base, tmp_path, monkeypatch):
    """Chemin de l'item rejugement : les paires que le juge LOCAL a jugees -- QUEL QUE SOIT le type (mesure 18/10 :
    %NOKIDO_DATA%\\embeddings.db porte 42 `supersedes` locaux et 0 `supports`, le libelle « 36 supports » ne designait rien) --
    sont re-jugees par le juge qualifie, en MESURE SEULE, vers la base de re-jugement ; jamais de promotion."""
    consol.consolider(limit=10, extracteur=_extracteur, juge=_juge_contradiction, db_path=base, fenetre_j=LARGE)
    vus = {}

    def espion(ids, **k):
        vus.update(k, ids=list(ids))
        return {"paires_jugees": 0}

    monkeypatch.setattr(consol, "reevaluer", espion)
    consol.rejuger_supports_mesure(db_path=base, rejugement_db=tmp_path / "r.db", backend="routeur")
    assert vus.get("mesure_seule") is True and vus.get("rejugement_db") == tmp_path / "r.db", vus
    assert vus.get("ids"), "les assertions des paires `supports` sont selectionnees"


def test_accord_inter_juges_mesure_sans_rien_ecrire(base, tmp_path, monkeypatch):
    """Decision owner 18/10 (choix multiple) : avant d'ouvrir la promotion des 61 `supports`, un ECHANTILLON est re-juge
    par un SECOND juge different ; on n'ouvre que si l'accord atteint 80 %. Mesure seule : aucune ecriture."""
    consol.consolider(limit=10, extracteur=_extracteur, juge=_juge_contradiction, db_path=base, fenetre_j=LARGE)
    ids = [r[0] for r in _lire(base, "SELECT id FROM chunk_claims")]
    rejug = tmp_path / "r.db"
    consol.reevaluer(ids, juge=lambda a, n: {"relation": "supports", "confidence": 0.9, "rationale": "q"},
                     db_path=base, nom_juge="qualifie_routeur", rejugement_db=rejug, mesure_seule=True)
    avant = _lire(rejug, "SELECT * FROM claim_reevaluations")
    d = consol.accord_inter_juges(n=10, juge2=lambda a, n: {"relation": "supports", "confidence": 0.8,
                                                            "rationale": "j2"},
                                  rejugement_db=rejug, db_path=base, graine=1)
    assert d["n"] >= 1 and d["accord"] == d["n"] and d["taux"] == 1.0 and d["ouvrir"] is True, d
    d2 = consol.accord_inter_juges(n=10, juge2=lambda a, n: {"relation": "unrelated", "confidence": 0.8,
                                                             "rationale": "j2"},
                                   rejugement_db=rejug, db_path=base, graine=1)
    assert d2["taux"] == 0.0 and d2["ouvrir"] is False and d2["desaccords"], d2
    assert _lire(rejug, "SELECT * FROM claim_reevaluations") == avant, "mesure seule : rien n'est ecrit"


def test_juge_local7b_interroge_un_modele_local_plus_grand(monkeypatch):
    """18/10 : le second juge `cerebras` est reste MUET 10/10 (job_81443261b41b) ; le juge `local` est le 1,5B qui
    disait 42/42 supersedes. Second avis independant, gratuit et joignable : un modele local plus grand."""
    vu = {}

    class _R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"response": "{\\"relation\\": \\"supports\\", \\"confidence\\": 0.7, \\"rationale\\": \\"x\\"}"}'

    def faux_urlopen(req, timeout=None):
        vu["corps"] = json.loads(req.data.decode("utf-8"))
        return _R()

    monkeypatch.setattr(consol.urllib.request, "urlopen", faux_urlopen)
    v = consol.juge_backend("local7b")("a", "b")
    assert vu["corps"]["model"] != consol.MODELE_LOCAL and "7b" in vu["corps"]["model"] or "qwen2.5" in vu["corps"]["model"]
    assert v and v["relation"] == "supports", v


def test_sans_base_de_rejugement_le_comportement_est_inchange(base, monkeypatch):
    monkeypatch.delenv("LAFORGE_EPISTEMIC_FERMER", raising=False)
    consol.consolider(limit=10, extracteur=_extracteur, juge=_juge_contradiction, db_path=base, fenetre_j=LARGE)
    ids = [r[0] for r in _lire(base, "SELECT id FROM chunk_claims")]
    b = consol.reevaluer(ids, juge=_juge_qualifie, db_path=base, nom_juge="qualifie")
    assert b["paires_jugees"] == 0, b          # deja jugee dans la grosse base : pas re-posee
    eff = consol.verdict_effectif(*_lire(base, "SELECT older_claim_id, newer_claim_id FROM claim_reevaluations")[0],
                                  db_path=base)
    assert eff and eff["relation"] != "supports", eff   # sans re-jugement, c'est le verdict d'origine
