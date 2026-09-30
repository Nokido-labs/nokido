# -*- coding: utf-8 -*-
"""forge_m2m_protocol.py — Sprint 3 : validation des messages M2M inter-agents.

Source de verite = config/m2m_intents.json (draft AGY, revue CLAUDE). Un message
inter-agents (canaux notify / postal / task_result) doit etre un JSON portant
`intent` (ou alias `intent_code`) du dictionnaire + les champs requis du canal.
Prose libre toleree si <= prose_max_words (defaut 15) — au-dela : violation.

MODE (lu LIVE) : env LAFORGE_M2M_MODE ou marqueur sandbox/m2m_mode.txt.
  - warn (defaut)  : tout passe, violations annotees + event bus `m2m_violation`.
  - error/enforce  : les violations BLOQUENT (refus cote canal).

Verdicts (eux-memes des intent codes) : M2M_OK, M2M_OK_PROSE, M2M_WARN_PROSE,
M2M_ERR_UNKNOWN_INTENT, M2M_ERR_MISSING_FIELD, M2M_ERR_BAD_PAYLOAD.
Jamais d'exception vers l'appelant : fail-open (les canaux ne cassent pas).
"""
from __future__ import annotations

__FORGE_COLOR__ = "snc/message_frame : validation des messages M2M inter-agents"  # organe declare le 2026-09-06 (audit de raccordement)

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Tuple, Union

_ROOT = Path(__file__).resolve().parent.parent
_CATALOG = _ROOT / "config" / "m2m_intents.json"
_MODE_MARKER = _ROOT / "sandbox" / "m2m_mode.txt"

_cache = {"mtime": -1.0, "data": None}


def _load_catalog() -> Dict[str, Any]:
    try:
        st = _CATALOG.stat()
    except OSError:
        return {}
    if st.st_mtime != _cache["mtime"] or _cache["data"] is None:
        try:
            _cache["data"] = json.loads(_CATALOG.read_text(encoding="utf-8"))
        except Exception:
            _cache["data"] = {}
        _cache["mtime"] = st.st_mtime
    return _cache["data"] or {}


def mode() -> str:
    """warn (defaut) | error. Lu LIVE : env puis marqueur (toggle sans restart)."""
    m = (os.environ.get("LAFORGE_M2M_MODE", "") or "").strip().lower()
    if not m:
        try:
            if _MODE_MARKER.exists():
                m = _MODE_MARKER.read_text(encoding="utf-8").strip().lower()
        except Exception:
            m = ""
    return "error" if m in ("error", "enforce", "strict") else "warn"


# Champs qui portent de la PROSE destinee a un lecteur humain. Tout le reste
# (pointer_ref, ids, sha, payload, mesures, chemins) porte des DONNEES et echappe
# a la limite de mots, quelle que soit sa taille.
_CHAMPS_PROSE = frozenset({
    "content", "note", "notes", "detail", "details", "comment", "commentaire",
    "text", "texte", "message", "raison", "reason", "description", "resume",
    "summary", "critique", "explication", "proposed_action",
})


def _word_count(text: str) -> int:
    return len([w for w in str(text).split() if w.strip()])


# ═══════════════════════  IDENTITE ET INCARNATION  ═══════════════════════
#
# MESURE DU 2026-09-20 qui motive ce bloc :
#
#   `agent_messages` (21 852 lignes) porte `from_agent TEXT, to_agent TEXT` et
#   RIEN d'autre : aucune signature, aucun instance_id, aucun nonce. 24 sites
#   distincts font `INSERT INTO agent_messages` -- il n'existe AUCUN poseur
#   commun ou brancher une validation. Et `validate(channel, payload)` ne recoit
#   NI expediteur NI destinataire : il ne POUVAIT pas juger l'identite.
#
#   Consequence : `agt_agt_gemini` (DOUBLE prefixe `agt_`) a accumule
#   25 messages, `ANTIGRAVITY` 11 `pending` vieux de 89 jours pendant que
#   `agt_antigravity` etait drainee normalement. >= 48 messages non delivrables.
#
# L'ASYMETRIE CORRIGEE ICI :
#   a la PORTE (:8766)  TPM · DPoP (RFC 9449 §6) · bail 30 min · ring · fail-closed
#   a l'INTERIEUR (M2M) une ligne SQL avec un nom en texte libre
# Le hub authentifie fort QUI ENTRE, puis un message inter-agents n'etait qu'une
# ETIQUETTE. Une etiquette n'est pas une identite.
#
# DEUX NIVEAUX DISTINGUES (directive owner : « agy autonome n'est pas pareil
# qu'agy CLI ») : l'identite LOGIQUE est stable et declaree au SSoT ; l'INCARNATION
# (`instance_id` + `generation`) designe CETTE execution-ci. Sans elle, deux
# processus concurrents du meme agent sont indiscernables dans le journal.
#
# Garde : tests/nr/test_m2m_identite_et_incarnation_nr.py

