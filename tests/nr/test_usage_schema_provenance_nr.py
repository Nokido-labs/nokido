"""NR A4.2 — schema TYPE, cout a trois etats, provenance NON deduite.

Trois verrous poses par l'owner le 2026-09-12, chacun contre un faux mesure :

1. TYPE DECLARE. `migrer()` faisait `ADD COLUMN <nom> INTEGER` pour toute
   colonne. SQLite accepterait une chaine dans une colonne INTEGER sans rien
   dire (affinite de type), donc le defaut serait invisible a l'usage et ne se
   verrait qu'a la premiere comparaison ou au premier tri. On verifie donc le
   TYPE DECLARE via `PRAGMA table_info`, pas le fait qu'un SELECT rende
   quelque chose.

2. COUT. `_pricing_lookup` rend `(0.0, 0.0)` pour un modele inconnu : mesure du
   12/09, `cost_usd = 0.0` sur 4663 lignes sur 7859 et ZERO NULL. Un tarif
   absent doit rendre NULL ; seule une gratuite PROUVEE vaut 0.

3. PROVENANCE. Le recorder ne DEDUIT rien. Ni depuis `agent_id`, ni depuis le
   nom du module, du processus ou de la cmdline. Une provenance non transportee
   vaut `UNKNOWN` -- un aveu, pas une invention. C'est ce qui empeche
   `forge_agent_proxy` de redevenir l'identite de 97,9 % des lignes.
"""
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

import forge_token_monitor as tm  # noqa: E402
from forge_llm_usage_adapters import depuis_claude  # noqa: E402

TEXTE = ("provenance", "execution_mode", "transport", "execution_id",
         "parent_execution_id", "measurement_kind", "measurement_source",
         "cost_kind", "cost_source", "writer_component")
ENTIERS = ("cache_read_tokens", "cache_write_tokens", "reasoning_tokens")


def _base(tmp_path):
    """Table minimale, a la forme du schema d'origine."""
    p = tmp_path / "usage.db"
    con = sqlite3.connect(str(p))
    con.execute(
        "CREATE TABLE token_usage (id TEXT PRIMARY KEY, ts TEXT, agent_id TEXT,"
        " provider TEXT, model TEXT, prompt_tokens INTEGER,"
        " completion_tokens INTEGER, total_tokens INTEGER, cost_usd REAL,"
        " latency_ms REAL, source TEXT, session_id TEXT, meta TEXT)")
    con.execute("CREATE TABLE network_log (ts TEXT, direction TEXT, method TEXT,"
                " tool TEXT, agent TEXT, status TEXT, channel TEXT, meta TEXT,"
                " provider TEXT, model TEXT, latency_ms REAL, session_id TEXT)")
    con.commit()
    return p, con


def test_les_colonnes_texte_sont_declarees_TEXT(tmp_path):
    _, con = _base(tmp_path)
    tm.migrer(con)
    types = {r[1]: (r[2] or "").upper()
             for r in con.execute("PRAGMA table_info(token_usage)")}
    con.close()
    for col in TEXTE:
        assert types.get(col) == "TEXT", (
            "%s declare %r au lieu de TEXT : SQLite stockerait la chaine sans "
            "protester, et le defaut ne se verrait qu'au tri ou a la "
            "comparaison" % (col, types.get(col)))
    for col in ENTIERS:
        assert types.get(col) == "INTEGER", (
            "%s declare %r au lieu de INTEGER" % (col, types.get(col)))


def test_prix_d_un_modele_inconnu_vaut_None_pas_zero():
    assert tm._price("modele-qui-n-existe-pas-xyz", 1000, 100) is None, (
        "un tarif absent rendu 0 se somme en silence et produit un cout "
        "faussement bas -- et faussement precis")


def test_un_modele_tarife_rend_une_valeur():
    """Temoin positif : sans lui, rendre None partout passerait le test."""
    modeles = list(getattr(tm, "PRICING", {}) or {})
    assert modeles, "table de prix vide : le NR mesurerait le neant"
    val = tm._price(modeles[0], 1000, 100)
    assert val is not None and val >= 0


def test_provider_local_est_gratuit_PROUVE(tmp_path, monkeypatch):
    p, con = _base(tmp_path)
    con.close()
    monkeypatch.setattr(tm, "DB", p)
    tm.log_call(agent_id="X", provider="ollama", model="quoi-que-ce-soit",
                prompt_tokens=10, completion_tokens=2, latency_ms=1.0)
    con = sqlite3.connect(str(p))
    cout, genre = con.execute(
        "SELECT cost_usd, cost_kind FROM token_usage").fetchone()
    con.close()
    assert genre == "FREE" and cout == 0, (
        "un provider local est gratuit PROUVE : 0 avec FREE, pas un 0 muet")


