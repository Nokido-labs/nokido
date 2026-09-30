"""NR — un JSON valide ne doit plus produire un faux DIGEST_FAILED.

MESURE DU 2026-09-01. Le modele local a rendu une reponse parfaitement formee :

    ```json
    {"suggestions": [ ... trois entrees completes ... ]}
    ```

et le digest a sorti `JSONDecodeError: Extra data (char 235)` -> `DIGEST_FAILED`
-> `docs_marques: 0`. Cause : l'extraction prenait du PREMIER `{` au DERNIER `}`.
Quand le modele emet deux valeurs a la suite, cet intervalle en contient deux, et
`json.loads` refuse a juste titre. Un faux echec, sur une bonne reponse, qui
bloquait le curseur.

`raw_decode` s'arrete a la fin de la premiere valeur : c'est le mecanisme
standard, sans heuristique sur la forme du texte.

Second cas mesure : sur une matiere pauvre le modele rendait `[]` — une LISTE.
« Rien a dire » est un digest reussi sans suggestion, pas une panne.

HERMETIQUE : aucun reseau, aucun LLM, aucune base reelle.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(_ROOT / "app"))

import forge_veille_digest as vd  # noqa: E402


# ── extraire_json : les formes que le modele produit reellement ─────────────

@pytest.mark.parametrize("brut,attendu", [
    ('{"a": 1}', {"a": 1}),
    ('[{"a": 1}]', [{"a": 1}]),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('```\n[{"a": 1}]\n```', [{"a": 1}]),
    ('Voici ma reponse :\n{"a": 1}', {"a": 1}),
    ('{"a": 1}\nVoila, j\'espere que cela convient.', {"a": 1}),
    ('Bla bla\n```json\n{"a": 1}\n```\nfin.', {"a": 1}),
    ('[]', []),
    ('{}', {}),
])
def test_1_les_formes_reelles_sont_toutes_lues(brut, attendu):
    assert vd.extraire_json(brut) == attendu


def test_2_DEUX_valeurs_consecutives_rendent_la_PREMIERE():
    """LA regression. L'intervalle premier-`{` -> dernier-`}` en contenait deux."""
    brut = '{"suggestions": [{"s": "une"}]}\n{"suggestions": [{"s": "deux"}]}'
    val = vd.extraire_json(brut)
    assert val == {"suggestions": [{"s": "une"}]}


def test_3_l_ancienne_heuristique_aurait_echoue_la_ou_celle_ci_reussit():
    """Preuve par contraste : on montre que l'ancien chemin cassait vraiment."""
    import json as _j
    brut = '{"a": 1}\n{"b": 2}'
    s, e = brut.find("{"), brut.rfind("}")
    with pytest.raises(ValueError):
        _j.loads(brut[s:e + 1])            # l'ancienne lecture
    assert vd.extraire_json(brut) == {"a": 1}


@pytest.mark.parametrize("brut", [
    "", None, "aucun json ici", "{pas du json}", "{'guillemets': 'simples'}",
    "{", "[", "```json\n{ casse\n```",
])
def test_4_une_reponse_sans_JSON_valide_rend_None(brut):
    """None, pas une exception : l'appelant decide, et il DOIT pouvoir montrer
    la reponse recue — un echec qui cache son entree ne se diagnostique pas."""
    assert vd.extraire_json(brut) is None


def test_5_une_accolade_parasite_avant_le_vrai_JSON_ne_bloque_pas():
    """On essaie CHAQUE ouverture : une accolade isolee n'arrete pas la lecture."""
    assert vd.extraire_json('note { incomplete puis {"a": 1}') == {"a": 1}


def test_6_le_json_imbrique_reste_entier():
    brut = '```json\n{"suggestions": [{"s": "x", "meta": {"k": [1, 2]}}]}\n```'
    assert vd.extraire_json(brut)["suggestions"][0]["meta"]["k"] == [1, 2]


# ── normaliser_reponse : liste nue vs objet ────────────────────────────────

@pytest.mark.parametrize("val,attendu", [
    ({"suggestions": [{"s": "x"}]}, {"suggestions": [{"s": "x"}]}),
    ([{"s": "x"}], {"suggestions": [{"s": "x"}]}),
    ([], {"suggestions": []}),
    ("une chaine", {}),
    (42, {}),
    (None, {}),
])
def test_7_la_liste_nue_devient_un_objet_exploitable(val, attendu):
    assert vd.normaliser_reponse(val) == attendu