import uuid as _uuid

# Stable pour toute la DUREE DU PROCESSUS, different d'un processus a l'autre :
# c'est exactement ce qu'on veut d'une incarnation. Un uuid regenere a chaque
# appel n'identifierait rien.
_INSTANCE_ID = _uuid.uuid4().hex[:16]
_REGISTRE_IDENT: Dict[str, Any] | None = None


def _registre_identites() -> Dict[str, Any]:
    """Charge le SSoT d'identite. MEME fichier que `claude_inbox_tick`.

    On ne construit PAS une seconde table : deux registres d'identite finiraient
    par diverger en silence, et c'est precisement le defaut qu'on corrige.
    """
    global _REGISTRE_IDENT
    if _REGISTRE_IDENT is not None:
        return _REGISTRE_IDENT
    _REGISTRE_IDENT = {}
    try:
        racine = Path(__file__).resolve().parent.parent
        brut = json.loads((racine / "config" / "agent_identities.json").read_text(
            encoding="utf-8", errors="replace"))
        reg = brut if isinstance(brut, dict) else {}
        if reg and not any(isinstance(v, dict) and "surface" in v for v in reg.values()):
            for v in reg.values():          # les entrees peuvent etre nichees
                if isinstance(v, dict) and any(
                        isinstance(w, dict) and "surface" in w for w in v.values()):
                    reg = v
                    break
        _REGISTRE_IDENT = reg
    except Exception:  # noqa: BLE001 - registre illisible : on ne devine pas
        _REGISTRE_IDENT = {}
    return _REGISTRE_IDENT


def _resoudre_agent(nom: Any) -> Tuple[str | None, str | None]:
    """(canonique, surface) d'un nom d'agent, ou (None, None) s'il est inconnu.

    DEUX PASSES, ET C'EST TOUT LE CORRECTIF. La version precedente testait, POUR
    CHAQUE entree, le nom canonique PUIS ses alias : la premiere qui matchait
    gagnait, meme par alias. La resolution dependait donc de l'ORDRE DE PARCOURS
    du dictionnaire -- un nom canonique pouvait perdre contre l'alias d'une autre
    entree rencontree plus tot.

    Mesure du 2026-09-20 : `LAFORGE_CLI` (acteur LAFORGE, ring 1) revendiquait
    `nokido_cli`, qui est l'identite de `NOKIDO_CLI` (acteur NOKIDO, ring 4).
    Selon l'ordre, un appelant se presentant comme `nokido_cli` pouvait obtenir
    le RING 1 -- une elevation de privilege latente. L'alias a ete retire du
    registre ; cette fonction cesse en plus d'etre sensible a l'ordre.

    ⚠️ J'AI ACCUSE LE REGISTRE A TORT DEUX FOIS AVANT DE LIRE SA STRUCTURE.
    `AGY` / `GEMINI` / `ANTIGRAVITY` partagent des alias, et c'est VOULU : les
    trois portent `actor = ANTIGRAVITY`, et le fichier le declare -- « un seul
    acteur, plusieurs noms, TOUS actifs ». Le registre modelisait deja la
    distinction ACTEUR / IDENTITE ; c'est ma resolution qui l'ignorait.
    146 identites pour 77 acteurs : le multi-nom est la regle, pas l'anomalie.
    """
    if not isinstance(nom, str) or not nom.strip():
        return None, None
    bas = nom.strip().lower()
    reg = _registre_identites()
    # PASSE 1 -- un nom CANONIQUE l'emporte toujours sur l'alias d'un autre.
    for canon, meta in reg.items():
        if isinstance(meta, dict) and canon.lower() == bas:
            return canon, meta.get("surface")
    # PASSE 2 -- alias seulement.
    for canon, meta in reg.items():
        if not isinstance(meta, dict):
            continue
        alias = meta.get("alias") or meta.get("aliases") or []
        if isinstance(alias, (list, tuple)) and any(str(a).lower() == bas for a in alias):
            return canon, meta.get("surface")
    return None, None