def test_tarif_inconnu_ecrit_NULL_et_UNKNOWN_PRICING(tmp_path, monkeypatch):
    p, con = _base(tmp_path)
    con.close()
    monkeypatch.setattr(tm, "DB", p)
    tm.log_call(agent_id="X", provider="groq", model="modele-hors-table-xyz",
                prompt_tokens=10, completion_tokens=2, latency_ms=1.0)
    con = sqlite3.connect(str(p))
    cout, genre = con.execute(
        "SELECT cost_usd, cost_kind FROM token_usage").fetchone()
    con.close()
    assert cout is None, "tarif inconnu : NULL, jamais 0"
    assert genre == "UNKNOWN_PRICING"


def test_le_recorder_n_invente_pas_la_provenance(tmp_path, monkeypatch):
    p, con = _base(tmp_path)
    con.close()
    monkeypatch.setattr(tm, "DB", p)
    tm.log_call(agent_id="forge_agent_proxy", provider="groq", model="m",
                prompt_tokens=1, completion_tokens=1, latency_ms=1.0)
    con = sqlite3.connect(str(p))
    prov, writer = con.execute(
        "SELECT provenance, writer_component FROM token_usage").fetchone()
    con.close()
    assert prov == "UNKNOWN", (
        "provenance non transportee = UNKNOWN. Un aveu, pas une invention")
    assert prov != "forge_agent_proxy", (
        "le module ecrivain ne redevient PAS l'identite du client")
    assert writer == "forge_agent_proxy", (
        "le writer reste consigne, mais a sa place")


def test_la_statusline_RELAIE_l_identite_jusqu_au_recorder(tmp_path, monkeypatch):
    """Le maillon que les NR unitaires ne voyaient pas.

    Mesure du 2026-09-12 : l'adaptateur posait bien provenance / mode /
    transport, et `_collecter` ne les transmettait PAS a `log_call`. Resultat
    en base reelle : 13 lignes a `provenance = UNKNOWN` alors que chaque
    maillon, teste seul, etait correct. Un mecanisme present mais non cable
    n'est pas une capacite -- c'est une dette de cablage.

    Ce test suit le chemin REEL : il appelle `_collecter` et espionne ce qui
    arrive au recorder, au lieu de verifier les deux extremites separement.
    """
    sys.path.insert(0, str(RACINE / "tools"))
    import nokido_statusline as sl

    recu = {}
    monkeypatch.setattr(tm, "log_call", lambda **kw: recu.update(kw))
    monkeypatch.setattr(sl, "ETAT", tmp_path / "statusline.json")

    sl._collecter({
        "model": "claude-opus-5", "input_tokens": 2, "output_tokens": 2,
        "cache_read_tokens": 433309, "cache_write_tokens": 4874,
        "reasoning_tokens": None, "source": "claude_statusline",
        "session_id": "S-reelle", "provenance": "CLAUDE",
        "execution_mode": "INTERACTIVE", "transport": "CLI_HTTP",
        "measurement_kind": "REPORTED",
    })

    assert recu, "le recorder n'a pas ete appele du tout"
    for champ, attendu in (("provenance", "CLAUDE"),
                           ("execution_mode", "INTERACTIVE"),
                           ("transport", "CLI_HTTP"),
                           ("measurement_kind", "REPORTED")):
        assert recu.get(champ) == attendu, (
            "%s non relaye : l'adaptateur remplit un evenement que personne "
            "ne transmet" % champ)
    assert recu.get("agent_id") == "nokido_statusline", (
        "agent_id nomme le WRITER ; l'identite du client vit dans provenance")
    assert recu.get("cache_read_tokens") == 433309


def test_l_adapter_claude_transporte_l_identite_reelle():
    charge = {
        "model": {"id": "claude-opus-5"},
        "session_id": "sess-reelle-42",
        "context_window": {
            "total_input_tokens": 4242,
            "current_usage": {"input_tokens": 2, "output_tokens": 2,
                              "cache_read_input_tokens": 433309,
                              "cache_creation_input_tokens": 4874},
        },
    }
    ev = depuis_claude(charge)
    assert ev["provenance"] == "CLAUDE"
    assert ev["execution_mode"] == "INTERACTIVE"
    assert ev["transport"] == "CLI_HTTP"
    assert ev["session_id"] == "sess-reelle-42", (
        "la session vient du payload du client, pas d'un uuid fabrique")
    assert ev["measurement_kind"] == "REPORTED", (
        "ces compteurs sont fournis par le client, ils ne sont pas estimes")
