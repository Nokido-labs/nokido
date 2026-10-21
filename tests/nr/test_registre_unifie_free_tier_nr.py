"""NR -- RED4 du plan free tier (`test_unified_registry_schema_and_generation`) : registre UNIFIE des surfaces.

Plan certifie 60d8ed546 + releve AGY 19/10 (job_6cfab01f, INTEGREE) : un registre data/surfaces_free_tier_registry.json,
racine {horodatage, surfaces, totaux, version_schema}, une entree par surface fournisseur:modele avec 13 cles. Genere
par le recensement EXISTANT (tools/forge_free_tier_census.py, regle « zero nouveau module ») en fusionnant ses
verdicts/preuves et forge_provider_specs. Liste blanche : GRATUIT_PROUVE seulement si joignable ET tier gratuit/local ;
une valeur non mesuree vaut None, jamais une invention.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_free_tier_census as C  # noqa: E402

CLES = {"fournisseur", "modele", "statut_gratuit", "declare", "gratuit_annonce", "joignable", "quota_primaire",
        "specialite", "capabilities", "acces_cli", "acces_swarm", "outils_supportes", "mesure_le"}

CENSUS = {"horodatage": "2026-10-19T01:06:00",
          "fournisseurs": [{"fournisseur": "groq", "preuves": [{"modele": "allam-2-7b", "joignable": True, "motif": ""}],
                            "quota": "NON MESURE"}],
          "verdicts": {"groq:llama-3.3-70b": {"declare": False, "joignable": False, "motif": "HTTP 404",
                                              "mesure_le": "2026-10-17T00:00:15"},
                       "cerebras:qwen": {"declare": True, "joignable": False, "motif": "HTTP 402",
                                         "mesure_le": "2026-10-19T01:06:00"},
                       "ollama:qwen2.5-coder": {"declare": True, "joignable": True, "motif": "", "outils": True,
                                                "mesure_le": "2026-10-19T01:06:00"}}}
SPECS = {"groq": {"tier": "free", "capabilities": ["chat", "code"], "notes": "rapide"},
         "ollama_local": {"tier": "local", "capabilities": ["chat", "code", "tool_call"], "notes": "local"}}


def test_schema_et_cles_obligatoires():
    r = C.registre_unifie(CENSUS, SPECS)
    assert {"horodatage", "surfaces", "totaux", "version_schema"} <= set(r)
    assert len(r["surfaces"]) == 4 and all(CLES <= set(s) for s in r["surfaces"])


def test_liste_blanche_du_statut_gratuit():
    s = {(x["fournisseur"], x["modele"]): x for x in C.registre_unifie(CENSUS, SPECS)["surfaces"]}
    assert s[("groq", "allam-2-7b")]["statut_gratuit"] == "GRATUIT_PROUVE"
    assert s[("ollama", "qwen2.5-coder")]["statut_gratuit"] == "GRATUIT_PROUVE"
    assert s[("cerebras", "qwen")]["statut_gratuit"] == "PAYANT_PROUVE"
    assert s[("groq", "llama-3.3-70b")]["statut_gratuit"] == "INCONNU"
    assert s[("cerebras", "qwen")]["capabilities"] is None and s[("cerebras", "qwen")]["acces_cli"] is None


def test_le_drapeau_ecrit_le_registre(tmp_path, monkeypatch):
    src = tmp_path / "census.json"
    src.write_text(json.dumps(CENSUS), encoding="utf-8")
    cible = tmp_path / "data" / "registre.json"
    monkeypatch.setattr(C, "SORTIE", src)
    monkeypatch.setattr(sys, "argv", ["forge_free_tier_census.py", "--registre-unifie", str(cible)])
    assert C.main() == 0
    assert json.loads(cible.read_text(encoding="utf-8"))["version_schema"] == "1"