def acteur_de(nom: Any) -> str | None:
    """L'ACTEUR derriere une identite -- l'entite, pas le nom sous lequel elle parle.

    `actor` est le champ UNIVERSEL du registre (146/146), la ou `canonical`
    n'existe que sur 4 entrees. C'est donc lui qui dit si deux noms designent la
    meme entite : `AGY_CLI` et `AGY_HEADLESS` ont des identites distinctes et un
    acteur COMMUN (`ANTIGRAVITY`), ce qui est exactement la distinction que
    l'owner demande -- « agy autonome n'est pas pareil qu'agy CLI » -- sans en
    faire deux entites differentes.
    """
    canon, _s = _resoudre_agent(nom)
    if not canon:
        return None
    meta = _registre_identites().get(canon) or {}
    return meta.get("actor") or meta.get("same_actor") or canon


def valider_identites(from_agent: Any, to_agent: Any = None) -> Dict[str, Any]:
    """Verdict M2M sur l'expediteur et le destinataire. NE LEVE JAMAIS.

    OBSERVER AVANT D'ENFORCER : le verdict par defaut est un AVERTISSEMENT. 24
    chemins d'ecriture existent et un refus d'emblee les casserait tous --
    RULES_SHARED : « un gate neuf est non bloquant le temps de mesurer son
    bruit ». Le refus n'arrive que sous `LAFORGE_M2M_MODE=error`, le MEME
    interrupteur que la prose : on n'en cree pas un second.
    """
    try:
        cf, sf = _resoudre_agent(from_agent)
        ct, st = _resoudre_agent(to_agent) if to_agent is not None else (None, None)
        violations = []
        if isinstance(from_agent, str) and from_agent.strip() and cf is None:
            violations.append(
                "expediteur '%s' NON DECLARE au registre d'identite "
                "(personne ne draine cette forme)" % from_agent.strip()[:40])
        if isinstance(to_agent, str) and to_agent.strip() and ct is None:
            violations.append(
                "destinataire '%s' NON DECLARE au registre d'identite "
                "(le message n'arrivera nulle part)" % to_agent.strip()[:40])
        verdict = {
            "from": cf, "surface_from": sf,
            "to": ct, "surface_to": st,
        }
        if not violations:
            verdict["code"] = "M2M_OK_IDENTITE"
            return verdict
        verdict["violations"] = violations
        verdict["code"] = ("M2M_ERR_IDENTITE" if str(mode()).lower() == "error"
                           else "M2M_WARN_IDENTITE")
        return verdict
    except Exception as e:  # noqa: BLE001 - fail-open, comme `validate` juste en
        # dessous : un validateur qui leve COUPE la communication qu'il protege.
        return {"code": "M2M_OK_IDENTITE", "note": "validator-error: %s" % str(e)[:80]}


