"""NR — GEN-4 : premiere EXECUTION deterministe, et preuve INDEPENDANTE du resultat.

GEN-3 s'arretait a « admissible et adressable ». GEN-4 franchit une transition
de plus, et une seule :

    ACCEPTED -> DISPATCHED -> EXECUTING -> COMPLETED -> VERIFIED/REJECTED/UNKNOWN

La capacite choisie est `forge_m2m_protocol.validate(channel, payload)`. Elle
n'a pas ete retenue parce qu'elle serait impressionnante, mais parce qu'elle est
la seule mesuree a reunir : deterministe, locale, sans LLM, sans reseau, sans
reservation, sans ecriture (0 `open(`, 0 `write`, 0 `INSERT`), recalculable par
un tiers, et DEJA en production -- ses appelants reels sont `forge_mcp_registry`
(le hub, deux sites) et `forge_postal`.

CE QUE CE NR PROUVE VRAIMENT, et c'est tout l'enjeu :

    l'evidence n'est pas une copie du resultat de l'executor.

`validate` est FAIL-OPEN : catalogue illisible -> elle rend `M2M_OK` avec une
note `validator-error`. Un verificateur qui se contenterait de relire le code
rendu par l'executor validerait donc une PANNE. Le verificateur de GEN-4 relit
le catalogue et refait le controle LUI-MEME ; le test « source alteree » le
demontre en rendant le catalogue inexploitable APRES l'execution.

SEUIL DE VOIX. `arbitrer` exige 2 voix independantes par defaut, parce que la
redondance sert a contrer la VARIANCE DES MODELES. Un calcul deterministe n'a
pas de variance : une execution plus une verification independante suffisent.
On passe donc `min_voix=1` -- sans modifier `arbitrer`, dont c'est un parametre
prevu, et ce NR fige ce choix pour qu'il reste un choix et non un oubli.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (RACINE, os.path.join(RACINE, "app"), os.path.join(RACINE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

executor = pytest.importorskip("forge_transient_executor")
proto = pytest.importorskip("forge_m2m_protocol")
gate = pytest.importorskip("forge_tool_gate")
ev = pytest.importorskip("forge_swarm_evidence")


def _transient_m2m(message, canal="notify", call_id="toolu_M1"):
    """Un message M2M REEL devient un transient : la surface M2M est deja
    fonctionnelle, on l'OBSERVE sans la modifier."""
    t = proto.normaliser_transient({
        "hook_event_name": "M2M",
        "transport": "m2m",
        "session_id": "sess-gen4",
        "tool_use_id": call_id,
        "tool_name": "m2m.%s" % canal,
        "tool_input": {"channel": canal, "message": message},
    })
    assert t is not None
    return t


# ── LA CHAINE COMPLETE ─────────────────────────────────────────────────────

def test_succes_execution_reelle_puis_preuve_independante():
    t = _transient_m2m({"intent": "FACT_PROPOSED", "pointer_ref": "bb:zone/cle"})
    adm = gate.admettre_transient(t)
    assert adm["decision"] in ("ACCEPTED", "UNKNOWN"), adm

    res = executor.executer(t, adm)
    assert res["status"] == "COMPLETED", res
    assert res["capability"] == "m2m.validate"
    assert res["result"]["code"] == "M2M_OK"
    # l'identite traverse l'execution sans se perdre
    assert res["source_call_id"] == t["source_call_id"]
    assert res["correlation_id"] == t["correlation_id"]
    assert res["execution_id"], "une execution doit etre identifiable"

    verdict = executor.verifier(res)
    assert verdict["etat"] == ev.SUPPORTED, verdict
    assert verdict["verifie_par"] == "nokido", (
        "la preuve doit venir de Nokido, pas de la declaration de l'executor")


def test_payload_invalide_execution_reussie_mais_verdict_REJECTED():
    """L'execution ABOUTIT ; c'est son RESULTAT qui est negatif.

    Distinguer les deux est le contrat : un refus applicatif n'est pas une panne.
    """
    t = _transient_m2m({"intent": "FACT_PROPOSED"}, call_id="toolu_M2")  # pointer_ref manquant
    res = executor.executer(t, gate.admettre_transient(t))
    assert res["status"] == "COMPLETED", "l'executor a bien tourne"
    assert res["result"]["code"] == "M2M_ERR_MISSING_FIELD"
    verdict = executor.verifier(res)
    assert verdict["etat"] == ev.REJECTED, verdict


def test_la_preuve_n_est_PAS_une_copie_du_resultat_de_l_executor(monkeypatch):
    """LE test de GEN-4. `validate` est FAIL-OPEN.

    On execute normalement, puis on rend la source de verite inexploitable. Un
    verificateur qui recopierait le code de l'executor dirait encore « OK ». Le
    notre relit le catalogue, n'y trouve plus de quoi conclure, et s'abstient.
    """
    t = _transient_m2m({"intent": "FACT_PROPOSED", "pointer_ref": "bb:zone/cle"},
                       call_id="toolu_M3")
    res = executor.executer(t, gate.admettre_transient(t))
    assert res["result"]["code"] == "M2M_OK"

    # La source de verite devient illisible APRES l'execution.
    monkeypatch.setattr(proto, "_load_catalog", lambda: {})
    verdict = executor.verifier(res)
    assert verdict["etat"] in (ev.UNKNOWN, ev.REJECTED), (
        "le verificateur a recopie le verdict de l'executor au lieu de "
        "recalculer : %r" % verdict)
    assert "catalogue" in (verdict.get("motif") or "").lower() or verdict.get("raison")


