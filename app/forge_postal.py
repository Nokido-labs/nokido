#!/usr/bin/env python3
"""forge_postal.py — système postal souverain Nokido : FACTEUR (livraison) + SECRÉTAIRE
(relève) par CANAL, courrier RICHE + cycle de vie avec ACCUSÉS + dédup anti-triplication.

Né du test conv-autonome CLAUDE<->GEMINI (2026-06-11) qui a révélé : triplication (0 dédup)
+ modèle consume confus (poll vide après le daemon). Spec user : le courrier comprend
QUI envoie / COMMENT / À QUI / RÉPONSE-À-QUI / COMMENT ; 1 facteur + 1 secrétaire par canal,
faisant office d'accusé de LIVRAISON, d'acheminement (réussi / en gare de triage) et de
accusé de RÉCEPTION.

Cycle de vie d'un courrier :
  queued (EN GARE DE TRIAGE) --facteur--> delivered (ACCUSÉ DE LIVRAISON, dans l'inbox)
                                          --secrétaire+lecture--> acked (ACCUSÉ DE RÉCEPTION)
  (échec de livraison -> reste queued, attempts++ ; cap -> dead-letter)

Réutilise : registre identité×canal (#7-10 config/agent_identities.json) pour valider
canaux/ring. DB dédiée mono-writer WAL (comme forge_swarm_blackboard) -> 0 conflit.
agent_messages/notify = transport optionnel ; ICI le store EST la source de vérité (l'agent
lit via secretaire(), pas via poll -> plus de triplication).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "postal.db"
MAX_ATTEMPTS = int(os.environ.get("POSTAL_MAX_ATTEMPTS", "20"))
AUTO_MAX_HOPS = int(os.environ.get("POSTAL_MAX_HOPS", "4"))  # P1-1 : profondeur max d'un fil (anti-emballement)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mail (
  id              TEXT PRIMARY KEY,         -- = dedup (sha) -> anti-triplication
  sender          TEXT NOT NULL,
  sender_channel  TEXT,
  recipient       TEXT NOT NULL,
  recipient_channel TEXT,
  reply_to        TEXT,                     -- à qui répondre (def = sender)
  reply_channel   TEXT,                     -- par quel canal répondre (def = sender_channel)
  body            TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'queued',  -- queued|delivered|acked|dead
  attempts        INTEGER NOT NULL DEFAULT 0,
  ts_queued       REAL,
  ts_delivered    REAL,
  ts_acked        REAL,
  trace_id        TEXT,
  in_reply_to     TEXT,                      -- id du courrier auquel celui-ci répond
  claimed_by      TEXT,                      -- P0-1 exclusion mutuelle : worker qui a claim
  ts_claimed      REAL,
  hops            INTEGER NOT NULL DEFAULT 0 -- P1-1 anti-emballement : profondeur du fil (in_reply_to)
);
CREATE INDEX IF NOT EXISTS idx_mail_recip ON mail(recipient, status);
CREATE INDEX IF NOT EXISTS idx_mail_chan ON mail(recipient_channel, status);
"""


# ETATS TRAITES : les SEULS purgeables (decision owner 2026-10-01, repetee : « ne purge QUE ce
# qui est traite ; l'agent postal doit le savoir »). Le purgeur unique, forge_log_retention,
# lit ces listes ici. Liste BLANCHE : un etat nouveau ou inconnu est protege par defaut.
#  - bus M2M (agent_messages) : 'done'. PAS 'read' (lu, pas traite), PAS 'archived' (ici, le
#    courrier NON LU d'un agent mort, exporte puis marque), ni pending/unread/quarantaine.
#  - courrier riche (table `mail`) : 'acked' (accuse de traitement par le destinataire). PAS
#    'dead' : un courrier jamais livre n'a pas ete traite.
ETATS_M2M_TRAITES = frozenset({"done"})
ETATS_COURRIER_TRAITES = frozenset({"acked"})


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB), timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    c.executescript(_SCHEMA)
    for _col in ("claimed_by TEXT", "ts_claimed REAL", "hops INTEGER DEFAULT 0"):  # P0-1/P1-1 migration
        try:
            c.execute("ALTER TABLE mail ADD COLUMN " + _col)
        except sqlite3.OperationalError:
            pass
    return c