def incarnation(agent_id: Any) -> Dict[str, Any]:
    """{agent_id, instance_id, generation, surface, declare} de CETTE execution.

    « agy tourne » et « CETTE instance d'agy » sont deux affirmations
    differentes. `agent_id` est le nom CANONIQUE (stable, `agt_claude` et
    `CLAUDE` rendent le meme), `instance_id` designe ce processus-ci, et
    `generation` compte les incarnations successives.

    `agent_id` vaut None pour un nom inconnu : on ne fabrique pas une identite
    canonique a partir d'une etiquette que le registre ignore.
    """
    canon, surface = _resoudre_agent(agent_id)
    gen = 0
    if canon:
        try:
            racine = Path(__file__).resolve().parent.parent
            f = racine / "sandbox" / "m2m_generations.json"
            etat = {}
            if f.exists():
                etat = json.loads(f.read_text(encoding="utf-8", errors="replace")) or {}
            cle = "%s:%s" % (canon, _INSTANCE_ID)
            if cle in etat:
                gen = int(etat[cle])            # deja incarne dans CE processus
            else:
                gen = int(etat.get(canon, 0)) + 1
                etat[canon] = gen
                etat[cle] = gen
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(etat)[:200000], encoding="utf-8")
        except Exception:  # noqa: BLE001 - la generation est best-effort : une
            gen = 0        # incarnation sans compteur vaut mieux qu'une exception
    return {
        "agent_id": canon,
        "instance_id": _INSTANCE_ID,
        "generation": gen,
        "surface": surface,
        "declare": canon is not None,
    }


def _empreinte_contenu(payload: Any) -> str:
    """sha256 stable du CONTENU. MEME forme que `normaliser_transient` (prefixe
    `F-`, 16 caracteres) : on reprend le patron du canal `transient` plutot que
    d'en inventer un second qui divergerait."""
    try:
        if isinstance(payload, (dict, list, tuple)):
            brut = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        else:
            brut = str(payload)
    except Exception:  # noqa: BLE001
        brut = repr(payload)
    return "F-" + hashlib.sha256(brut.encode("utf-8", "replace")).hexdigest()[:16]


def sceller_message(payload: Any, from_agent: Any) -> Dict[str, Any]:
    """Scelle un message M2M : identite declaree + incarnation + empreinte.

    ⚠️ CE QUE CE SCEAU NE PROUVE PAS, et c'est ecrit dans le sceau lui-meme
    (`preuve_origine = False`).

    Un HMAC a SECRET PARTAGE ne fournit AUCUNE non-repudiation entre agents du
    meme hote : quiconque detient le secret peut signer au nom de n'importe qui.
    Une vraie preuve d'origine exige UNE CLE PAR AGENT (asymetrique) -- Nokido
    possede la cle TPM de la MACHINE, pas une cle par agent. Produire un HMAC et
    l'appeler « signature d'origine » serait exactement la faute que
    `forge_videur` nomme : « Invoquer une RFC qu'on n'implemente pas est une
    fausse garantie ». Un sceau qui ment sur sa portee est PIRE que pas de sceau,
    parce qu'on cesse de se mefier.

    CE QU'IL PROUVE, et rien de plus :
      INTEGRITE    le contenu n'a pas ete altere entre emission et lecture
      INCARNATION  quelle execution a produit ce message (instance_id, generation)
      IDENTITE DECLAREE  le nom canonique, resolu au SSoT -- jamais fabrique

    CE QU'IL FAUDRAIT POUR L'ORIGINE, dit ici pour que le chantier ne se perde
    pas : une paire de cles par agent, la publique au registre d'identite, et
    `forge_integrity.CapabilityToken` (qui porte deja DPoP `jkt` et l'empreinte
    de certificat) comme transport de la preuve. C'est un geste OWNER : il touche
    le registre, les rings et la distribution de cles.

    Garde : tests/nr/test_m2m_sceau_integrite_nr.py
    """
    try:
        inc = incarnation(from_agent)
        return {
            "agent_id": inc.get("agent_id"),
            "instance_id": inc.get("instance_id"),
            "generation": inc.get("generation"),
            "surface": inc.get("surface"),
            "declare": inc.get("declare"),
            "content_fingerprint": _empreinte_contenu(payload),
            "scelle_a": int(time.time()),
            # Champ NON DECORATIF : il interdit de lire ce sceau comme une
            # authentification. Un NR le verrouille.
            "preuve_origine": False,
            "portee": "integrite+incarnation (PAS d'authentification d'origine : "
                      "secret partage, pas de cle par agent)",
        }
    except Exception as e:  # noqa: BLE001 - fail-open : sceller ne casse jamais
        return {"preuve_origine": False, "note": "sceau-error: %s" % str(e)[:80]}