# ── LE VERIFICATEUR APPLIQUE LE CONTRAT, PAS SA PROPRE REGLE ───────────────
# Piege paye en RUNTIME le 2026-09-17, et INVISIBLE aux tests precedents parce
# qu'ils n'utilisaient que des payloads structures. Sur 4 messages M2M REELS,
# deux sortaient REJECTED a tort : le verificateur traitait tout non-dict comme
# invalide, alors que le contrat TOLERE la prose courte (`prose_max_words`,
# code `M2M_OK_PROSE`). Un verificateur plus strict que le contrat qu'il verifie
# ne prouve que son opinion -- et il rejette du valide.

def test_la_prose_courte_toleree_par_le_contrat_n_est_pas_rejetee():
    t = _transient_m2m("ok recu", call_id="toolu_P1")
    res = executor.executer(t, gate.admettre_transient(t))
    assert res["result"]["code"] == "M2M_OK_PROSE"
    verdict = executor.verifier(res)
    assert verdict["etat"] == ev.SUPPORTED, (
        "le contrat tolere la prose courte : la rejeter serait appliquer une "
        "regle que le contrat ne porte pas -> %r" % verdict)
    assert verdict["accord_avec_executor"] is True


def test_la_prose_TROP_LONGUE_est_bien_refusee_des_DEUX_cotes():
    """Controle negatif : sans lui, un verificateur permissif passerait aussi."""
    t = _transient_m2m("mot " * 40, call_id="toolu_P2")
    res = executor.executer(t, gate.admettre_transient(t))
    assert res["result"]["code"] == "M2M_WARN_PROSE"
    verdict = executor.verifier(res)
    assert verdict["etat"] == ev.REJECTED
    assert verdict["accord_avec_executor"] is True, (
        "executor et verificateur doivent converger quand la regle est claire")


# ── CE QUE GEN-4 NE FAIT TOUJOURS PAS ──────────────────────────────────────

def test_aucun_LLM_et_aucun_reseau(monkeypatch):
    vus = []
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: vus.append("reseau") or None)
    import subprocess
    for nom in ("Popen", "run", "call", "check_output"):
        if hasattr(subprocess, nom):
            monkeypatch.setattr(subprocess, nom,
                                lambda *a, **k: vus.append("subprocess") or None)
    t = _transient_m2m({"intent": "OK_DONE", "pointer_ref": "x"}, call_id="toolu_M4")
    res = executor.executer(t, gate.admettre_transient(t))
    executor.verifier(res)
    assert vus == [], "GEN-4 a declenche %r ; aucun LLM ni reseau avant GEN-6" % vus


def test_aucune_reservation_de_lane(monkeypatch):
    """La capacite choisie est locale et instantanee : rien a reserver.

    `1 transient -> 1 reservation -> 1 release` n'est PAS la propriete de ce
    cliquet : elle le deviendra pour une capacite qui consomme reellement une
    ressource. Ici, reserver serait du ceremonial.
    """
    vus = []
    try:
        import forge_lane_admission as lane
        for nom in ("acquire", "admit", "check_ressources"):
            if hasattr(lane, nom):
                monkeypatch.setattr(lane, nom, lambda *a, **k: vus.append(nom) or {})
    except Exception:
        pass
    t = _transient_m2m({"intent": "OK_DONE", "pointer_ref": "x"}, call_id="toolu_M5")
    executor.executer(t, gate.admettre_transient(t))
    assert vus == [], "GEN-4 a touche a l'admission de ressource : %r" % vus


def test_un_transient_non_admis_n_est_JAMAIS_execute():
    t = _transient_m2m({"intent": "OK_DONE", "pointer_ref": "x"}, call_id="toolu_M6")
    refus = {"decision": "REJECTED", "reason": "refuse pour le test",
             "destination": "AUCUNE"}
    res = executor.executer(t, refus)
    assert res["status"] == "NOT_DISPATCHED", res
    assert "result" not in res or res.get("result") is None


def test_une_capacite_inconnue_n_est_pas_inventee():
    t = proto.normaliser_transient({
        "hook_event_name": "PreToolUse", "session_id": "s", "tool_use_id": "toolu_M7",
        "tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}})
    res = executor.executer(t, gate.admettre_transient(t))
    assert res["status"] == "NO_CAPABILITY", (
        "GEN-4 ne connait QU'UNE capacite ; toute autre doit ressortir sans "
        "etre executee : %r" % res)


# ── L'IDENTITE SURVIT A LA CHAINE ──────────────────────────────────────────

def test_deux_observations_du_meme_appel_ne_font_pas_deux_executions():
    """Double cablage mesure : meme `source_call_id`, deux observations.

    L'executor est idempotent PAR IDENTITE DE SOURCE, ce qui n'est pas un
    `dedupe()` global : deux appels legitimes distincts restent deux executions.
    """
    a = _transient_m2m({"intent": "OK_DONE", "pointer_ref": "x"}, call_id="toolu_SAME")
    b = _transient_m2m({"intent": "OK_DONE", "pointer_ref": "x"}, call_id="toolu_SAME")
    r1 = executor.executer(a, gate.admettre_transient(a))
    r2 = executer_meme = executor.executer(b, gate.admettre_transient(b))
    assert r1["execution_id"] == r2["execution_id"], (
        "deux observations du MEME appel doivent partager une execution")


def test_deux_appels_distincts_restent_deux_executions():
    a = _transient_m2m({"intent": "OK_DONE", "pointer_ref": "x"}, call_id="toolu_D1")
    b = _transient_m2m({"intent": "OK_DONE", "pointer_ref": "x"}, call_id="toolu_D2")
    r1 = executor.executer(a, gate.admettre_transient(a))
    r2 = executor.executer(b, gate.admettre_transient(b))
    assert r1["execution_id"] != r2["execution_id"], (
        "deux appels legitimes distincts ne doivent pas etre fusionnes")