def claim(agent: str, mail_id: str) -> bool:
    """P0-1 — EXCLUSION MUTUELLE ATOMIQUE (1er domino, débat unanime). Un seul worker gagne un
    courrier 'delivered' : delivered -> claimed, rowcount==1 = gagné. Primitive dont dépendent
    Contract Net (award), multi-machine (1 nœud claim), répondeur Claude (anti double-réponse).
    Mutuellement exclusif avec l'ack interactif (tous deux atomiques sur status='delivered')."""
    con = _conn()
    try:
        cur = con.execute(
            "UPDATE mail SET status='claimed', claimed_by=?, ts_claimed=? WHERE id=? AND status='delivered'",
            ((agent or "").upper(), time.time(), mail_id),
        )
        con.commit()
        if cur.rowcount == 1:
            _emit("postal_claimed", {"id": mail_id, "by": (agent or "").upper(), "status": "claimed"})
            return True
        return False
    finally:
        con.close()


def ack_mail(mail_id: str, agent: str = "") -> bool:
    """Finalise un courrier traité : claimed/delivered -> acked (accusé de réception)."""
    con = _conn()
    try:
        cur = con.execute(
            "UPDATE mail SET status='acked', ts_acked=? WHERE id=? AND status IN ('claimed','delivered')",
            (time.time(), mail_id),
        )
        con.commit()
        if cur.rowcount:
            _emit("postal_acked", {"id": mail_id, "by": (agent or "").upper(), "status": "acked"})
        return cur.rowcount == 1
    finally:
        con.close()


def unclaim(mail_id: str) -> bool:
    """Rend un courrier claimé NON traité (échec CLI/quota) : claimed -> delivered (retriable)."""
    con = _conn()
    try:
        cur = con.execute(
            "UPDATE mail SET status='delivered', claimed_by=NULL WHERE id=? AND status='claimed'", (mail_id,))
        con.commit()
        return cur.rowcount == 1
    finally:
        con.close()


_REG_CACHE: dict = {"mtime": 0.0, "agents": {}, "index": {}}


def _registre() -> dict:
    """Registre identités (schéma 2), cache sur mtime. Source unique partagée
    avec forge_videur / forge_workspace_guard / forge_ring_admin."""
    p = ROOT / "config" / "agent_identities.json"
    try:
        m = p.stat().st_mtime
        if m != _REG_CACHE["mtime"]:
            reg = json.loads(p.read_text(encoding="utf-8"))
            agents = reg.get("agents", {}) or {}
            # index alias -> boîte de l'ACTEUR (un hook/relais n'a pas de boîte propre)
            index = {}
            for nom, e in agents.items():
                boite = (e.get("mailbox") or e.get("actor") or nom).upper()
                index[nom.upper()] = boite
                for a in e.get("aliases") or []:
                    index[str(a).upper()] = boite
            _REG_CACHE.update({"mtime": m, "agents": agents, "index": index})
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger("forge.postal").warning(
            "[postal] registre d'identités ILLISIBLE (%s: %s) | consequence: le "
            "courrier retombe sur le nom brut, donc deux noms du meme acteur "
            "redonnent deux boites — c'est le defaut du 2026-08-14",
            type(e).__name__, str(e)[:90])
    return _REG_CACHE


def canonical(nom: str) -> str:
    """Nom d'agent -> BOÎTE de l'acteur. `agt_antigravity`, `AGY`, `GEMINI`,
    `AGY_DAEMON` et `GEMINI_RELAY` désignent tous la boîte `ANTIGRAVITY`.
    Un hook ou un relais n'a pas de boîte propre : son courrier va à son acteur."""
    n = (nom or "").upper().strip()
    return _registre()["index"].get(n, n)


def alias_de(boite: str) -> list:
    """Tous les noms qui routent vers cette boîte. Sert à la LECTURE : les
    courriers déjà déposés sous un ancien nom restent relevables sans migration."""
    b = canonical(boite)
    noms = {b} | {k for k, v in _registre()["index"].items() if v == b}
    return sorted(noms)


