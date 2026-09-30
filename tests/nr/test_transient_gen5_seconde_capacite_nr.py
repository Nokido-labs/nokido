"""NR — GEN-5 : une SECONDE capacite deterministe, volontairement moins confortable.

GEN-4 avait prouve la boucle avec `forge_m2m_protocol.validate`, qui appartient
au Spine lui-meme. C'etait le bon premier pas, et c'etait aussi le plus facile :
le Spine validait son propre protocole. GEN-5 demande donc une capacite
EXTERIEURE, pour repondre a une question differente :

    le Spine sait-il executer autre chose que lui-meme ?

La capacite retenue est `forge_module_census.organ(name, fname, relpath)`, sur
mesure : deterministe (stable sur essais repetes), locale, 0,02 ms, sans LLM,
sans reseau, sans reservation, 0 `open(` / `write` / `subprocess` / `requests`
dans la fonction, et adossee a un gate CI reel (`anatomie`).

DEUX PIEGES QU'ELLE PORTE, et que ces tests figent :

1. APPELEE SANS CHEMIN, ELLE MENT PAR OMISSION. `organ("forge_m2m_protocol")`
   rend « ? non classe » : sans `fname`, elle ne peut pas lire la declaration
   `__FORGE_COLOR__` du fichier. Ce « non classe » serait alors un ARTEFACT
   D'APPEL, pas une mesure -- exactement le motif deja consigne dans
   RULES_SHARED (homonyme lu a la place du bon fichier, `relpath` absent).
   L'executor DOIT fournir le chemin.

2. ELLE A QUATRE FILETS. Carte explicite, mot-cle du nom, dossier, imports,
   puis declaration du module. Un verificateur independant ne peut donc trancher
   que si le module PORTE une declaration ; sinon il ne peut pas reconstruire le
   raisonnement, et `UNKNOWN` est la seule reponse honnete. Ne pas confondre
   « je ne peux pas verifier » avec « c'est faux ».

L'instrument ne se lit jamais lui-meme : les cibles de test sont d'AUTRES
modules que l'executor et que le census.
"""
from __future__ import annotations

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
mc = pytest.importorskip("forge_module_census")

# Cible EXTERIEURE a l'executor et au census : un module qui porte une
# declaration d'organe et que ni l'un ni l'autre n'ecrit.
CIBLE = "forge_m2m_protocol"
CIBLE_REL = "app/forge_m2m_protocol.py"


def _transient_census(module=CIBLE, relpath=CIBLE_REL, call_id="toolu_C1"):
    fname = os.path.join(RACINE, relpath.replace("/", os.sep))
    t = proto.normaliser_transient({
        "hook_event_name": "TRANSIENT", "transport": "interne",
        "session_id": "sess-gen5", "tool_use_id": call_id,
        "tool_name": "census.organ",
        "tool_input": {"module": module, "fname": fname, "relpath": relpath},
    })
    assert t is not None
    return t


# ── LA SECONDE CAPACITE EXISTE ET S'EXECUTE ────────────────────────────────

def test_la_seconde_capacite_est_reconnue_et_executee():
    t = _transient_census()
    res = executor.executer(t, gate.admettre_transient(t))
    assert res["status"] == "COMPLETED", res
    assert res["capability"] == "census.organ"
    assert res["result"]["organe"], "un organe doit etre rendu"


def test_l_executor_FOURNIT_le_chemin_sinon_il_mesure_un_artefact():
    """Sans `fname`, `organ` rend « non classe » : ce serait un artefact d'appel.

    On compare l'appel nu et l'appel complet sur la MEME cible : s'ils
    different, c'est que le chemin change le resultat, et l'executor doit donc
    le transmettre.
    """
    nu = mc.organ(CIBLE)
    complet = mc.organ(CIBLE, os.path.join(RACINE, CIBLE_REL.replace("/", os.sep)),
                       CIBLE_REL)
    t = _transient_census()
    res = executor.executer(t, gate.admettre_transient(t))
    assert res["result"]["organe"] == complet, (
        "l'executor doit rendre le resultat de l'appel COMPLET (%r), pas celui "
        "de l'appel nu (%r)" % (complet, nu))


# ── PREUVE INDEPENDANTE, ET SES LIMITES DECLAREES ──────────────────────────

def test_un_module_qui_DECLARE_son_organe_est_verifiable():
    t = _transient_census()
    res = executor.executer(t, gate.admettre_transient(t))
    verdict = executor.verifier(res)
    assert verdict["etat"] in (ev.SUPPORTED, ev.UNKNOWN, ev.CONTESTED), verdict
    assert verdict["verifie_par"] == "nokido"
    assert "declaration" in (verdict.get("recalcul") or "").lower()