def verifier_sceau(payload: Any, sceau: Any) -> Dict[str, Any]:
    """Recalcule l'empreinte et la compare. Rend {intact, code, ...}.

    `intact=None` quand il n'y a PAS de sceau : une absence n'est pas une
    alteration. `UNKNOWN != NO` -- c'est l'invariant du depot, et le confondre
    ici transformerait tous les messages anterieurs en messages « alteres ».
    """
    try:
        if not isinstance(sceau, dict) or not sceau.get("content_fingerprint"):
            return {"intact": None, "code": "M2M_SCEAU_INCONNU",
                    "note": "aucun sceau : ni intact ni altere, INDETERMINE"}
        attendu = _empreinte_contenu(payload)
        ok = attendu == sceau.get("content_fingerprint")
        return {
            "intact": ok,
            "code": "M2M_SCEAU_OK" if ok else "M2M_SCEAU_ALTERE",
            "attendu": attendu,
            "recu": sceau.get("content_fingerprint"),
            "agent_id": sceau.get("agent_id"),
            "instance_id": sceau.get("instance_id"),
            "preuve_origine": False,
        }
    except Exception as e:  # noqa: BLE001 - fail-open
        return {"intact": None, "code": "M2M_SCEAU_INCONNU",
                "note": "verif-error: %s" % str(e)[:80]}


def validate(channel: str, payload: Union[str, dict, None]) -> Dict[str, Any]:
    """Valide un payload M2M. Retourne un verdict M2M (jamais d'exception)."""
    try:
        cat = _load_catalog()
        intents = cat.get("intents") or {}
        rules = cat.get("schema_rules") or {}
        max_words = int(rules.get("prose_max_words", 15))
        required = (rules.get("required_fields_by_channel") or {}).get(str(channel), [])

        data = payload
        if isinstance(payload, str):
            s = payload.strip()
            if s.startswith("{"):
                try:
                    data = json.loads(s)
                except Exception:
                    data = payload  # prose qui ressemble a du JSON casse
        if data is None:
            return {"code": "M2M_ERR_BAD_PAYLOAD", "violations": ["payload vide"]}

        # ── Prose libre (legacy) : toleree si courte ─────────────────────────
        if not isinstance(data, dict):
            n = _word_count(str(data))
            if n <= max_words:
                return {"code": "M2M_OK_PROSE", "words": n}
            return {"code": "M2M_WARN_PROSE", "words": n, "max_words": max_words,
                    "violations": [f"prose {n} mots > {max_words} — utiliser un intent du dictionnaire"]}

        # ── Message M2M structure ────────────────────────────────────────────
        code = data.get("intent") or data.get("intent_code") or ""
        violations = []
        if not code:
            violations.append("champ intent/intent_code absent")
        elif intents and code not in intents:
            return {"code": "M2M_ERR_UNKNOWN_INTENT", "intent": str(code)[:40],
                    "violations": [f"intent '{code}' hors dictionnaire v{cat.get('version', '?')}"]}
        for f in required:
            if f in ("intent", "intent_code"):
                continue
            if f not in data:
                violations.append(f"champ requis manquant: {f}")
        # La limite ne vise pas le VOLUME, elle vise la PROSE : le contrat M2M est
        # {intent, pointer_ref} vers le SSoT, jamais une lettre. ANTIGRAVITY l'a
        # retiree le 2026-08-28 pour une raison juste — elle frappait aussi les
        # champs de DONNEES, ou un pointer_ref, une liste d'ids ou un JSON de
        # mesures depassent 15 mots sans etre de la prose.
        #
        # Mais le retrait TOTAL laissait un contournement immediat : il suffisait
        # d'emballer sa prose dans {"intent": ..., "content": "<600 mots>"} pour
        # que le garde se taise sur la totalite du message. C'est precisement le
        # chemin qu'avait pris mon propre message du jour, celui qui a fait crier
        # le garde — le remede etait d'ecrire court, pas de retirer la mesure.
        #
        # Donc : la limite s'applique aux champs de PROSE, et seulement a eux.
        # Liste POSITIVE volontaire : un champ inconnu est presume porter des
        # DONNEES et n'est pas signale. Un garde qui crie a faux se fait desarmer,
        # et c'est exactement ce qui venait d'arriver a celui-ci.
        for k, v in data.items():
            if k not in _CHAMPS_PROSE or not isinstance(v, str):
                continue
            n_mots = _word_count(v)
            if n_mots > max_words:
                violations.append(f"champ '{k}': {n_mots} mots > {max_words}")
        if violations:
            c = "M2M_ERR_MISSING_FIELD" if any("manquant" in v or "absent" in v for v in violations) else "M2M_WARN_PROSE"
            return {"code": c, "intent": str(code)[:40], "violations": violations}
        return {"code": "M2M_OK", "intent": str(code)[:40]}
    except Exception as e:  # fail-open : la validation ne casse jamais un canal
        return {"code": "M2M_OK", "note": f"validator-error: {str(e)[:80]}"}