def _channel_of(agent: str) -> str:
    """Canal d'un agent depuis le registre identité×canal (#10a)."""
    try:
        a = _registre()["agents"].get((agent or "").upper())
        if a is None:
            a = _registre()["agents"].get(canonical(agent), {})
        return (a or {}).get("channel", "")
    except Exception:
        return ""


def _dedup_id(sender: str, recipient: str, body: str, dedup_key: Optional[str]) -> str:
    base = dedup_key or f"{sender}|{recipient}|{body}"
    return "mail_" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:20]


def _rag_trace(mid: str, sender: str, recipient: str, body: str) -> None:
    """Trace collab -> rag_chunks (veille Stash 2026-07-07) : la memoire d'equipe
    voit passer le courrier inter-agents (sinon trou noir type « AGY a livre
    quoi ? »). Fire-and-forget en thread daemon (JAMAIS de SQLite sync dans un
    handler async — lecon log_turn) ; embedding NULL deferre au backfill :8099
    qui upserte aussi Qdrant. Contrat INSERT = miroir handle_index_result.
    Kill-switch LAFORGE_COLLAB_RAG=0."""
    if os.environ.get("LAFORGE_COLLAB_RAG", "1") == "0":
        return

    def _work():
        try:
            import sqlite3 as _sq
            text = f"[COLLAB:postal] {sender} -> {recipient}\n{(body or '')[:1200]}"
            con = _sq.connect(str(ROOT / "RAG" / "embeddings.db"), timeout=10)
            con.execute(
                "INSERT OR IGNORE INTO rag_chunks(id, source, text, domain, author, ingested_at) "
                "SELECT ?, ?, ?, ?, ?, datetime('now') "
                "WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)",
                (f"collab_postal_{mid}", f"postal:{sender.lower()}", text,
                 "laforge-memory", sender, f"collab_postal_{mid}"))
            con.commit()
            con.close()
        except Exception:
            pass

    import threading as _th
    _th.Thread(target=_work, daemon=True, name="collab-rag-trace").start()


def post(sender: str, recipient: str, body: str, *, reply_to: Optional[str] = None,
         reply_channel: Optional[str] = None, sender_channel: Optional[str] = None,
         recipient_channel: Optional[str] = None, dedup_key: Optional[str] = None,
         trace_id: Optional[str] = None, in_reply_to: Optional[str] = None) -> dict:
    """Dépose un courrier riche EN GARE DE TRIAGE (queued). Dédup sur (sender,recipient,body)
    ou dedup_key -> INSERT OR IGNORE = pas de triplication."""
    # ÉCRITURE CANONIQUE : le courrier part vers la boîte de l'ACTEUR, jamais
    # vers l'un de ses alias de surface (hook, relais, agt_*, ancien nom).
    sender, recipient = canonical(sender), canonical(recipient)
    sc = sender_channel or _channel_of(sender)
    rc = recipient_channel or _channel_of(recipient)
    mid = _dedup_id(sender, recipient, body, dedup_key)
    now = time.time()
    con = _conn()
    try:
        hops = 0
        if in_reply_to:  # P1-1 ANTI-EMBALLEMENT : profondeur du fil bornée -> le ping-pong auto
            _ph = con.execute("SELECT hops FROM mail WHERE id=?", (in_reply_to,)).fetchone()  # 2-côtés ne diverge pas
            hops = ((_ph[0] or 0) if _ph else 0) + 1
            if hops > AUTO_MAX_HOPS:
                _emit("postal_refused", {"from": sender, "to": recipient, "reason": "max_hops", "hops": hops})
                return {"id": None, "status": "refused", "reason": f"max_hops {AUTO_MAX_HOPS} (anti-emballement)", "hops": hops}
        # Sprint 3 M2M : validation du courrier (config/m2m_intents.json).
        # warn (defaut) = event bus ; error = refus (miroir max_hops). Fail-open.
        try:
            from nokido_agent.app.forge_m2m_protocol import check as _m2m_check
            _ok_m2m, _v_m2m = _m2m_check("postal", body)
            if not _ok_m2m:
                _emit("postal_refused", {"from": sender, "to": recipient, "reason": "m2m",
                                         "code": _v_m2m.get("code")})
                return {"id": None, "status": "refused", "reason": f"m2m: {_v_m2m.get('code')}",
                        "m2m": _v_m2m}
        except Exception:
            pass
        cur = con.execute(
            "INSERT OR IGNORE INTO mail (id,sender,sender_channel,recipient,recipient_channel,"
            "reply_to,reply_channel,body,status,ts_queued,trace_id,in_reply_to,hops) "
            "VALUES (?,?,?,?,?,?,?,?, 'queued', ?,?,?,?)",
            (mid, sender, sc, recipient, rc, (reply_to or sender).upper(),
             reply_channel or sc, body, now, trace_id, in_reply_to, hops),
        )
        con.commit()
        if cur.rowcount == 1:  # nouveau courrier seulement (pas les duplicates dedup)
            _rag_trace(mid, sender, recipient, body)
        _emit("postal_queued", {"id": mid, "from": sender, "to": recipient, "channel": rc,
                                "body": body[:240], "status": "queued", "duplicate": cur.rowcount == 0})
        return {"id": mid, "status": "queued", "duplicate": cur.rowcount == 0,
                "sender": sender, "sender_channel": sc, "recipient": recipient, "recipient_channel": rc}
    finally:
        con.close()


