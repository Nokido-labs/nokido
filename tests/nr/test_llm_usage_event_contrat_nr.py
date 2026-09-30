"""NR du contrat `LLMUsageEvent` — P0-A, arrete par l'owner le 2026-09-12.

Ce que ce contrat empeche, et qui a ete MESURE le meme jour sur les 7839
lignes de `token_usage` (baseline `docs/baselines/usage_T0_2026-09-12.json`) :

  agent_id = 'forge_agent_proxy' sur 7671/7839 (97,9 %)  -> on mesurait QUI
      ECRIT, jamais QUI DEMANDE. `agent_id` est un parametre de signature :
      chaque appelant y mettait son propre nom.
  session_id renseigne 0/7839, meta 2/7839 -> les deux champs prevus pour la
      provenance n'ont JAMAIS servi.

Deux invariants, et ils ne se negocient pas :

1. La provenance est un TUPLE (provenance, execution_mode, transport), pas
   une etiquette. AGY/INTERACTIVE/CLI_OAUTH et AGY/AUTONOMOUS/M2M partagent
   le modele et le fournisseur, mais ce sont deux consommateurs distincts.
   Les confondre rend le tableau de couts joli et FAUX.

2. `measurement_kind` separe ce que le FOURNISSEUR a rapporte de ce que
   Nokido a ESTIME localement (tiktoken). Une estimation n'est pas une
   preuve de facturation. Melanger les deux en silence est exactement la
   facon dont une telemetrie devient un mensonge confortable.

Et la symetrie, qui compte autant : un usage NON MESURE vaut `UNKNOWN` avec
des compteurs a None -- jamais zero. Un zero se somme, un None se voit.
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

from forge_llm_usage_event import (  # noqa: E402
    MESURES,
    MODES,
    PROVENANCES,
    TRANSPORTS,
    ErreurContrat,
    cle_agregation,
    creer,
)

BASE = dict(
    execution_id="E1",
    provenance="AGY",
    execution_mode="INTERACTIVE",
    transport="CLI_OAUTH",
    provider="gemini",
    model="gemini-2.5-pro",
    measurement_kind="REPORTED",
    measurement_source="provider_usage",
)


def test_les_enums_couvrent_les_identites_reelles():
    for p in ("CLAUDE", "AGY", "CODEX", "UNKNOWN"):
        assert p in PROVENANCES
    for m in ("INTERACTIVE", "AUTONOMOUS", "M2M", "UNKNOWN"):
        assert m in MODES
    for t in ("DESKTOP_STDIO", "CLI_HTTP", "CLI_OAUTH", "M2M", "JSONL", "UNKNOWN"):
        assert t in TRANSPORTS
    assert set(MESURES) == {"REPORTED", "ESTIMATED", "UNKNOWN"}


def test_agy_cli_et_agy_m2m_ne_se_confondent_pas():
    cli = creer(**BASE)
    m2m = creer(**dict(BASE, execution_id="E2", execution_mode="AUTONOMOUS",
                       transport="M2M"))
    assert cle_agregation(cli) != cle_agregation(m2m)
    assert cle_agregation(cli) == ("AGY", "INTERACTIVE", "CLI_OAUTH")


def test_claude_stdio_et_claude_http_ne_se_confondent_pas():
    a = creer(**dict(BASE, provenance="CLAUDE", transport="DESKTOP_STDIO",
                     provider="anthropic", model="claude-opus-5"))
    b = creer(**dict(BASE, provenance="CLAUDE", transport="CLI_HTTP",
                     provider="anthropic", model="claude-opus-5"))
    assert cle_agregation(a) != cle_agregation(b)


def test_codex_ne_se_confond_pas_avec_agy():
    codex = creer(**dict(BASE, provenance="CODEX", execution_mode="EXEC",
                         transport="JSONL"))
    assert cle_agregation(codex) != cle_agregation(creer(**BASE))


def test_execution_id_est_obligatoire():
    with pytest.raises(ErreurContrat):
        creer(**dict(BASE, execution_id=""))


def test_provenance_inconnue_vaut_UNKNOWN_jamais_le_module_ecrivain():
    ev = creer(**dict(BASE, provenance=None, execution_mode=None, transport=None))
    assert ev["provenance"] == "UNKNOWN"
    assert ev["execution_mode"] == "UNKNOWN"
    assert ev["transport"] == "UNKNOWN"


def test_une_provenance_hors_enum_est_REFUSEE_pas_silencieusement_rangee():
    with pytest.raises(ErreurContrat):
        creer(**dict(BASE, provenance="forge_agent_proxy"))


def test_estimation_exige_sa_source_nommee():
    with pytest.raises(ErreurContrat):
        creer(**dict(BASE, measurement_kind="ESTIMATED", measurement_source=None))
    ev = creer(**dict(BASE, measurement_kind="ESTIMATED",
                      measurement_source="tiktoken:cl100k_base",
                      input_tokens=120))
    assert ev["measurement_kind"] == "ESTIMATED"
    assert ev["measurement_source"] == "tiktoken:cl100k_base"


def test_une_estimation_ne_peut_pas_se_declarer_REPORTED():
    with pytest.raises(ErreurContrat):
        creer(**dict(BASE, measurement_kind="REPORTED",
                     measurement_source="tiktoken:cl100k_base"))


def test_usage_non_mesure_rend_None_et_UNKNOWN_jamais_zero():
    ev = creer(**dict(BASE, measurement_kind="UNKNOWN", measurement_source=None))
    for champ in ("input_tokens", "output_tokens", "reasoning_tokens",
                  "cache_read_tokens", "cache_creation_tokens"):
        assert ev[champ] is None, "%s doit rester None, un zero se sommerait" % champ


def test_UNKNOWN_refuse_des_compteurs_qui_pretendraient_mesurer():
    with pytest.raises(ErreurContrat):
        creer(**dict(BASE, measurement_kind="UNKNOWN", measurement_source=None,
                     input_tokens=42))


def test_cache_read_et_cache_creation_restent_separes():
    ev = creer(**dict(BASE, input_tokens=10, output_tokens=2,
                      cache_read_tokens=900, cache_creation_tokens=7))
    assert ev["cache_read_tokens"] == 900
    assert ev["cache_creation_tokens"] == 7
    assert "cache_tokens" not in ev, "les deux natures de cache ne se fusionnent pas"


def test_event_id_est_pose_et_stable_dans_l_evenement():
    ev = creer(**BASE)
    assert ev["event_id"] and isinstance(ev["event_id"], str)
    assert creer(**BASE)["event_id"] != ev["event_id"], "un id par evenement"


def test_parent_execution_id_est_optionnel_mais_present_dans_le_schema():
    ev = creer(**BASE)
    assert "parent_execution_id" in ev
    assert ev["parent_execution_id"] is None
    enfant = creer(**dict(BASE, execution_id="E3", parent_execution_id="E1"))
    assert enfant["parent_execution_id"] == "E1"


def test_status_par_defaut_et_champs_temporels_presents():
    ev = creer(**BASE)
    for champ in ("started_at", "completed_at", "duration_ms", "status",
                  "session_id"):
        assert champ in ev
    assert ev["status"] in ("OK", "PENDING", "FAILED", "UNKNOWN")
