"""NR — la copie RAG d'un tour de conversation passe la DLP ; sans DLP, rien n'est indexe.

Decision owner du 24/09 (veille lot_B_05) : `log_turn` recopiait chaque tour EN CLAIR dans
`rag_chunks` (memoire episodique), qui nourrit des contextes envoyes aux modeles. On REUTILISE la
DLP existante (`forge_semantic_firewall.redact_tool_output`, les DEUX jeux de motifs) sur cette
copie. Le journal brut (`conversation_log`) reste local et intact.

24/09, second temps : la 1re version appelait `redact_text` seul, qui ne connait AUCUNE cle
d'API — mesure sur des cles fictives a la forme reelle : GitHub, Groq, AWS, Hugging Face et
OpenRouter passaient en clair. Les cles sont donc testees ici, forme par forme.

Regles verrouillees :
  - donnee sensible (ici un courriel) masquee dans rag_chunks, conservee dans le journal ;
  - DLP indisponible -> AUCUNE copie RAG (fail-closed), le journal est ecrit, et c'est DIT ;
  - la borne de 2000 caracteres est DITE dans la copie (motif `borne_trop_serree`).
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
COURRIEL = "prenom.nom" + "@" + "exemple.org"      # construit : aucun scanner ne le prend pour une fuite


def _logger():
    spec = importlib.util.spec_from_file_location(
        "forge_conversation_logger_nr", RACINE / "app" / "forge_conversation_logger.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _base(tmp_path):
    db = tmp_path / "journal.db"
    cx = sqlite3.connect(db)
    cx.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT,"
               " role_hint TEXT, author TEXT, ingested_at TEXT)")
    cx.commit()
    cx.close()
    return str(db)


def _lire(db, sql):
    cx = sqlite3.connect(db)
    try:
        return cx.execute(sql).fetchall()
    finally:
        cx.close()


def test_courriel_masque_dans_le_rag_et_garde_au_journal(tmp_path):
    m = _logger()
    db = _base(tmp_path)
    r = m.log_turn("sess0001", "human", "ecris-moi a %s demain" % COURRIEL, db_path=db)
    assert r["ok"]
    rag = _lire(db, "SELECT text FROM rag_chunks")
    assert rag and COURRIEL not in rag[0][0], "courriel en clair dans la memoire episodique"
    assert "[EMAIL_" in rag[0][0]
    assert COURRIEL in _lire(db, "SELECT content FROM conversation_log")[0][0], "le journal local doit rester brut"


def test_dlp_indisponible_aucune_copie_rag(tmp_path, monkeypatch):
    m = _logger()
    db = _base(tmp_path)
    casse = types.ModuleType("nokido_agent.app.forge_semantic_firewall")   # sans redact_text
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_semantic_firewall", casse)
    r = m.log_turn("sess0002", "human", "contenu quelconque %s" % COURRIEL, db_path=db)
    assert _lire(db, "SELECT COUNT(*) FROM rag_chunks")[0][0] == 0, "copie RAG ecrite SANS DLP"
    assert _lire(db, "SELECT COUNT(*) FROM conversation_log")[0][0] == 1
    assert r.get("rag") == "NON_INDEXE_DLP_INDISPONIBLE", r


_CORPS = "Ab3dE5gH7jK9" * 12          # construit : aucun litteral de cle dans ce fichier
CLES_FICTIVES = {
    "github": "gh" + "p_" + _CORPS[:36],
    "github_fin": "github" + "_pat_" + _CORPS[:22] + "_" + _CORPS[:59],
    "groq": "gs" + "k_" + _CORPS[:52],
    "aws": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "huggingface": "h" + "f_" + _CORPS[:34],
    "openrouter": "sk-" + "or-v1-" + ("0123456789abcdef" * 4),
    "anthropic": "sk-" + "ant-api03-" + _CORPS[:93] + "AA",
}


def test_cles_d_api_masquees_dans_le_rag(tmp_path):
    m = _logger()
    db = _base(tmp_path)
    contenu = " | ".join("%s=%s" % (k, v) for k, v in CLES_FICTIVES.items())
    m.log_turn("sess0004", "human", contenu, db_path=db)
    rag = _lire(db, "SELECT text FROM rag_chunks")[0][0]
    fuites = [k for k, v in CLES_FICTIVES.items() if v in rag]
    assert not fuites, "cle(s) d'API en clair dans la memoire episodique : %s" % fuites
    journal = _lire(db, "SELECT content FROM conversation_log")[0][0]
    assert all(v in journal for v in CLES_FICTIVES.values()), "le journal local doit rester brut"


def test_motifs_de_cles_absents_aucune_copie_rag(tmp_path, monkeypatch):
    """Redaction PARTIELLE (infrastructure seule) = fail-closed, pas une copie a moitie propre."""
    m = _logger()
    db = _base(tmp_path)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secret_guard",
                        types.ModuleType("nokido_agent.app.forge_secret_guard"))
    r = m.log_turn("sess0005", "human", "texte quelconque", db_path=db)
    assert _lire(db, "SELECT COUNT(*) FROM rag_chunks")[0][0] == 0, "copie RAG sans motifs de cles"
    assert r.get("rag") == "NON_INDEXE_DLP_INDISPONIBLE", r


# Donnees PERSONNELLES fictives (decision owner 24/09 : TOUTES les categories). Construites :
# aucun litteral qu'un scanner prendrait pour une vraie donnee.
PERSONNELLES = {
    "telephone": "06 " + "12 34 56 78",
    "telephone_intl": "+33 " + "6 12 34 56 78",
    "iban": "FR76 " + "3000 6000 0112 3456 7890 189",
    "carte": "4111 " + "1111 " * 2 + "1111",   # numero de TEST valide Luhn (sans Luhn : non masque, a dessein)
    "nir": "1 85 05 " + "75 123 456 78",
    "adresse": "12 rue de la " + "Paix 75002 Paris",
    "ip_publique": "203.0." + "113.42",
    "civilite": "Monsieur " + "Dupont",
}


def test_donnees_personnelles_masquees_dans_le_rag(tmp_path):
    m = _logger()
    db = _base(tmp_path)
    contenu = "\n".join("%s : %s" % (k, v) for k, v in PERSONNELLES.items())
    r = m.log_turn("sess0006", "human", contenu, db_path=db)
    rag = _lire(db, "SELECT text FROM rag_chunks")[0][0]
    fuites = [k for k, v in PERSONNELLES.items() if v in rag]
    assert not fuites, "donnee(s) personnelle(s) en clair dans la memoire episodique : %s" % fuites
    assert str(r.get("rag", "")).startswith("INDEXE_MASQUE_"), r
    journal = _lire(db, "SELECT content FROM conversation_log")[0][0]
    assert all(v in journal for v in PERSONNELLES.values()), "le journal local doit rester brut"


def test_une_phrase_technique_n_est_pas_abimee(tmp_path):
    """Le masquage ne doit pas detruire la memoire : sha, versions, chemins publics, compteurs."""
    m = _logger()
    db = _base(tmp_path)
    phrase = "le commit b3d27a002 corrige 3 fichiers ; 268 tests verts ; version 2.1.281 ; job_7e131bd9a0b1"
    m.log_turn("sess0007", "assistant", phrase, db_path=db)
    assert phrase in _lire(db, "SELECT text FROM rag_chunks")[0][0]


def test_borne_de_la_copie_rag_dite(tmp_path):
    m = _logger()
    db = _base(tmp_path)
    m.log_turn("sess0003", "assistant", "x" * 5000, db_path=db)
    texte = _lire(db, "SELECT text FROM rag_chunks")[0][0]
    assert "non indexes" in texte, "la coupe a 2000 caracteres doit etre DITE"