def test_8_les_entrees_non_objets_sont_ecartees_sans_lever():
    """`digest_batch` appelle `.get` sur chaque entree : une chaine la ferait
    lever. On filtre au lieu de casser le lot."""
    assert vd.normaliser_reponse([{"s": "ok"}, "bruit", 7]) == {"suggestions": [{"s": "ok"}]}


# ── bout en bout : plus de faux echec, et le curseur suit ──────────────────

_URL = "https://arxiv.org/abs/2405.00796v1"


def _base(tmp_path: Path) -> Path:
    db = tmp_path / "veille.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE biblio_raw (id TEXT PRIMARY KEY, title TEXT, "
              "description TEXT, url TEXT, status TEXT, created_at TEXT)")
    c.execute("INSERT INTO biblio_raw VALUES ('blr_1','Bazel','resume pauvre',"
              "?,'promoted','2026-08-28')", (_URL,))
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, "
              "sequence_id INTEGER, active INTEGER)")
    c.execute("INSERT INTO rag_chunks VALUES ('c0',?,?,0,1)",
              ("Abstract A long continuous integration build forces developers to "
               "wait for CI feedback. " + "x" * 600, _URL))
    c.commit()
    c.close()
    return db


@pytest.fixture()
def digest(tmp_path, monkeypatch):
    monkeypatch.setattr(vd, "REPORT", tmp_path / "rapport.md")
    monkeypatch.setattr(vd, "_organs", lambda: "rag")
    monkeypatch.setattr(vd, "_roadmap", lambda: "-")
    monkeypatch.setattr(vd, "DB_PATH", str(_base(tmp_path)))
    return vd


def _decode(provider, brut):
    """Rejoue EXACTEMENT le chemin de `_hub_json` sur une reponse brute donnee.

    On injecte le texte du modele, pas un dict deja parse : sinon le test
    validerait le mock au lieu du parseur.
    """
    val = vd.extraire_json(brut)
    if val is None:
        raise ValueError("pas de JSON dans la reponse %s (%d chars) : %r"
                         % (provider, len(brut), brut[:220]))
    return vd.normaliser_reponse(val)


_SUGG = ('```json\n{"suggestions": [{"s": "Integrer Bazel comme outil de build par '
         'defaut pour les projets", "organe": "rag", "prio": "P1", '
         '"src": "Bazel"}]}\n```\n{"suggestions": []}')


def test_9_une_reponse_valide_donne_DIGEST_OK_et_avance_le_curseur(
        monkeypatch, digest):
    """Deux valeurs a la suite : c'est exactement le cas qui produisait un faux
    DIGEST_FAILED. La premiere doit etre lue, et le document marque."""
    monkeypatch.setattr(vd, "_llm_json",
                        lambda prompt, provider="", modele="": _decode(provider, _SUGG))
    r = vd.backfill(limit=10, provider="llamacpp", modele="m")
    assert r["statut"] == "DIGEST_OK", r.get("raison_echec")
    assert r["suggestions_generated"] == 1
    assert r["docs_marques"] == 1


def test_10_une_liste_VIDE_est_un_digest_reussi_sans_suggestion(monkeypatch, digest):
    """« Rien a dire » n'est pas une panne : la matiere a bien ete lue."""
    vide = "```json\n[]\n```"
    monkeypatch.setattr(vd, "_llm_json",
                        lambda prompt, provider="", modele="": _decode(provider, vide))
    r = vd.backfill(limit=10, provider="llamacpp", modele="m")
    assert r["statut"] == "DIGEST_OK"
    assert r["suggestions_generated"] == 0
    assert r["docs_marques"] == 1


def test_11_une_reponse_ILLISIBLE_echoue_proprement_et_ne_marque_RIEN(
        tmp_path, monkeypatch, digest):
    """Contrat inchange : un echec laisse `digested_at` a NULL."""
    def _boum(prompt, provider="", modele=""):
        return _decode(provider, "je n'ai pas compris la demande")

    monkeypatch.setattr(vd, "_llm_json", _boum)
    r = vd.backfill(limit=10, provider="llamacpp", modele="m")
    assert r["statut"] == "DIGEST_FAILED"
    assert r["docs_marques"] == 0
    assert "pas de JSON" in (r["raison_echec"] or "")
    conn = sqlite3.connect(vd.DB_PATH)
    assert conn.execute("SELECT digested_at FROM biblio_raw").fetchone()[0] is None
    conn.close()
