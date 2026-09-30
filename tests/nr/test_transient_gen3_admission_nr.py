"""NR — GEN-3 : un transient devient ADMISSIBLE et ADRESSABLE, sans etre execute.

GEN-3 est volontairement petit. Son succes n'est pas de faire travailler quelque
chose : c'est de prouver qu'un transient franchit la frontiere

    OBSERVE  ->  ACCEPTE / REJETE / UNKNOWN  +  destination identifiee

et RIEN de plus. La moitie de ces tests verifie donc ce qui ne doit PAS arriver,
parce que c'est la seule facon d'empecher une generation de s'attribuer le
travail de la suivante.

TROIS MESURES DU 2026-09-17 FIXENT CE PERIMETRE, et aucune ne vient du plan :

1. `route_subtask` appelle `router_call`, donc un LLM. Ce n'est pas un routeur
   generique de workers. Aucun appel LLM avant GEN-6 : les tests l'exigent.

2. `forge_lane_admission.check_ressources(heavy=True)` n'est PAS une lecture :
   en cas de saturation il appelle `_try_reserve()`, qui peut ARRETER Ollama,
   llama-server ou des conteneurs. Une observation ne doit jamais avoir ce
   pouvoir -- une seule intention en produit deja DEUX par double cablage. D'ou
   `resource_state = NON_CONSULTE`, qui est une abstention DECLAREE et non une
   ignorance.

3. `decide()` appelle `forge_recon_breaker.verdict()`, un coupe-circuit a SEUIL.
   La rappeler pour admettre incrementerait ce compteur une seconde fois. Une
   admission REUTILISE donc la decision de policy quand elle existe, et dit
   laquelle des deux voies elle a prise.

ANTI-EMBOLIE : la propriete centrale de ce cliquet est `0 acquire()`. N
observations donnent N decisions et ZERO reservation. C'est ce qui garantit que
le Spine ne transforme pas une anomalie de configuration en famine de ressources.
"""
from __future__ import annotations