def test_une_divergence_declaration_classement_donne_CONTESTED_pas_REJECTED():
    """Divergence REELLE, mesuree le 2026-09-17 sur `forge_m2m_protocol`.

        declare  : "snc/message_frame : validation des messages M2M..."
        classe   : "Cognition/Agentique/Raisonnement"

    Ce n'est PAS une erreur : la declaration est le DERNIER filet du census
    (carte, nom, dossier, imports, puis declaration), donc un filet anterieur
    l'emporte legitimement. Mais personne ne signalait l'ecart.

    REJETER serait faux -- les deux sources ont raison chacune dans son ordre.
    L'etat juste existe deja dans la couche a preuves : CONTESTED, « deux
    solutions prouvees : un contradicteur doit trancher, pas la majorite ».
    Ecraser l'une des deux aurait fait disparaitre le signal.
    """
    t = _transient_census()
    res = executor.executer(t, gate.admettre_transient(t))
    declare = executor._organe_declare(res["result"]["fname"])
    rendu = res["result"]["organe"]
    mot = declare.split("/")[0].split(":")[0].strip().lower()
    if mot in str(rendu).lower():
        pytest.skip("declaration et classement concordent sur cette cible")
    verdict = executor.verifier(res)
    assert verdict["etat"] == ev.CONTESTED, (
        "une divergence entre deux sources legitimes doit ressortir CONTESTED, "
        "jamais REJECTED : declare=%r rendu=%r -> %r" % (declare, rendu, verdict))


def test_l_extraction_de_la_declaration_ne_garde_pas_le_commentaire():
    """`DECL_RE` capture 90 caracteres : la valeur est suivie du commentaire.

    Sans coupure au guillemet fermant, « snc/... » devenait
    « snc/...\"  # organe declare le 2026-0 » -- une valeur polluee qui aurait
    fausse toute comparaison ulterieure.
    """
    fname = os.path.join(RACINE, CIBLE_REL.replace("/", os.sep))
    declare = executor._organe_declare(fname)
    assert declare, "la cible doit porter une declaration"
    assert "#" not in declare, "le commentaire de fin de ligne a ete conserve : %r" % declare
    assert not declare.endswith('"'), "le guillemet fermant a ete conserve : %r" % declare


def test_sans_declaration_lisible_le_verdict_est_UNKNOWN_et_non_REJECTED(tmp_path):
    """`organ` a QUATRE filets : un verificateur qui n'en lit qu'un ne peut pas
    conclure a l'erreur. « Je ne peux pas verifier » n'est pas « c'est faux »."""
    faux = tmp_path / "module_sans_declaration.py"
    faux.write_text("# aucun organe declare ici\nX = 1\n", encoding="utf-8")
    t = proto.normaliser_transient({
        "hook_event_name": "TRANSIENT", "transport": "interne",
        "session_id": "s", "tool_use_id": "toolu_C9", "tool_name": "census.organ",
        "tool_input": {"module": "module_sans_declaration", "fname": str(faux),
                       "relpath": "tmp/module_sans_declaration.py"}})
    res = executor.executer(t, gate.admettre_transient(t))
    verdict = executor.verifier(res)
    assert verdict["etat"] == ev.UNKNOWN, (
        "sans declaration lisible, le verificateur doit s'abstenir : %r" % verdict)


# ── LE DISPATCH CHOISIT, IL N'INVENTE PAS ──────────────────────────────────

def test_deux_capacites_et_le_dispatch_choisit_la_bonne():
    t_m2m = proto.normaliser_transient({
        "hook_event_name": "M2M", "transport": "m2m", "session_id": "s",
        "tool_use_id": "toolu_X1", "tool_name": "m2m.notify",
        "tool_input": {"channel": "notify",
                       "message": {"intent": "OK_DONE", "pointer_ref": "x"}}})
    t_cen = _transient_census(call_id="toolu_X2")
    assert executor.capacite_de(t_m2m) == "m2m.validate"
    assert executor.capacite_de(t_cen) == "census.organ"


def test_une_methode_inconnue_ne_recoit_AUCUNE_capacite():
    t = proto.normaliser_transient({
        "hook_event_name": "PreToolUse", "session_id": "s", "tool_use_id": "toolu_X3",
        "tool_name": "Bash", "tool_input": {"command": "echo"}})
    assert executor.capacite_de(t) is None
    res = executor.executer(t, gate.admettre_transient(t))
    assert res["status"] == "NO_CAPABILITY"


# ── CONCURRENCE MINIMALE ET IDEMPOTENCE ────────────────────────────────────

def test_deux_transients_independants_donnent_deux_executions():
    a = _transient_census(call_id="toolu_I1")
    b = _transient_census(module="forge_tool_gate", relpath="tools/forge_tool_gate.py",
                          call_id="toolu_I2")
    ra = executor.executer(a, gate.admettre_transient(a))
    rb = executor.executer(b, gate.admettre_transient(b))
    assert ra["execution_id"] != rb["execution_id"]
    assert ra["status"] == rb["status"] == "COMPLETED"


def test_le_meme_appel_source_garde_une_seule_execution():
    a = _transient_census(call_id="toolu_MEME")
    b = _transient_census(call_id="toolu_MEME")
    assert (executor.executer(a, gate.admettre_transient(a))["execution_id"]
            == executor.executer(b, gate.admettre_transient(b))["execution_id"])


# ── TOUJOURS AUCUN LLM, AUCUN RESEAU, AUCUNE RESERVATION ───────────────────

def test_la_seconde_capacite_ne_declenche_ni_LLM_ni_reservation(monkeypatch):
    vus = []
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: vus.append("reseau") or None)
    try:
        import forge_lane_admission as lane
        for nom in ("acquire", "admit", "check_ressources"):
            if hasattr(lane, nom):
                monkeypatch.setattr(lane, nom, lambda *a, **k: vus.append(nom) or {})
    except Exception:
        pass
    t = _transient_census(call_id="toolu_Z1")
    res = executor.executer(t, gate.admettre_transient(t))
    executor.verifier(res)
    assert vus == [], "GEN-5 a declenche %r" % vus