def _emit(kind: str, data: dict) -> None:
    """Publie un event sur le swarm bus existant (vue live /forge/postal). Best-effort,
    no-op si pas de bus (selftest, sandbox). topic='postal' -> filtrable côté UI."""
    try:
        from nokido_agent.app.forge_swarm_bus import publish

        publish(kind, data, topic="postal")
    except Exception:
        pass


_SWARM_LLM = ["ANTIGRAVITY", "GEMINI", "CODEX", "COPILOT", "CLINE", "ROO_PLAN", "SIXTH"]


def broadcast(sender, body, *, agents=None, exclude=None, reply_to=None, dry_run=False):
    """Fan-out M2M au swarm en UN appel (forge_postal est 1:1 sinon). `agents` defaut =
    collaborateurs LLM canoniques (_SWARM_LLM) ; chacun draine son canal en autonome (pull).
    Liste CUREE, PAS de dedup par canal : CODEX/COPILOT partagent HTTP_DIRECT mais sont des
    agents distincts (le canal = transport, pas identite). exclude + emetteur sautes.
    dry_run=True -> liste les cibles sans poster (test sur)."""
    targets = agents if agents is not None else _SWARM_LLM
    skip = {(e or "").upper() for e in (exclude or [])}
    skip.add((sender or "").upper())
    out = []
    for name in targets:
        if name.upper() in skip:
            continue
        if dry_run:
            out.append({"to": name, "channel": _channel_of(name), "dry": True})
            continue
        try:
            r = post(sender, name, body, reply_to=reply_to)
            out.append({"to": name, "channel": r.get("recipient_channel"), "status": r.get("status")})
        except Exception as e:  # noqa: BLE001
            out.append({"to": name, "error": str(e)[:120]})
    return out


def facteur(channel: str, deliver_fn=None) -> dict:
    """FACTEUR du canal : achemine les courriers queued -> delivered (ACCUSÉ DE LIVRAISON).
    deliver_fn(mail_row)->bool = transport réel optionnel (notify/mailbox) ; sinon le passage
    en 'delivered' suffit (l'agent lit via secretaire). Échec -> reste queued (EN GARE), cap dead."""
    con = _conn()
    delivered, stuck = [], []
    try:
        rows = con.execute(
            "SELECT id,sender,recipient,body,attempts FROM mail "
            "WHERE recipient_channel=? AND status='queued' ORDER BY ts_queued", (channel,),
        ).fetchall()
        for mid, sender, recipient, body, attempts in rows:
            ok = True
            if deliver_fn is not None:
                try:
                    ok = bool(deliver_fn({"id": mid, "sender": sender, "recipient": recipient, "body": body}))
                except Exception:
                    ok = False
            if ok:
                con.execute("UPDATE mail SET status='delivered', ts_delivered=?, attempts=attempts+1 WHERE id=?",
                            (time.time(), mid))
                delivered.append(mid)
                _emit("postal_delivered", {"id": mid, "from": sender, "to": recipient,
                                           "channel": channel, "body": body[:240], "status": "delivered"})
            else:
                na = attempts + 1
                con.execute("UPDATE mail SET attempts=?, status=? WHERE id=?",
                            (na, "dead" if na >= MAX_ATTEMPTS else "queued", mid))
                stuck.append({"id": mid, "attempts": na})
        con.commit()
        return {"channel": channel, "delivered": delivered, "en_gare_de_triage": stuck}
    finally:
        con.close()