import os
import sys

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (RACINE, os.path.join(RACINE, "app"), os.path.join(RACINE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

gate = pytest.importorskip("forge_tool_gate")
proto = pytest.importorskip("forge_m2m_protocol")


def _transient(tool_name="Read", payload=None, call_id="toolu_A"):
    ev = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-gen3",
        "tool_use_id": call_id,
        "tool_name": tool_name,
        "tool_input": payload if payload is not None else {"file_path": "/tmp/x.txt"},
    }
    t = proto.normaliser_transient(ev)
    assert t is not None, "pre-requis : GEN-1 doit savoir normaliser cet evenement"
    return t


@pytest.fixture
def espions(monkeypatch):
    """Espionne TOUT ce que GEN-3 n'a pas le droit de declencher."""
    vus = []

    def _pister(nom, module, attribut):
        try:
            mod = __import__(module, fromlist=["_"])
        except Exception:
            return  # module absent : rien a pister, et c'est deja une garantie
        if hasattr(mod, attribut):
            monkeypatch.setattr(mod, attribut,
                                lambda *a, **k: vus.append(nom) or {})

    _pister("acquire", "forge_lane_admission", "acquire")
    _pister("admit", "forge_lane_admission", "admit")
    _pister("check_ressources", "forge_lane_admission", "check_ressources")
    _pister("route_subtask", "forge_swarm_router", "route_subtask")
    return vus


# ── CAS A : accepte ────────────────────────────────────────────────────────

def test_cas_A_un_transient_anodin_est_ACCEPTE_avec_une_destination(espions):
    d = gate.admettre_transient(_transient())
    assert d["decision"] == "ACCEPTED", d
    assert d["destination"], "un transient accepte doit porter une destination"
    assert espions == [], "GEN-3 a declenche %r" % espions


# ── CAS B : rejete ─────────────────────────────────────────────────────────

def test_cas_B_un_sous_agent_est_REJETE_avec_sa_raison(espions):
    """La regle owner du 2026-09-06 passe par la policy, pas par une regle neuve."""
    t = _transient(tool_name="Task",
                   payload={"subagent_type": "Explore", "description": "recon"})
    d = gate.admettre_transient(t)
    assert d["decision"] == "REJECTED", d
    assert d["reason"], "un refus sans raison n'est pas exploitable"
    assert espions == []


# ── CAS C : inconnu, jamais optimiste ──────────────────────────────────────

def test_cas_C_policy_indisponible_donne_UNKNOWN_et_non_ACCEPTED(monkeypatch, espions):
    def _casse(*a, **k):
        raise RuntimeError("policy indisponible")
    monkeypatch.setattr(gate, "decide", _casse)
    d = gate.admettre_transient(_transient())
    assert d["decision"] == "UNKNOWN", (
        "une policy en panne ne fabrique pas une autorisation : %r" % d)
    assert espions == []


def test_un_transient_malforme_est_REJETE():
    d = gate.admettre_transient({"pas": "un transient"})
    assert d["decision"] == "REJECTED"
    assert d["reason"]


# ── LA PROPRIETE CENTRALE : 0 acquire ──────────────────────────────────────

def test_N_observations_donnent_N_decisions_et_ZERO_reservation(espions):
    """Anti-embolie. Avec le double cablage mesure, 1 appel -> 2 observations.

    Si l'admission reservait, une simple lecture de fichier consommerait deux
    lanes. C'est exactement la famine que `forge_lane_admission` existe pour
    prevenir.
    """
    decisions = [gate.admettre_transient(_transient(call_id="toolu_%d" % i))
                 for i in range(6)]
    assert len(decisions) == 6
    assert all(d["decision"] in ("ACCEPTED", "REJECTED", "UNKNOWN") for d in decisions)
    assert espions == [], "GEN-3 doit faire ZERO reservation, vu : %r" % espions


def test_la_ressource_est_declaree_NON_CONSULTEE_avec_sa_raison():
    d = gate.admettre_transient(_transient())
    assert d["resource_state"] == "NON_CONSULTE", (
        "GEN-3 ne consulte pas la capacite : `check_ressources(heavy=True)` peut "
        "ARRETER des services, et `heavy=False` n'observe rien")
    assert d.get("resource_reason"), "une abstention se DECLARE, avec son motif"


# ── ZERO LLM ───────────────────────────────────────────────────────────────

def test_aucun_module_de_routage_LLM_n_est_charge():
    avant = {n for n in sys.modules if "swarm_router" in n or "llm_router" in n}
    gate.admettre_transient(_transient())
    apres = {n for n in sys.modules if "swarm_router" in n or "llm_router" in n}
    assert apres <= avant, (
        "GEN-3 a charge un routeur d'intelligence : %r. Aucun LLM avant GEN-6."
        % sorted(apres - avant))


# ── REUTILISATION DE LA POLICY ─────────────────────────────────────────────

def test_une_policy_FOURNIE_n_est_pas_recalculee(monkeypatch):
    """`decide()` incremente un coupe-circuit a SEUIL : on ne la rappelle pas.

    Sans cela, admettre un transient ferait avancer le compteur du breaker une
    seconde fois -- et deux fois plus vite encore avec le double cablage.
    """
    appels = []
    monkeypatch.setattr(gate, "decide",
                        lambda *a, **k: appels.append(1) or {"action": "native"})
    fournie = {"action": "native", "target": None, "reason": "deja calculee"}
    d = gate.admettre_transient(_transient(), policy=fournie)
    assert appels == [], "la policy fournie a quand meme ete recalculee"
    assert d["policy_source"] == "FOURNIE"


def test_sans_policy_fournie_le_recalcul_est_DECLARE():
    d = gate.admettre_transient(_transient())
    assert d["policy_source"] == "RECALCULEE", (
        "un recalcul a un cout (compteur du breaker) : il se declare")


# ── LE LIFECYCLE S'ARRETE A L'ADMISSION ────────────────────────────────────

def test_aucun_etat_au_dela_de_l_admission():
    d = gate.admettre_transient(_transient())
    interdits = {"DISPATCHED", "EXECUTING", "COMPLETED", "FAILED", "VERIFIED", "RETURNED"}
    assert d["decision"] not in interdits, (
        "GEN-3 produit un etat qui appartient a une generation ulterieure")
    assert "result" not in d and "evidence" not in d, (
        "GEN-3 n'execute rien : il ne peut donc porter ni resultat ni preuve")