# ── Transient : observer une intention SANS toucher a son chemin ────────────
# GEN-1 du Transient Spine. Le contrat vit ICI et nulle part ailleurs : le depot
# s'interdit un 3e protocole, et `m2m_intents.json` portait deja un schema
# versionne avec des champs requis par canal. Le transient est donc un CANAL de
# plus, pas un dictionnaire concurrent.
_SCHEMA_TRANSIENT = "nokido.transient.v1"

# Surfaces MESUREES le 2026-09-17 (docs/transient_surface_matrix.md). Une entree
# ici dit « cette surface a ete vue », JAMAIS « on sait la capturer » :
#     EXISTE != CAPTURABLE != REJOUABLE != REINJECTABLE.
_SURFACES = {
    "claude": "claude_code",
    "gemini": "gemini_cli",
    "codex": "codex_cli",
    "antigravity": "antigravity",
}


def _transport_observe(ev: dict) -> str:
    """Le transport est une DIMENSION mesuree, jamais deduite du client.

    Un meme client parle par plusieurs transports : Gemini adresse le hub en
    HTTP `/mcp` ET porte des hooks locaux. Lire le transport dans le nom du
    client FABRIQUERAIT une valeur. On lit donc un indice STRUCTUREL de
    l'evenement lui-meme, et a defaut on rend `UNKNOWN` -- jamais une supposition.
    """
    declare = ev.get("transport")
    if isinstance(declare, str) and declare:
        return declare  # l'appelant sait : sa declaration fait autorite
    if ev.get("session_id") or ev.get("transcript_path"):
        return "hook"   # charge utile d'un hook local recue sur stdin
    if ev.get("http_path") or ev.get("headers"):
        return "http"
    return "UNKNOWN"