def _match(m: dict, filt: dict) -> bool:
    """Filtre de TRIAGE du secrétaire (à étendre, spec 'filtre à définir' user). Clés :
    from (expéditeur), contains (sous-chaîne du body), min_ts (delivered après), status."""
    if "from" in filt and (m.get("from") or "").upper() != str(filt["from"]).upper():
        return False
    if "contains" in filt and str(filt["contains"]).lower() not in (m.get("body") or "").lower():
        return False
    if "min_ts" in filt and (m.get("ts_delivered") or 0) < float(filt["min_ts"]):
        return False
    if "status" in filt and m.get("status") != filt["status"]:
        return False
    return True


# Auto-triage SÛR : ne marquer routine QUE les RÉPONSES auto d'un agent (préfixe `[X-AUTO`),
# JAMAIS une requête/ping (qui DOIT être traitée). Bug 2026-06-14 : des markers larges ("test
# pickup") ackaient un vrai ping destiné à Gemini avant que son agent le pioche -> ping-pong cassé.
_ROUTINE_MARKERS = ("[gemini-auto", "[gemini_auto", "[claude-auto", "[copilot-auto")


def _is_routine(body: str) -> bool:
    # Predicat partage avec `forge_semantic_invariant._porte_une_decision` :
    # meme test, vocabulaires differents (2026-08-20, cliquet de clones).
    from nokido_agent.app.forge_utils import contient_un_mot

    return contient_un_mot(body, _ROUTINE_MARKERS)


def auto_ack_replied(agent: str, routine: bool = True) -> dict:
    """AUTO-TRIAGE (tâche de synchro) : acke les courriers DELIVERED à `agent` DÉJÀ traités —
    (a) `agent` y a déjà RÉPONDU (un mail existe avec in_reply_to=ce mail ET sender=agent), ou
    (b) routine test/FYI (pattern _ROUTINE_MARKERS). SÛR : ne touche JAMAIS un actionnable non
    répondu (il reste 'delivered' -> surfacé par le digest). Retourne {replied:[...], routine:[...]}."""
    agent = (agent or "").upper()
    con = _conn()
    ackd = {"replied": [], "routine": []}
    try:
        rows = con.execute(
            "SELECT id, body FROM mail WHERE recipient=? AND status='delivered'", (agent,)
        ).fetchall()
        for mid, body in rows:
            why = None
            rep = con.execute(
                "SELECT 1 FROM mail WHERE in_reply_to=? AND sender=? LIMIT 1", (mid, agent)
            ).fetchone()
            if rep:
                why = "replied"
            elif routine and _is_routine(body):
                why = "routine"
            if why:
                con.execute("UPDATE mail SET status='acked', ts_acked=? WHERE id=?", (time.time(), mid))
                ackd[why].append(mid)
        if ackd["replied"] or ackd["routine"]:
            con.commit()
            _emit("postal_auto_acked",
                  {"agent": agent, "replied": len(ackd["replied"]), "routine": len(ackd["routine"])})
        return ackd
    finally:
        con.close()


