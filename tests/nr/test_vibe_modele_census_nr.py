# -*- coding: utf-8 -*-
"""NR (decision owner 19/10 « invariant bloquant ») : un executeur ne delegue jamais sur un modele que le census PROUVE
hors quota, et sa config perimee ecrite par l'executeur se regenere.

Mesure : le 19/10 au matin, Vibe a ete passe a mistral-medium-latest alors que le census (17/10) le mesurait a
`x-ratelimit-limit-req-minute: 0` sur notre cle -- l'essai job_10971233 a rendu 429 avant toute action ; et
`_config_mcp_vibe` n'ecrasait JAMAIS un fichier existant, donc un changement de modele dans le code n'atteignait pas le
worktree. Invariant : `_modele_hors_quota` rend un motif si le census prouve 0 req/min ou un modele mort (402/404/410) ;
census absent, illisible ou muet sur le couple = None (INCONNU n'est pas NON : on delegue et on le dit).
"""
import ast
import inspect
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


def _census(tmp_path, verdicts):
    p = tmp_path / "census.json"
    p.write_text(json.dumps({"verdicts": verdicts}), encoding="utf-8")
    return p


def test_un_modele_a_zero_requete_minute_est_refuse(tmp_path):
    p = _census(tmp_path, {"mistral:mistral-medium-latest": {
        "joignable": False, "motif": "HTTP 429",
        "limites": {"x-ratelimit-limit-req-minute": "0", "x-ratelimit-remaining-req-minute": "0"}}})
    motif = T._modele_hors_quota("mistral", "mistral-medium-latest", p)
    assert motif and "0 req/min" in motif


def test_un_modele_mort_est_refuse_un_joignable_passe(tmp_path):
    p = _census(tmp_path, {"mistral:vieux": {"joignable": False, "motif": "HTTP 404", "limites": {}},
                           "mistral:codestral-latest": {"joignable": True, "motif": "",
                                                        "limites": {"x-ratelimit-limit-req-minute": "125"}}})
    assert "404" in (T._modele_hors_quota("mistral", "vieux", p) or "")
    assert T._modele_hors_quota("mistral", "codestral-latest", p) is None


def test_census_absent_ou_muet_n_est_pas_un_refus(tmp_path):
    assert T._modele_hors_quota("mistral", "codestral-latest", tmp_path / "absent.json") is None
    illisible = tmp_path / "x.json"
    illisible.write_text("{pas du json", encoding="utf-8")
    assert T._modele_hors_quota("mistral", "codestral-latest", illisible) is None
    # un 429 SANS limite nulle est un debit passager, pas une interdiction : pas de refus
    p = _census(tmp_path, {"mistral:m": {"joignable": False, "motif": "HTTP 429", "limites": {}}})
    assert T._modele_hors_quota("mistral", "m", p) is None


def test_la_config_ecrite_par_l_executeur_et_perimee_se_regenere(tmp_path):
    (tmp_path / ".vibe").mkdir()
    ancienne = T._CONFIG_MCP_VIBE.replace('active_model = "codestral-nokido"', 'active_model = "medium-nokido"')
    (tmp_path / ".vibe" / "config.toml").write_text(ancienne, encoding="utf-8")
    cfg = tomllib.loads(T._config_mcp_vibe(tmp_path).read_text(encoding="utf-8"))
    assert cfg["active_model"] == "codestral-nokido"


def test_la_delegation_vibe_passe_par_l_invariant():
    src = inspect.getsource(T._delegate_to_vibe)
    assert "_modele_hors_quota" in src
    cfg = tomllib.loads(T._CONFIG_MCP_VIBE)
    (m,) = [x for x in cfg["models"] if x["alias"] == cfg["active_model"]]
    assert ("mistral", m["name"]) == T._MODELE_VIBE
    ast.parse(src.replace("    ", "", 1) if src.startswith("    ") else src)