def normaliser_transient(evenement: Union[dict, None]) -> Union[dict, None]:
    """Rend un transient `nokido.transient.v1`, ou None. **N'EXECUTE RIEN.**

    GEN-1 observe et normalise, sans modifier le comportement existant : aucun
    processus lance, aucune socket ouverte, ni le routeur de swarm ni la couche
    a preuves ne sont appeles. Une couche d'observation qui agit n'est plus une
    observation -- c'est ce que verrouille le NR.

    Ne leve jamais : une normalisation qui casserait l'appel qu'elle observe
    reproduirait le defaut du garde RSS mort sur son propre journal (2026-09-06).

    Verrouille par tests/nr/test_transient_gen1_observation_nr.py.
    """
    try:
        ev = evenement or {}
        if not isinstance(ev, dict):
            return None
        methode = str(ev.get("tool_name") or ev.get("tool") or ev.get("method") or "")
        if not methode:
            return None
        cli = str(ev.get("cli") or ev.get("producer") or "").lower()
        surface = _SURFACES.get(cli, "UNKNOWN")
        transport = _transport_observe(ev)
        charge = ev.get("tool_input") or ev.get("args") or ev.get("payload") or {}
        session = ev.get("session_id") or ev.get("transcript_path") or ""
        # ── IDENTITE (GEN-2.1) : TROIS notions DISTINCTES ─────────────────
        # Les confondre a un cout MESURE. Le 2026-09-17, un hash unique de
        # (session, methode, charge) a fusionne 2 appels x 2 cablages en UNE
        # seule identite : plus moyen d'y distinguer une duplication accidentelle
        # d'une repetition legitime.
        #   source_call_id       ce que la SOURCE fournit (`tool_use_id`, mesure
        #                        du 2026-09-17 sur l'evenement reel). Deux
        #                        observations d'un MEME appel le partagent ; deux
        #                        appels distincts en portent deux. C'est ce qui
        #                        separe « 1 appel + 2 cablages » de « 2 appels ».
        #   content_fingerprint  le CONTENU de l'intention, sans session ni
        #                        occurrence. Deux appels identiques legitimes le
        #                        partagent -- c'est voulu, pas un defaut.
        #   correlation_id       la session, pour rattacher les observations.
        call_id = ev.get("tool_use_id") or ev.get("call_id") or ""
        empreinte = hashlib.sha256(
            ("%s|%s" % (methode,
                        json.dumps(charge, sort_keys=True, ensure_ascii=False)[:512])
             ).encode("utf-8")).hexdigest()[:16]
        if call_id:
            ident = hashlib.sha256(str(call_id).encode("utf-8")).hexdigest()[:16]
        else:
            # Repli DECLARE, jamais silencieux : sans identifiant de source, deux
            # appels identiques dans une meme session sont indiscernables. On le
            # dit par `source_call_id = UNKNOWN` au lieu d'inventer une occurrence.
            ident = hashlib.sha256(
                ("%s|%s" % (session, empreinte)).encode("utf-8")).hexdigest()[:16]
        connu = (surface != "UNKNOWN") and (transport != "UNKNOWN")
        return {
            "schema": _SCHEMA_TRANSIENT,
            "intent": "TRANSIENT_OBSERVED",
            "id": "T-" + ident,
            "source_call_id": str(call_id) if call_id else "UNKNOWN",
            "content_fingerprint": "F-" + empreinte,
            "correlation_id": session or "UNKNOWN",
            "observed_at": time.time(),
            "source": {
                "surface": surface,
                # Mesure du 2026-09-17 : AUCUN des 11 champs de l'evenement reel
                # ne nomme le client. Le gate resout `cli` par DEFAUT a "claude",
                # mais un defaut de configuration n'est pas une observation --
                # d'ou UNKNOWN, accompagne de sa raison.
                "surface_resolution": ("OBSERVEE" if surface != "UNKNOWN"
                                       else "ABSENTE_DE_LA_SOURCE"),
                "transport": transport,
                "producer": (ev.get("agent") or cli or "UNKNOWN").upper(),
                "signal": (ev.get("hook_event_name") or ev.get("event")
                           or ev.get("signal") or "PreToolUse"),
                "method": methode,
                # GEN-2.1 : les NOMS des champs fournis par la source, jamais
                # leurs valeurs. C'est la seule facon de repondre par la MESURE a
                # deux questions ouvertes -- la source fournit-elle un identifiant
                # d'appel unique, et fournit-elle un identifiant de client ? --
                # sans fabriquer ni l'un ni l'autre. Conserver la liste permet en
                # outre une resolution ULTERIEURE : un champ qu'on ne sait pas
                # encore lire reste nomme au lieu d'etre perdu.
                "champs_bruts": sorted(str(k) for k in ev.keys()),
            },
            "payload": charge,
            "provenance": {
                "session": session or "UNKNOWN",
                # Sans profondeur, une boucle de spawn est indetectable : un
                # worker qui redemanderait une tache relancerait la chaine.
                "depth": int(ev.get("depth") or 0),
                "parent": ev.get("parent_transient"),
            },
            "observation": "CAPTURED" if connu else "UNKNOWN",
            # GEN-1 n'a le droit de rien changer, et le DIT dans son artefact :
            # sans ce champ, une observation ne se distingue pas d'une interception.
            "effect": "UNCHANGED",
        }
    except Exception:  # noqa: BLE001  # muet-ok : l'observation ne casse jamais l'observe
        return None


