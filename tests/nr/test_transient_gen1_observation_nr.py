"""NR — GEN-1 du Transient Spine : OBSERVER sans rien changer.

GEN-1 repond a une seule question, et n'a le droit de rien faire d'autre :

    « Lorsqu'une intention apparait sur une surface deja existante, peut-on en
      produire une representation Transient exploitable localement, SANS alterer
      le chemin actuel ? »

Ce NR verrouille les DEUX moities de cette phrase. La premiere est facile a
tester et facile a croire ; c'est la seconde qui compte, parce qu'une couche
d'observation qui se met a agir est exactement la facon dont un garde devient un
point de fragilite.

CE QUI EST INTERDIT A GEN-1, et que ces tests font echouer :
  - modifier la decision de `forge_tool_gate` (le refus des sous-agents reste) ;
  - declencher une execution (subprocess, reseau, appel au swarm) ;
  - creer un second protocole a cote de `config/m2m_intents.json` v1.3.0 ;
  - toucher au chemin M2M autonome, qui FONCTIONNE et n'est pas ce qu'on repare.

NOTE DE MESURE, 2026-09-17. Une version anterieure de l'analyse M2M concluait
que 73 a 78 % des messages de tache n'etaient jamais lus, et allait en tirer une
exigence d'ACK pour le Spine. C'ETAIT UN ARTEFACT : `status` n'est pas un capteur
de lecture (84 % des `read` sans `read_at`) et 93 % des `unread` visaient une
destination d'ARCHIVAGE. Aucune exigence fonctionnelle de GEN-1 ne doit deriver
de ces chiffres — une fausse mesure fabrique une fausse contrainte d'architecture.
"""
from __future__ import annotations