def secretaire(agent: str, ack: bool = False, include_acked: bool = False,
               filt: Optional[dict] = None) -> list:
    """SECRÉTAIRE : relève le courrier de l'agent. Defaut = delivered non-ackés, ack=False
    (NON-consommant, l'agent relit -> corrige le 'poll vide' du test). ack=True -> marque acked
    (ACCUSÉ DE RÉCEPTION). include_acked=True -> RE-PRÉSENTE aussi les ackés (re-montre AVANT
    suppression/archivage, spec user). filt (dict) = triage : ne re-présente que le matching."""
    # LECTURE ÉLARGIE : la boîte canonique ET tous ses alias, sinon les courriers
    # déposés sous un ancien nom restent invisibles (8 dormants le 2026-08-14).
    agent = canonical(agent)
    boites = alias_de(agent)
    statuses = ("delivered", "acked") if include_acked else ("delivered",)
    ph = ",".join("?" * len(statuses))
    pb = ",".join("?" * len(boites))
    con = _conn()
    try:
        rows = con.execute(
            f"SELECT id,sender,sender_channel,reply_to,reply_channel,body,ts_delivered,in_reply_to,status "
            f"FROM mail WHERE recipient IN ({pb}) AND status IN ({ph}) ORDER BY ts_delivered",
            (*boites, *statuses),
        ).fetchall()
        out = []
        for r in rows:
            m = {"id": r[0], "from": r[1], "from_channel": r[2], "reply_to": r[3],
                 "reply_channel": r[4], "body": r[5], "ts_delivered": r[6], "in_reply_to": r[7], "status": r[8]}
            if filt and not _match(m, filt):
                continue
            out.append(m)
        if ack:
            for m in out:
                if m["status"] == "delivered":
                    con.execute("UPDATE mail SET status='acked', ts_acked=? WHERE id=?", (time.time(), m["id"]))
                    _emit("postal_acked", {"id": m["id"], "from": m["from"], "to": agent, "status": "acked"})
            con.commit()
        return out
    finally:
        con.close()


def represent(agent: str, filt: Optional[dict] = None) -> list:
    """Re-PRÉSENTE le courrier (delivered + acked) AVANT suppression/archivage, selon filtre.
    Non-consommant. Le secrétaire re-montre l'important avant que la rétention (2j) ne purge."""
    return secretaire(agent, ack=False, include_acked=True, filt=filt)


_RING_INCONNU = 99  # sentinelle : moins privilegie que tout ring declare (0..4)


def _ring_resolu(agent: str) -> tuple:
    """(ring, etat) — etat ∈ RESOLU | INCONNU | ILLISIBLE.

    TROIS ETATS ET JAMAIS DEUX. La version precedente rendait `3` pour un agent
    inconnu, pour un registre illisible ET pour un vrai ring 3 : une panne de
    lecture y etait indistinguable d'une identite. Or 3 est plus privilegie que
    31 des 146 identites declarees — l'inconnu etait mieux traite que le connu.

    ELLE RESOUT LES ALIAS, ce que l'ancienne ne faisait pas : celle-ci indexait
    `agent.upper()` droit dans `agents`, si bien que `agt_claude` (alias de
    CLAUDE, ring 1) etait lu 3. Mesure du 2026-09-21 sur `sandbox/m2m.db` :
    117 des 304 alias rendaient un ring autre que le leur, et 252 messages
    reellement emis (agt_claude 161, agt_gemini 89, agt_antigravity 2) y
    perdaient le boost de priorite auquel leur ring 1 donne droit.

    ⚠️ NE PAS « SIMPLIFIER » EN APPELANT `canonical()` juste au-dessus. Celle-la
    rend la BOITE de l'acteur, pas l'identite : `agt_claude_hook` y devient
    `CLAUDE`. Le ring de CLAUDE_HOOK vaut 4, celui de CLAUDE vaut 1 — passer par
    la boite fabriquerait une elevation de 4 vers 1, exactement le defaut que
    cette fonction sert a fermer. BOITE et IDENTITE repondent a deux questions
    distinctes : « ou va le courrier » et « qui parle ».

    La resolution elle-meme n'est pas reecrite ici : `_resoudre_agent` est la
    primitive canonique (deux passes, canoniques avant alias), durcie le
    2026-09-20 apres l'elevation LAFORGE_CLI / NOKIDO_CLI.
    """
    try:
        from nokido_agent.app.forge_m2m_protocol import _resoudre_agent
        canon, _surface = _resoudre_agent(agent)
    except Exception:
        return _RING_INCONNU, "ILLISIBLE"
    if not canon:
        return _RING_INCONNU, "INCONNU"
    agents = _registre()["agents"]
    if not agents:
        return _RING_INCONNU, "ILLISIBLE"
    brut = (agents.get(canon) or {}).get("ring")
    if brut is None:
        return _RING_INCONNU, "INCONNU"
    try:
        return int(brut), "RESOLU"
    except (TypeError, ValueError):
        return _RING_INCONNU, "INCONNU"


