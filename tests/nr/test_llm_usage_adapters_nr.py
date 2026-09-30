"""NR -- adaptateurs d'usage LLM : une seule table pour Claude, Codex et AGY.

ORDRE OWNER 2026-09-12. Le but n'est PAS d'optimiser chaque CLI separement,
c'est de pouvoir repondre a une question qu'aucun outil ne peut trancher seul :

    combien de tokens Nokido a-t-il reellement EVITES a ses clients LLM ?

CE QUI EXISTE DEJA, et qu'on etend au lieu de le refaire (anti-dup) :
`token_usage` est ecrite par `app/forge_llm_transport.py::_track_usage` et
agregee PAR AGENT (CLAUDE, GEMINI, ANTIGRAVITY, CODEX) par
`tools/forge_token_meter.py`. Le bus transverse existe donc. Ce qui manque est
double :

  1. ses 10 colonnes ignorent `cache_read`, `cache_write` et `reasoning` --
     or c'est exactement la ou se joue la depense reelle ;
  2. ses ecrivains sont tous des PROVIDERS appeles par Nokido. Aucun n'alimente
     la table depuis les CLI CLIENTS eux-memes.

DEUX PIEGES NOMMES PAR L'OWNER, et que ce NR transforme en tests, parce que ce
sont les deux facons de fabriquer une mesure fausse qui a l'air juste :

  * CHAMP ABSENT != ZERO. Un flux qui ne rapporte pas le cache n'a pas un cache
    nul : il a un cache INCONNU. Ecrire 0 fabrique un denominateur faux et fait
    conclure a une economie qui n'existe pas.
  * QUOTA != USAGE. `/usage` d'un CLI montre des quotas et du restant ; les
    evenements de tour montrent la consommation. Melanger les deux donne un
    chiffre qui ne veut rien dire. Trois couches distinctes : quota de session,
    usage du tour, metrique OTel.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app" / "forge_llm_usage_adapters.py"


def _mod():
    if not SRC.exists():
        pytest.fail("%s absent -- les adaptateurs n'existent pas encore" % SRC.name)
    spec = importlib.util.spec_from_file_location("forge_llm_usage_adapters", SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# --- Echantillons a la FORME REELLE des trois flux -------------------------
# Fabriques, mais calques sur les schemas documentes de chaque CLI : une
# fixture doit ressembler a ce qui ARRIVE, pas a ce qu'on imagine.

CLAUDE_STATUSLINE = {
    "session_id": "4322ca50",
    "model": {"id": "claude-opus-5"},
    "context_window": {"total_input_tokens": 128000, "total_output_tokens": 4200},
    "current_usage": {
        "input_tokens": 3120,
        "output_tokens": 780,
        "cache_creation_input_tokens": 4096,
        "cache_read_input_tokens": 118000,
    },
}

CODEX_TURN = {
    "type": "turn.completed",
    "usage": {
        "input_tokens": 5100,
        "cached_input_tokens": 61000,
        "cache_write_input_tokens": 2048,
        "output_tokens": 910,
        "reasoning_output_tokens": 3400,
    },
}

AGY_STEP = {
    "type": "step_update",
    "model": "gemini-3.1-pro",
    "usage": {
        "input_tokens": 4200,
        "output_tokens": 650,
        "thinking_tokens": 2900,
        "cache_read_tokens": 51000,
        "total_tokens": 58750,
    },
}


# --------------------------------------------------------------------------
# 1. Les trois flux tombent dans UN SEUL contrat
# --------------------------------------------------------------------------

def test_les_trois_adaptateurs_rendent_le_meme_contrat():
    M = _mod()
    evs = [
        M.depuis_claude(CLAUDE_STATUSLINE),
        M.depuis_codex(CODEX_TURN),
        M.depuis_agy(AGY_STEP),
    ]
    for e in evs:
        assert e is not None
        for champ in ("provider", "model", "input_tokens", "output_tokens",
                      "cache_read_tokens", "cache_write_tokens",
                      "reasoning_tokens", "source"):
            assert champ in e, "champ %s absent du contrat" % champ
    assert {e["provider"] for e in evs} == {"claude", "codex", "agy"}


def test_les_valeurs_sont_reprises_FIDELEMENT():
    """Un mapping qui se trompe de champ produit une mesure plausible et fausse."""
    M = _mod()
    c = M.depuis_claude(CLAUDE_STATUSLINE)
    assert c["input_tokens"] == 3120
    assert c["cache_read_tokens"] == 118000
    assert c["cache_write_tokens"] == 4096

    x = M.depuis_codex(CODEX_TURN)
    assert x["cache_read_tokens"] == 61000, "cached_input_tokens est un cache READ"
    assert x["cache_write_tokens"] == 2048
    assert x["reasoning_tokens"] == 3400

    a = M.depuis_agy(AGY_STEP)
    assert a["reasoning_tokens"] == 2900, "thinking_tokens est du reasoning"
    assert a["cache_read_tokens"] == 51000


# --------------------------------------------------------------------------
# 2. CHAMP ABSENT != ZERO -- le piege qui fabrique de fausses economies
# --------------------------------------------------------------------------

def test_un_cache_NON_RAPPORTE_vaut_None_et_jamais_zero():
    M = _mod()
    sans_cache = {"type": "turn.completed",
                  "usage": {"input_tokens": 100, "output_tokens": 10}}
    e = M.depuis_codex(sans_cache)
    assert e["cache_read_tokens"] is None, (
        "un flux qui ne rapporte pas le cache n'a pas un cache NUL : il a un "
        "cache INCONNU. Ecrire 0 fabrique une economie qui n'existe pas.")
    assert e["reasoning_tokens"] is None
    assert e["input_tokens"] == 100, "ce qui EST rapporte doit rester exact"


def test_le_total_n_est_pas_invente_quand_les_parts_manquent():
    M = _mod()
    e = M.depuis_agy({"type": "step_update", "usage": {"input_tokens": 42}})
    assert e["output_tokens"] is None
    assert e["total_tokens"] is None, (
        "additionner des inconnues donne une somme fausse presentee comme sure")


# --------------------------------------------------------------------------
# 3. QUOTA != USAGE -- trois couches qu'on ne melange pas
# --------------------------------------------------------------------------

def test_un_payload_de_QUOTA_est_refuse_et_non_converti_en_usage():
    M = _mod()
    quota = {"type": "usage_summary", "quota": {"limit": 1000000, "remaining": 412000},
             "model": "gemini-3.1-pro"}
    assert M.depuis_agy(quota) is None, (
        "un quota restant n'est pas une consommation. Les confondre donne un "
        "chiffre qui ne veut rien dire -- et qui a l'air d'une mesure.")


def test_un_payload_inconnu_rend_None_sans_rien_inventer():
    M = _mod()
    for charge in ({}, None, {"type": "autre"}, {"usage": "pas un dict"}, []):
        for fn in (M.depuis_claude, M.depuis_codex, M.depuis_agy):
            assert fn(charge) is None


# --------------------------------------------------------------------------
# 4. Le schema etendu doit EXISTER, et NULL doit y rester possible
# --------------------------------------------------------------------------

def test_les_colonnes_de_cache_sont_declarees_pour_la_migration():
    """Presence ET type declare.

    `COLONNES_AJOUTEES` est passe de set a table TYPEE le 2026-09-12 (A4.2) :
    les colonnes d'identite sont TEXT, et SQLite rangerait une chaine dans une
    colonne INTEGER sans protester. Une egalite stricte figerait la liste et
    casserait a chaque ajout legitime ; ce qui doit etre verrouille, c'est que
    les compteurs de cache restent declares, et declares ENTIERS.
    """
    M = _mod()
    cache = {"cache_read_tokens", "cache_write_tokens", "reasoning_tokens"}
    assert cache <= set(M.COLONNES_AJOUTEES)
    for col in sorted(cache):
        assert M.COLONNES_AJOUTEES[col] == "INTEGER", (
            "%s doit rester INTEGER" % col)


def test_la_migration_est_idempotente_et_ne_detruit_rien(tmp_path):
    """ALTER TABLE ADD COLUMN, jamais de recreation.

    Les lignes anterieures gardent NULL -- qui se lit << non mesure >>, pas
    << zero >>. C'est la seule facon honnete de faire cohabiter l'ancien et le
    neuf dans la meme table.
    """
    import sqlite3
    M = _mod()
    base = tmp_path / "t.db"
    con = sqlite3.connect(base)
    con.execute("CREATE TABLE token_usage(id TEXT PRIMARY KEY, agent_id TEXT, "
                "provider TEXT, model TEXT, prompt_tokens INT, completion_tokens INT, "
                "total_tokens INT, cost_usd REAL, latency_ms REAL, source TEXT)")
    con.execute("INSERT INTO token_usage VALUES('vieux','CLAUDE','groq','x',10,2,12,0.0,5.0,'transport')")
    con.commit()

    M.migrer(con)
    M.migrer(con)  # idempotent : deux fois ne doit pas lever

    cols = {r[1] for r in con.execute("PRAGMA table_info(token_usage)")}
    assert set(M.COLONNES_AJOUTEES) <= cols
    ligne = con.execute(
        "SELECT prompt_tokens, cache_read_tokens FROM token_usage WHERE id='vieux'"
    ).fetchone()
    assert ligne[0] == 10, "la migration a abime une ligne existante"
    assert ligne[1] is None, (
        "une ligne anterieure doit rester NULL (non mesure), surtout pas 0")
    con.close()