def check(channel: str, payload: Union[str, dict, None]) -> Tuple[bool, Dict[str, Any]]:
    """(allow, verdict). allow=False UNIQUEMENT en mode error avec violations.
    En warn : event bus `m2m_violation` (observabilite 0-token) et on laisse passer."""
    v = validate(channel, payload)
    # Compter AUSSI les conformes : le bus ne publiait que les violations, donc
    # on avait un numerateur sans denominateur (2836 violations sur deux mois,
    # sur un total inconnu). Sans taux, on ne peut pas armer le mode `error`
    # sans risquer de rendre le corps muet. Observation seule : aucun verdict
    # n'est modifie ici.
    try:
        from nokido_agent.app.forge_m2m_conformance import noter as _noter

        _noter(channel, v)
    except Exception:  # muet-ok : un compteur ne casse jamais un canal
        pass
    bad = v.get("code") not in ("M2M_OK", "M2M_OK_PROSE")
    if bad:
        try:
            from nokido_agent.app.forge_swarm_bus import publish

            publish("m2m_violation", {"channel": channel, **{k: v[k] for k in ("code", "intent", "words") if k in v}},
                    topic="m2m")
        except Exception:
            pass
        if mode() == "error":
            return False, v
    return True, v


# --------------------------------------------------------------------------
# Statut APPLICATIF d'un resultat de tache -- a ne pas confondre avec le statut
# de TRANSPORT. Mesure du 2026-09-08 dans sandbox/tasks.db : 35 taches « done »
# dont QUATRE portaient {"intent": "ERR_INTERNAL", "status_code": "FAILURE"}.
# L'ecrivain posait `status='done'` des qu'une reponse revenait, sans jamais
# regarder son contenu : « le message est revenu » n'est pas « le travail a
# reussi ». Verrouille par tests/nr/test_statut_tache_transport_vs_applicatif_nr.
# --------------------------------------------------------------------------

_CODES_ECHEC = ("FAILURE", "FAILED", "ERROR", "KO")
_CODES_SUCCES = ("SUCCESS", "OK")


def _codes_erreur() -> set:
    """Les intents de la categorie `error`, LUS AU CATALOGUE.

    Jamais une liste ecrite en dur : un intent d'erreur ajoute au dictionnaire
    doit etre reconnu sans qu'on retouche ce module.
    """
    codes = set()
    intents = (_load_catalog() or {}).get("intents") or {}
    for cle, valeur in intents.items():
        if not isinstance(valeur, dict):
            continue
        if cle == "error":
            codes.update(k for k in valeur if isinstance(k, str))
        elif str(valeur.get("category")) == "error":
            codes.add(cle)
    return codes


def statut_depuis_resultat(brut) -> str:
    """Rend `echec`, `succes` ou `inconnu` pour un resultat de tache.

    TROIS etats, jamais deux, et classement par liste BLANCHE : n'est ECHEC que
    ce qui est PROUVE en echec. Un resultat en texte libre -- le cas majoritaire,
    les reponses d'un fournisseur cloud -- reste INCONNU. Poser l'inverse
    fabriquerait des pannes fictives, defaut symetrique consigne le 2026-07-30
    (24 pouls sans pid lus comme 24 pannes).

    Le consommateur decide quoi en faire : ici on se contente de NOMMER l'etat.
    """
    if not brut or not isinstance(brut, str):
        return "inconnu"
    texte = brut.strip()
    if not texte.startswith("{"):
        return "inconnu"
    try:
        charge = json.loads(texte)
    except (ValueError, TypeError):
        return "inconnu"
    if not isinstance(charge, dict):
        return "inconnu"

    code = str(charge.get("status_code") or "").strip().upper()
    intent = str(charge.get("intent") or charge.get("intent_code") or "").strip()

    if code in _CODES_ECHEC or intent in _codes_erreur():
        return "echec"
    if code in _CODES_SUCCES:
        return "succes"
    return "inconnu"