import io
import json
import os
import sys

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (RACINE, os.path.join(RACINE, "app"), os.path.join(RACINE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

proto = pytest.importorskip("forge_m2m_protocol")


def _evenement_task():
    """L'evenement REEL tel que le hook le recoit sur stdin."""
    return {
        "cli": "claude",
        "session_id": "sess-gen1",
        "agent": "CLAUDE",
        "tool_name": "Task",
        "tool_input": {"subagent_type": "Explore",
                       "description": "recon des appelants",
                       "prompt": "cherche qui appelle X"},
    }


# ── 1. l'observation produit un transient exploitable ──────────────────────

def test_une_intention_observable_devient_un_transient():
    t = proto.normaliser_transient(_evenement_task())
    assert t is not None, "aucun transient produit pour un evenement Task"
    assert t.get("schema") == "nokido.transient.v1"


def test_le_transient_porte_source_transport_et_provenance_separement():
    """Le transport est une DIMENSION, jamais deduit du client."""
    t = proto.normaliser_transient(_evenement_task())
    src = t.get("source") or {}
    for champ in ("surface", "transport", "producer", "signal", "method"):
        assert champ in src, "champ de source manquant : %s" % champ
    assert src["transport"] == "hook", "le transport doit etre MESURE, pas deduit"
    prov = t.get("provenance") or {}
    assert "session" in prov and "depth" in prov, (
        "sans profondeur ni session, une boucle de spawn est indetectable")
    assert prov["depth"] == 0, "un transient issu du client est a la profondeur 0"


def test_le_transient_dit_qu_il_n_a_RIEN_change():
    t = proto.normaliser_transient(_evenement_task())
    assert t.get("effect") == "UNCHANGED", (
        "GEN-1 observe ; un transient qui ne declare pas son innocuite ne peut "
        "pas etre distingue d'une interception active")
    assert t.get("observation") in ("CAPTURED", "UNKNOWN")


def test_une_surface_inconnue_rend_UNKNOWN_et_jamais_un_transient_invente():
    t = proto.normaliser_transient({"cli": "surface-jamais-vue", "tool_name": "Xyz"})
    assert t is None or (t.get("source") or {}).get("transport") == "UNKNOWN", (
        "une surface non mesuree doit rester UNKNOWN, jamais etre devinee")


# ── 2. le contrat est ETENDU, pas duplique ─────────────────────────────────

def test_le_contrat_m2m_reste_compatible_v1_3_0():
    """Les 25 intents et les 4 canaux de v1.3.0 survivent a l'extension."""
    cat = proto._load_catalog()
    intents = cat.get("intents") or {}
    canaux = (cat.get("schema_rules") or {}).get("required_fields_by_channel") or {}
    for code in ("SCOPE_SET", "OK_DONE", "ERR_TEST_FAIL", "FACT_PROPOSED",
                 "REVIEW_OK", "NEED_HUMAN_APPROVAL", "AUTHZ_OBSERVATION"):
        assert code in intents, "intent v1.3.0 disparu : %s" % code
    for canal in ("notify", "postal", "task_assign", "task_result"):
        assert canal in canaux, "canal v1.3.0 disparu : %s" % canal
    assert "intent" in canaux["notify"] and "pointer_ref" in canaux["notify"]


def test_le_canal_transient_est_declare_dans_le_contrat_existant():
    """Pas de schema concurrent : le transient est un CANAL de plus."""
    cat = proto._load_catalog()
    canaux = (cat.get("schema_rules") or {}).get("required_fields_by_channel") or {}
    assert "transient" in canaux, (
        "le canal transient doit vivre dans config/m2m_intents.json, pas dans un "
        "second dictionnaire — le depot s'interdit deja un 3e protocole")


def test_un_transient_valide_passe_le_validateur_existant():
    t = proto.normaliser_transient(_evenement_task())
    v = proto.validate("transient", t)
    assert v.get("code") in ("M2M_OK", "M2M_OK_PROSE"), (
        "le transient produit doit satisfaire le validateur du contrat : %s" % v)


# ── GEN-2.1 : IDENTITE — occurrence, contenu, correlation ──────────────────
# Mesure du 2026-09-17 sur l'evenement REEL (noms de champs seuls, jamais les
# valeurs). La source fournit 11 champs :
#   cwd · effort · hook_event_name · permission_mode · prompt_id ·
#   scratchpad_dir · session_id · tool_input · tool_name · tool_use_id ·
#   transcript_path
# Deux consequences, et elles tranchent les deux inconnues de GEN-2 :
#   1. `tool_use_id` EXISTE -> c'est l'identifiant d'APPEL fourni par la source.
#      On ne fabrique donc aucun call id : on lit le sien.
#   2. AUCUN champ ne nomme le client. `surface` reste UNKNOWN, et le rester est
#      la reponse JUSTE -- le gate resout `cli` par DEFAUT a "claude", mais un
#      defaut de configuration n'est pas une observation.

def _ev(tool_use_id=None, description="recon", avec_source=True):
    ev = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-identite",
        "tool_name": "Task",
        "tool_input": {"subagent_type": "Explore", "description": description},
    }
    if avec_source:
        ev["tool_use_id"] = tool_use_id or "toolu_A"
    return ev


def test_cas_A_un_appel_unique_porte_l_identifiant_de_la_source():
    t = proto.normaliser_transient(_ev(tool_use_id="toolu_A"))
    assert t["source_call_id"] == "toolu_A", (
        "l'identifiant d'appel doit venir de la SOURCE, pas d'une fabrication")
    assert t["content_fingerprint"].startswith("F-")
    assert t["correlation_id"] == "sess-identite"


def test_cas_B_deux_appels_identiques_ont_DEUX_identites():
    """Meme contenu n'est pas meme occurrence.

    Sans cela, deux lectures legitimes du meme fichier seraient fusionnees en
    une, et un consommateur en aval croirait avoir tout traite.
    """
    a = proto.normaliser_transient(_ev(tool_use_id="toolu_A"))
    b = proto.normaliser_transient(_ev(tool_use_id="toolu_B"))
    assert a["source_call_id"] != b["source_call_id"]
    assert a["id"] != b["id"], "deux appels distincts doivent porter deux identites"
    assert a["content_fingerprint"] == b["content_fingerprint"], (
        "le contenu est le MEME : le fingerprint doit le dire")


def test_cas_C_double_cablage_meme_appel_meme_identite():
    """Deux observations du MEME appel : meme identite, et le doublon RESTE visible.

    Mesure du 2026-09-17 : `forge_tool_gate` est cable DEUX FOIS (settings
    utilisateur + settings local du projet), donc un appel produit deux
    observations. C'est une anomalie de CONFIGURATION, pas une propriete du
    Spine -- le Spine doit la rendre identifiable, jamais l'absorber.
    """
    a = proto.normaliser_transient(_ev(tool_use_id="toolu_A"))
    b = proto.normaliser_transient(_ev(tool_use_id="toolu_A"))
    assert a["source_call_id"] == b["source_call_id"] == "toolu_A"
    assert a["id"] == b["id"], "deux observations d'un meme appel = une identite"
    assert a["content_fingerprint"] == b["content_fingerprint"]


def test_aucune_deduplication_silencieuse():
    """Le normaliseur RESTITUE chaque observation : il n'en avale aucune.

    Un `dedupe()` pose ici masquerait le double cablage au lieu de l'exposer.
    """
    obs = [proto.normaliser_transient(_ev(tool_use_id="toolu_A")) for _ in range(3)]
    assert all(o is not None for o in obs), (
        "une observation a ete avalee : le Spine ne doit pas dedupliquer en silence")


def test_sans_identifiant_de_source_l_absence_est_DECLAREE():
    """UNKNOWN explicite, jamais un identifiant invente."""
    t = proto.normaliser_transient(_ev(avec_source=False))
    assert t["source_call_id"] == "UNKNOWN", (
        "sans identifiant fourni, on declare UNKNOWN -- on n'en fabrique pas")
    assert t["content_fingerprint"], "le fingerprint de contenu reste calculable"


def test_la_surface_absente_reste_UNKNOWN_et_dit_pourquoi():
    t = proto.normaliser_transient(_ev())
    src = t["source"]
    assert src["surface"] == "UNKNOWN", (
        "aucun des 11 champs de la source ne nomme le client : inventer "
        "`claude` transformerait un defaut du gate en observation")
    assert src.get("surface_resolution") == "ABSENTE_DE_LA_SOURCE"


def test_le_signal_vient_du_champ_reel_et_non_d_un_defaut():
    t = proto.normaliser_transient(_ev())
    assert t["source"]["signal"] == "PreToolUse"
    ev = _ev()
    ev["hook_event_name"] = "PostToolUse"
    assert proto.normaliser_transient(ev)["source"]["signal"] == "PostToolUse", (
        "le signal doit etre LU dans hook_event_name, pas suppose")


# ── 3. GEN-1 N'EXECUTE RIEN — c'est le test qui compte ─────────────────────

def test_la_normalisation_ne_declenche_aucune_execution(monkeypatch):
    """Espionne les portes de sortie : subprocess, reseau, swarm."""
    appels = []

    import subprocess
    for nom in ("Popen", "run", "call", "check_output"):
        if hasattr(subprocess, nom):
            monkeypatch.setattr(subprocess, nom,
                                lambda *a, **k: appels.append("subprocess") or None)
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: appels.append("reseau") or None)

    proto.normaliser_transient(_evenement_task())
    assert appels == [], (
        "GEN-1 a declenche une execution : %r. Une couche d'observation qui agit "
        "n'est plus une observation." % appels)


def test_le_gate_refuse_toujours_les_sous_agents(capsys):
    """Le comportement EXISTANT ne bouge pas. Chemin reel : main() sur stdin."""
    gate = pytest.importorskip("forge_tool_gate")
    stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps(_evenement_task()))
    try:
        rc = gate.main()
    finally:
        sys.stdin = stdin
    assert rc == 0
    sortie = capsys.readouterr().out
    assert sortie.strip(), "le gate doit toujours emettre sa decision"
    d = json.loads(sortie.strip().splitlines()[-1])
    texte = json.dumps(d, ensure_ascii=False).lower()
    assert "deny" in texte or "refus" in texte or "block" in texte, (
        "le refus des sous-agents a disparu : GEN-1 a modifie le comportement, "
        "ce qui lui est explicitement interdit. Sortie : %s" % texte[:300])