def _ring_of(agent: str) -> int:
    """Ring d'un agent, alias compris. Un inconnu ou une lecture en panne rendent
    `_RING_INCONNU`, donc fail-closed partout ou le ring commande un privilege
    par un `<= n`. Appeler `_ring_resolu` quand l'ETAT compte — un entier seul ne
    peut pas dire s'il vient d'une identite ou d'une panne."""
    return _ring_resolu(agent)[0]


_URGENT_KW = ("urgent", "[risk", "crit", "bloqu", "asap", "!!", "danger", "fail", "oom", "down")


def _priority_score(m: dict, now: float) -> float:
    """Intelligence de priorité : urgence (mots-clés) + ring bas de l'expéditeur (+ de confiance)
    + ancienneté (un vieux courrier non traité remonte). Plus haut = plus prioritaire."""
    body = (m.get("body") or "").lower()
    urg = 2.0 if any(k in body for k in _URGENT_KW) else 0.0
    ring_boost = 1.0 if _ring_of(m.get("from", "")) <= 1 else 0.0
    age_h = (now - (m.get("ts_delivered") or now)) / 3600.0
    return round(urg + ring_boost + min(age_h, 3.0), 3)


def digest(agent: str, filt: Optional[dict] = None) -> dict:
    """SECRÉTAIRE INTELLIGENT : au lieu de relever BRUT, il TRIE — priorise (urgence/ring/âge),
    GROUPE par fil de discussion (in_reply_to), RÉSUME, et RECOMMANDE quoi traiter. Non-consommant
    (l'agent décide). C'est la logique agentique du secrétaire : transformer une boîte en plan d'action."""
    now = time.time()
    mails = secretaire(agent, ack=False, filt=filt)
    for m in mails:
        m["_prio"] = _priority_score(m, now)
    ranked = sorted(mails, key=lambda m: m["_prio"], reverse=True)
    threads: dict = {}
    for m in mails:
        threads.setdefault(m.get("in_reply_to") or m["id"], []).append(m["id"])
    top: dict = {}
    for m in mails:
        top[m["from"]] = top.get(m["from"], 0) + 1
    urgent = [m for m in ranked if m["_prio"] >= 2.0]
    oldest = round(max((now - (m.get("ts_delivered") or now) for m in mails), default=0))
    return {
        "agent": agent.upper(),
        "n_pending": len(mails),
        "n_threads": len(threads),
        "urgent": [{"id": m["id"], "from": m["from"], "prio": m["_prio"], "body": (m["body"] or "")[:140]} for m in urgent[:5]],
        "ranked_ids": [m["id"] for m in ranked],
        "threads": threads,
        "top_senders": sorted(top.items(), key=lambda x: -x[1])[:5],
        "oldest_pending_age_s": oldest,
        "recommend": (
            "INBOX VIDE" if not mails
            else f"TRAITER {len(urgent)} URGENT(S) d'abord" if urgent
            else f"{len(mails)} courrier(s), {len(threads)} fil(s) — lire par priorité"
        ),
    }


def envelope_for(agent: str, max_msgs: int = 5) -> str:
    """Bloc TEXTE des M2M postal en attente pour `agent` (delivered), ACK au passage
    (surface-once, réutilise secretaire(ack=True)). Fail-safe : '' sur TOUTE erreur.
    L'APPELANT doit avoir vérifié l'identité FORTE (token) avant — ne jamais exposer
    sur un header usurpable (anti-spoof)."""
    try:
        mails = secretaire(agent, ack=True)
        if not mails:
            return ""
        lines = [f"[M2M] {len(mails)} message(s) postal en attente pour {agent.upper()} (auto-surface) :"]
        for m in mails[:max_msgs]:
            body = (m.get("body") or "").replace(chr(10), " ")[:400]
            lines.append(f"  - [{m.get('from')}] {body}")
        if len(mails) > max_msgs:
            lines.append(f"  (+{len(mails) - max_msgs} autre(s) — hub action=poll)")
        return "\n\n" + "\n".join(lines)
    except Exception:
        return ""


