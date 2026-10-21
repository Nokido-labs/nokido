"""NR -- l'executeur EMET un transient quand une delegation echoue sans livrer, pour que les autres surfaces le lisent
au tour suivant (decision owner 19/10 : « emetteur de transients »).

Le canal `nokido.transient.v1` (forge_m2m_protocol, intent TRANSIENT_OBSERVED) etait normalise mais personne n'emettait
les BLOCAGES : cette nuit, trois executeurs OpenCode ont echoue en boucle (429, silence) sans que rien ne le dise aux
autres CLI. Pas de demon parallele : le tableau noir (zone discovered_facts, lue par les hooks d'inbox) est le bus ; la
cle `transient_<agent>_<effet>` deduplique (upsert), `expire_at` borne la vie du signal, et le lecteur
`transients_actifs` ne rend que les transients non expires.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


def _capture(monkeypatch):
    vus = []
    monkeypatch.setenv("NOKIDO_VERDICT_AUTO", "1")    # le conftest le coupe pour tous les autres tests
    import nokido_agent.app.forge_swarm_blackboard as B
    import nokido_agent.app.forge_motivation as M
    monkeypatch.setattr(B, "apply_fact_sync", lambda zone, fact, **kw: vus.append((zone, fact, kw)) or {"ok": True})
    monkeypatch.setattr(M, "recompenser_resultat", lambda *a, **k: None)
    return vus


def test_une_panne_fournisseur_emet_un_transient_dedoublonne(monkeypatch):
    vus = _capture(monkeypatch)
    T._consigner_verdict_auto("OPENCODE_GPTOSS", "job_x", False, "commits produits : 0",
                              "erreur ACP OpenCode (RuntimeError): HTTP 429 Too Many Requests", None)
    assert len(vus) == 1
    zone, fait, kw = vus[0]
    t = json.loads(fait)
    assert zone == "discovered_facts" and kw["key"] == "transient_OPENCODE_GPTOSS_panne"
    assert kw["category"] == "transient" and kw["ring"] <= 2
    for champ in ("intent", "schema", "source", "provenance", "effect", "source_call_id", "content_fingerprint"):
        assert champ in t, champ
    assert t["intent"] == "TRANSIENT_OBSERVED" and t["effect"] == "panne" and "429" in t["resume"]
    assert time.time() < t["expire_at"] <= time.time() + 3600


def test_un_vide_prouve_emet_un_transient_vide(monkeypatch):
    vus = _capture(monkeypatch)
    T._consigner_verdict_auto("OPENCODE_GLM", "job_y", False, "commits produits : 0 ; [AUCUN EFFET]", "fini", None)
    assert vus and vus[0][2]["key"] == "transient_OPENCODE_GLM_vide"


def test_une_reussite_n_emet_rien(monkeypatch):
    vus = _capture(monkeypatch)
    T._consigner_verdict_auto("OPENCODE_GLM", "job_z", True, "commits produits : 1", "OK", None)
    assert vus == []


def test_l_interrupteur_coupe_verdict_et_transient(monkeypatch):
    """19/10 : sans lui, les NR de delegation ecrivaient de FAUX verdicts dans le vrai registre de recompense."""
    vus = _capture(monkeypatch)
    import nokido_agent.app.forge_motivation as M
    notes = []
    monkeypatch.setattr(M, "recompenser_resultat", lambda *a, **k: notes.append(a))
    monkeypatch.setenv("NOKIDO_VERDICT_AUTO", "0")
    T._consigner_verdict_auto("OPENCODE_GLM", "job_w", False, "commits produits : 0 ; [AUCUN EFFET]", "fini", None)
    assert vus == [] and notes == []


def test_le_conftest_coupe_le_verdict_automatique_des_tests():
    import os
    assert os.environ.get("NOKIDO_VERDICT_AUTO") == "0"


def test_le_lecteur_ne_rend_que_les_transients_non_expires(monkeypatch):
    import nokido_agent.app.forge_swarm_blackboard as B
    maintenant = time.time()
    faits = [{"key": "transient_A_panne", "category": "transient",
              "value": json.dumps({"intent": "TRANSIENT_OBSERVED", "expire_at": maintenant + 60})},
             {"key": "transient_B_panne", "category": "transient",
              "value": json.dumps({"intent": "TRANSIENT_OBSERVED", "expire_at": maintenant - 1})},
             {"key": "transient_C_vide", "category": "transient", "value": "pas du json"}]
    monkeypatch.setattr(B, "read_zone", lambda zone, **kw: faits)
    actifs = T.transients_actifs()
    assert [a["cle"] for a in actifs] == ["transient_A_panne"]
