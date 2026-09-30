"""NR — le JOINT capability graph : `actions_prouvees` (fiche_capability_graph_joint_2026-09-27).

Le planificateur GOAP ne lit que `ALLOWED_METHODS` ; les capacités PROUVÉES par usage vivent dans un
autre registre (`forge_capability_crosswalk`). Ce joint les croise. Invariants (texte owner « conscience
opérationnelle » J2/J5) :
- une capacité DÉCLARÉE non prouvée n'est JAMAIS une action planifiable (DECLARED ≠ INVOCABLE) ;
- une capacité PROUVÉE mais hors whitelist est NOMMÉE dans `non_planifiables`, jamais écartée en silence
  (c'est la dette de vascularisation à combler) ;
- aucune précondition ni effet n'est FABRIQUÉ : ce qui n'est pas connu vaut UNKNOWN, jamais [].

Autonome : construit un faux crosswalk, ne dépend pas du socle vivant (qui bouge).
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "tools" / "forge_capability_crosswalk.py"


def _charger():
    spec = importlib.util.spec_from_file_location("forge_capability_crosswalk_nr", MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _crosswalk_factice():
    return {
        "n_capacites": 3,
        "capacites": [
            {"id": "CAP-tool_A", "tool": "tool_A", "tier": "garanti", "calls_au_gel": 5, "tests": ["t_a"], "trous": []},
            {"id": "CAP-tool_B", "tool": "tool_B", "tier": "best", "calls_au_gel": 3, "tests": [], "trous": ["ring_non_declare"]},
            {"id": "CAP-tool_D", "tool": "tool_D", "tier": "best", "calls_au_gel": 0, "tests": [], "trous": ["aucune_mention_en_test"]},
        ],
    }


# tool_A planifiable+prouvé ; tool_D dans la whitelist mais 0 usage ; method_C planifiable jamais vue ; tool_B prouvé HORS whitelist
_ALLOWED = {"tool_A": {"ring": 2}, "tool_D": {"ring": 2}, "method_C": {"ring": 1}}


def test_declaree_non_prouvee_jamais_une_action():
    m = _charger()
    r = m.actions_prouvees(_crosswalk_factice(), _ALLOWED)
    tools_actions = {a["tool"] for a in r["actions"]}
    assert "tool_D" not in tools_actions        # 0 usage : déclarée, pas invocable
    assert "method_C" not in tools_actions       # jamais observée
    non_prouves = {x.get("method") or x.get("tool") for x in r["non_prouves"]}
    assert "tool_D" in non_prouves and "method_C" in non_prouves


def test_prouvee_et_planifiable_devient_action():
    m = _charger()
    r = m.actions_prouvees(_crosswalk_factice(), _ALLOWED)
    a = next((a for a in r["actions"] if a["tool"] == "tool_A"), None)
    assert a is not None
    assert a["planifiable"] is True
    assert a["etat_preuve"] in ("INVOCABLE", "RELIABLE")


def test_prouvee_hors_whitelist_est_nommee_jamais_muette():
    m = _charger()
    r = m.actions_prouvees(_crosswalk_factice(), _ALLOWED)
    noms = {x["tool"] for x in r["non_planifiables"]}
    assert "tool_B" in noms                      # prouvée par usage mais hors ALLOWED_METHODS
    # jamais silencieusement écartée : chaque capacité prouvée est classée quelque part
    tous = {a["tool"] for a in r["actions"]} | noms
    assert "tool_A" in tous and "tool_B" in tous


def test_precondition_effet_jamais_fabriques():
    m = _charger()
    r = m.actions_prouvees(_crosswalk_factice(), _ALLOWED, contracts=None)
    a = next(a for a in r["actions"] if a["tool"] == "tool_A")
    assert a["preconditions"] == ["UNKNOWN"]     # aucun contrat fourni : UNKNOWN, pas []
    assert a["effets"] == ["UNKNOWN"]