def facteur_is_online(agent: str) -> bool:
    """Présence best-effort (intelligence facteur) : l'agent a-t-il un heartbeat/poll récent ?
    Sert à decider acheminement-direct vs garder-en-gare. Hook extensible."""
    try:
        for cand in (ROOT / "sandbox" / f"{agent.lower()}_poll_daemon.heartbeat",
                     ROOT / "sandbox" / f"presence_{agent.lower()}.seen"):
            if cand.exists() and (time.time() - cand.stat().st_mtime) < 300:
                return True
    except Exception:
        pass
    return False


def track(mail_id: str) -> dict:
    """Suivi d'un courrier (pour l'expéditeur) : où en est l'acheminement."""
    con = _conn()
    try:
        r = con.execute(
            "SELECT status,attempts,ts_queued,ts_delivered,ts_acked,recipient,recipient_channel "
            "FROM mail WHERE id=?", (mail_id,)).fetchone()
        if not r:
            return {"id": mail_id, "status": "unknown"}
        return {"id": mail_id, "status": r[0], "attempts": r[1], "ts_queued": r[2],
                "ts_delivered": r[3], "ts_acked": r[4], "recipient": r[5], "recipient_channel": r[6],
                "accuse_livraison": r[3] is not None, "accuse_reception": r[4] is not None}
    finally:
        con.close()


def channels_with_pending() -> list:
    con = _conn()
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT recipient_channel FROM mail WHERE status='queued'").fetchall() if r[0]]
    finally:
        con.close()


def _selftest() -> int:
    body = f"URGENT bloquant : design facteur/secretaire [{time.time()}]"
    r = post("CLAUDE", "GEMINI", body, reply_to="CLAUDE")
    dup = post("CLAUDE", "GEMINI", body)  # même contenu -> DÉDUP (anti-triplication)
    assert dup["duplicate"], "dedup FAIL"
    f = facteur(r["recipient_channel"])
    assert r["id"] in f["delivered"], "facteur FAIL"
    box = secretaire("GEMINI")
    assert any(m["id"] == r["id"] for m in box), "secretaire FAIL"
    d = digest("GEMINI")  # SECRÉTAIRE INTELLIGENT : doit prioriser l'URGENT
    assert d["urgent"], "digest priorisation FAIL"
    secretaire("GEMINI", ack=True)  # accusé de réception
    rep = represent("GEMINI")  # re-présente (incl acked) avant purge
    t = track(r["id"])
    assert t["status"] == "acked" and t["accuse_reception"], "ack FAIL"
    # P0-1 — EXCLUSION MUTUELLE ATOMIQUE (test d'acceptation = 2 claims concurrents, 1 seul gagne)
    r2 = post("CLAUDE", "GEMINI", f"claim test [{time.time()}]", reply_to="CLAUDE")
    facteur(r2["recipient_channel"])  # -> delivered
    assert claim("GEMINI", r2["id"]) is True, "claim 1 doit GAGNER"
    assert claim("GEMINI", r2["id"]) is False, "claim 2 doit PERDRE (exclusion atomique)"
    assert ack_mail(r2["id"], "GEMINI") is True, "ack_mail FAIL"
    assert track(r2["id"])["status"] == "acked", "claim->acked FAIL"
    # P1-1 — borne HOP (anti-emballement) : un fil > AUTO_MAX_HOPS est refusé
    _pid = post("CLAUDE", "GEMINI", f"hop0 [{time.time()}]")["id"]
    _rh = {"status": "?"}
    for _i in range(1, AUTO_MAX_HOPS + 2):
        _rh = post("CLAUDE", "GEMINI", f"hop{_i} [{time.time()}]", in_reply_to=_pid)
        if _rh.get("status") == "refused":
            break
        _pid = _rh["id"]
    assert _rh.get("status") == "refused", "hop-limit doit refuser au-delà de AUTO_MAX_HOPS"
    print(json.dumps({"selftest": "PASS", "dedup_blocked": dup["duplicate"],
                      "claim_exclusion": "1 gagne / 1 perd OK",
                      "hop_limit": f"refusé hops={_rh.get('hops')} (max {AUTO_MAX_HOPS})",
                      "digest_recommend": d["recommend"], "urgent_detected": len(d["urgent"]),
                      "represent_incl_acked": len(rep), "track": t}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("forge_postal: post/facteur/secretaire/track/channels_with_pending. --selftest pour tester.")
