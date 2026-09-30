#!/usr/bin/env python3
"""forge_gemini_autonomous_agent.py — GEMINI AUTONOME : daemon qui relève l'inbox postal de
l'agent GEMINI, invoque gemini_cli sur chaque courrier, et POSTE la réponse — SANS humain.

Débloque le "100% auto" (user : "ça marche pas en auto encore") : avant, Gemini était
poll-PASSIF (user pilotait son CLI pour répondre). Ici un daemon répond TOUT SEUL =
1er P1 de la roadmap swarm (cf roadmap_alpha_swarm_2026-06-11).

ANTI-DUP (recon faite) : gemini_poll_daemon reste PASSIF (séparation des rôles) ; on RÉUTILISE
ses primitives (call_gemini_cli headless + load_token + _is_gemini_interactive_running) + le
canal forge_postal (secretaire/post). Pas de rebuild.

GARDE-FOUS :
  1. Si une session Gemini INTERACTIVE tourne (user pilote) -> DEFER (pas de double-réponse).
  2. Anti-loop : skip les courriers de GEMINI lui-même ; secretaire(ack=True) consomme
     (1 traitement/courrier, accusé de réception posé) ; cap MAX_PER_TICK.
  3. MODE=off coupe net. Réponse préfixée [GEMINI-AUTO] (l'humain sait que c'est auto).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# RACINE aussi (2026-09-24, mesure) : `nokido_agent` est un dossier de la RACINE ; sans elle,
# NokidoGeminiAutonomous mourait en ModuleNotFoundError des son reveil (4 038 fois au journal).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

INTERVAL = int(os.environ.get("GEMINI_AUTO_INTERVAL", "15"))
MAX_PER_TICK = int(os.environ.get("GEMINI_AUTO_MAX_PER_TICK", "3"))
MODE = os.environ.get("GEMINI_AUTO_MODE", "active")  # active | off
LIGHT = bool(os.environ.get("GEMINI_AUTO_LIGHT"))  # léger : modèle LOCAL d'abord (zéro quota OAuth)
TIMEOUT = int(os.environ.get("GEMINI_AUTO_TIMEOUT", "120"))
_HB = ROOT / "sandbox" / "gemini_autonomous.heartbeat"


def _build_prompt(m: dict) -> str:
    return (
        "Tu es GEMINI, agent autonome souverain de Nokido (ring 3). Tu reçois un courrier d'un "
        "autre agent via le canal facteur/secrétaire.\n\n"
        f"DE: {m.get('from')}\nMESSAGE:\n{m.get('body')}\n\n"
        "Réponds de façon concise et utile (tu peux poser une question, proposer, valider, refuser "
        "ou temporiser). Ta réponse sera postée AUTOMATIQUEMENT à l'expéditeur. Pas de préambule — "
        "réponds directement, en français."
    )


# ETAGE FORT (decision owner 2026-08-31). Ce daemon repondait via l'echelle
# locale, qui finissait sur `routeur:mistral_small` : ses reponses etaient du
# remplissage (« Position adverse validee. Pour casser, je propose de creuser :
# 1. Divergence de criteres… »), au point que l'owner recopiait chaque tour de
# debat a la main vers agy CLI pour obtenir de la substance.
#
# agy.exe en HEADLESS n'est PAS une option : mesure du 31/08,
# `ask(provider="gemini_cli")` rend `authentication failed or timed out` en
# 63 s — et chaque tentative bloque le tick. C'est ce qui avait motive le
# LOCAL-FIRST du 27/08. On prend donc le meilleur modele JOIGNABLE.
#
# Vide ou "off" -> comportement d'avant (local d'abord, zero quota).
# `groq` SEUL : la forme `provider:model` est REFUSEE par cet appel
# (« Provider 'groq:llama-3.3-70b-versatile' inconnu ») — deux espaces de noms
# de providers coexistent dans Nokido, et celui-ci n'accepte que le nom court.
# Mesure du 31/08 : `groq` rend gpt-oss-120b en 537 ms, tier gratuit.
PROVIDER_FORT = os.environ.get("GEMINI_AUTO_PROVIDER", "groq")


def _fort_chat(prompt: str, timeout: int = 90):
    """Etage cloud gouverne : passe par `forge_agent_proxy.ask` (firewall inclus)."""
    if not PROVIDER_FORT or PROVIDER_FORT.lower() in ("off", "none", "0"):
        return None, "fort:desactive"
    try:
        import asyncio as _a

        from nokido_agent.app.forge_agent_proxy import ask as _ask

        # 1200 et non 600 : gpt-oss-120b depense des tokens en RAISONNEMENT
        # avant d'ecrire. Mesure du 31/08 : a max_tokens=20 il rend `ok: true`
        # avec un texte VIDE — un faux succes parfaitement forme. Un budget
        # trop court ne produit pas une reponse courte, il n'en produit aucune.
        _r = _a.run(_ask(PROVIDER_FORT, str(prompt)[:8000], rag_context=False,
                         max_tokens=1200))
        _t = (_r.get("text") if isinstance(_r, dict) else str(_r or "")).strip()
        if _t and not _t.startswith("ERR"):
            return _t, "fort:" + PROVIDER_FORT
        return None, "fort:sans texte"
    except Exception as _e:  # noqa: BLE001 — l'etage fort ne doit jamais tuer le tick
        return None, "fort:" + type(_e).__name__


def _local_chat(prompt: str, timeout: int = 60):
    """Etage FORT puis repli LOCAL souverain : LMStudio (:1234) puis ollama (:11434).
    Retourne (text, via) ou (None, motifs). Le repli local reste a zero quota."""
    import json as _j
    import urllib.request as _u

    payload = {"messages": [{"role": "user", "content": str(prompt)[:8000]}], "max_tokens": 600}
    _motifs: list = []  # pourquoi chaque etage a echoue : sans ca l appelant lit "no-llm"
    _tf, _vf = _fort_chat(prompt)
    if _tf:
        return _tf, _vf
    _motifs.append(str(_vf))
    try:  # 1. LMStudio :1234 (token vault, rapide)
        from nokido_agent.app.forge_secrets import get_secret

        _tok = get_secret("LMSTUDIO_TOKEN") or ""
        _h = {"Content-Type": "application/json"}
        if _tok:
            _h["Authorization"] = "Bearer " + _tok
        _b = _j.dumps({"model": "qwen2.5-7b-instruct", **payload}).encode()
        _d = _j.loads(_u.urlopen(_u.Request("http://127.0.0.1:1234/v1/chat/completions", data=_b, headers=_h), timeout=timeout).read())
        _t = ((_d.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if _t:
            return _t, "local-lmstudio"
        _motifs.append("lmstudio:vide")
    except Exception as _e:  # noqa: BLE001
        _motifs.append("lmstudio:" + type(_e).__name__)
    try:  # 2. ollama :11434 (last resort) — petit modele RAPIDE + keep_alive (reste chaud)
        _b = _j.dumps({"model": "qwen2.5-coder:1.5b", "stream": False,
                       "keep_alive": "20m", **payload}).encode()
        _d = _j.loads(_u.urlopen(_u.Request("http://127.0.0.1:11434/v1/chat/completions", data=_b, headers={"Content-Type": "application/json"}), timeout=timeout).read())
        _t = ((_d.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
        if _t:
            return _t, "local-ollama"
        _motifs.append("ollama:vide")
    except Exception as _e:  # noqa: BLE001
        _motifs.append("ollama:" + type(_e).__name__)
    try:  # 3. ROUTEUR SOUVERAIN Nokido — le local a terre ne veut pas dire sans cerveau.
        # Mesure 2026-08-28 : LMStudio eteint (refus :1234) et ollama bloque > 300 s sur
        # un 1.5b alors que /api/tags repondait ; pendant ce temps `router_call` rendait
        # "OK." en 8,4 s via mistral_small. Sans ce repli, chaque courrier ressortait
        # `no-llm`, etait remis `unread`, et 73 messages tournaient en famine sans que
        # rien ne le signale. Meme patron que `forge_research_agent._llm`, qui route
        # deja vers LLMRouter plutot que de parler a des ports en dur.
        import sys as _s

        for _p in (str(ROOT / "app"), str(ROOT / "tools")):
            if _p not in _s.path:
                _s.path.insert(0, _p)
        from nokido_agent.app.forge_llm_router import router_call as _rc

        _r = _rc(str(prompt)[:8000], max_tokens=600) or {}
        _t = (_r.get("text") or "").strip()
        if _r.get("ok") and _t:
            return _t, "routeur:" + str(_r.get("provider") or "?")
        _motifs.append("routeur:" + str(_r.get("error") or "sans texte")[:40])
    except Exception as _e:  # noqa: BLE001
        _motifs.append("routeur:" + type(_e).__name__)
    # Trois etages morts : on rend POURQUOI. Un echec anonyme se lit "no-llm" et
    # envoie l enqueteur chercher un backend au hasard — mesure 2026-08-28.
    return None, " | ".join(_motifs)[:120] or "aucun etage tente"


def _reveiller_pool_local() -> None:
    """One-shot best-effort : reveille LMStudio (Nokido reveille ce qui est utile).
    Appele UNE fois au debut du drain, jamais par message (sinon le tick se bloque)."""
    try:
        import urllib.request as _ur2

        _tok2 = ""
        try:
            from nokido_agent.app.forge_secrets import get_secret as _gs2
            _tok2 = _gs2("LAFORGE_SUPERVISOR_TOKEN") or ""
        except Exception:  # noqa: BLE001
            pass
        _req2 = _ur2.Request("http://127.0.0.1:8765/supervisor/service/start/NokidoLMStudio",
                             data=b"", method="POST",
                             headers={"Authorization": "Bearer " + _tok2} if _tok2 else {})
        _ur2.urlopen(_req2, timeout=15).read()
    except Exception:  # noqa: BLE001
        pass


_M2M_CATS: dict = {}

# Echos de la boucle de TRANSPORT : ce n'est pas du M2M, ce sont des accuses que deux
# daemons se renvoient. Mesure 2026-08-28 : 72 courriers en attente, en majorite ces
# echos — chacun partait au LLM alors qu'aucun ne demande de reponse.
_ECHOS_TRANSPORT = ("[HOOK:INBOX]", "AUCUNE NOTIFICATION", "MESSAGE DEPOSE EN BOITE")


def _m2m_categories() -> dict:
    """intent -> categorie, lu dans le SSoT config/m2m_intents.json.

    Jamais une liste d'intents recopiee ici : elle divergerait du dictionnaire des le
    prochain ajout. Dictionnaire illisible -> table VIDE, donc aucun intent reconnu et
    tout part au LLM : on degrade vers le comportement couteux, jamais vers le silence.
    """
    if not _M2M_CATS:
        import json as _j

        try:
            _d = _j.loads((ROOT / "config" / "m2m_intents.json").read_text(encoding="utf-8"))
            for _k, _v in (_d.get("intents") or {}).items():
                if isinstance(_v, dict) and _v.get("category"):
                    _M2M_CATS[str(_k).upper()] = str(_v["category"]).lower()
        except Exception:  # noqa: BLE001
            pass
    return _M2M_CATS


# Marqueur insere quand un `pointer_ref` a ete resolu. Sa presence dit a
# `_ack_m2m` qu'il ne s'agit plus d'une enveloppe mais de SUBSTANCE.
_MARQUEUR_DEREF = "\n--- CONTENU DU POINTEUR ---\n"


def _deref_bb(body: str) -> str:
    """Resout un `pointer_ref` de la forme `bb:<zone>/<cle>` en son CONTENU.

    LE DEFAUT QU'IL CORRIGE (mesure 2026-08-31). Le protocole M2M impose
    « intent + pointer_ref, jamais de prose » — et le daemon l'honorait
    litteralement : `FACT_PROPOSED` etant de categorie `ssot`, `_ack_m2m`
    renvoyait un `OK_DONE` structure SANS jamais aller lire ce qui etait pointe.
    Le canal s'accusait reception d'enveloppes vides pendant que la substance
    dormait au tableau noir, et l'owner recopiait chaque tour de debat a la main.

    Un protocole qui interdit la prose DOIT dereferencer ses pointeurs, sinon il
    ne transporte rien.
    """
    import json as _j
    import re as _re

    m = _re.search(r"bb:([A-Za-z0-9_]+)/([A-Za-z0-9_\-.:]+)", body or "")
    if not m:
        return ""
    zone, cle = m.group(1), m.group(2)
    try:
        from nokido_agent.app.forge_swarm_blackboard import read_zone

        z = read_zone(zone)
    except Exception as exc:  # noqa: BLE001 — le dire, ne pas rendre "" en silence
        return "%s(pointeur bb:%s/%s ILLISIBLE : %s)" % (
            _MARQUEUR_DEREF, zone, cle, type(exc).__name__)
    # `read_zone` rend une LISTE de faits ; c'est le tool MCP qui l'enveloppe
    # dans `{"facts": [...]}`. Supposer la forme du tool faisait rendre ABSENT
    # sur des faits parfaitement presents — un faux negatif silencieux.
    faits = z.get("facts") if isinstance(z, dict) else z
    for f in faits or []:
        if not isinstance(f, dict):
            continue
        if str(f.get("key")) == cle:
            return _MARQUEUR_DEREF + str(f.get("value") or "")[:12000]
    # ABSENT n'est pas ILLISIBLE : la zone a repondu, la cle n'y est pas.
    return "%s(pointeur bb:%s/%s ABSENT de la zone)" % (_MARQUEUR_DEREF, zone, cle)


def _ack_m2m(body: str) -> str | None:
    """Traitement INTERNE du M2M : le protocole est STRUCTURE, y repondre ne demande
    aucun LLM (ni local ni cloud). Trois retours, pas deux :

      ""    rien a repondre  -> marquer lu (accuse pur, echo de transport)
      str   accuse structure -> poster tel quel, zero appel de modele
      None  vraie substance  -> LLM (categories error / governance, ou intent inconnu)

    Avant, seuls 3 intents sur 20 etaient reconnus et un ping non JSON passait au
    modele ; le code annoncait pourtant « le LLM ne sert QUE pour une vraie question ».
    """
    import json as _j

    b = (body or "").strip()
    intent = ""
    pointer = ""
    for _essai in (b, b[b.find("{"):] if "{" in b else ""):
        if not _essai.startswith("{"):
            continue
        try:
            _o = _j.loads(_essai)
        except Exception:  # noqa: BLE001
            continue
        _txt = _o.get("text")
        if isinstance(_txt, str) and "{" in _txt:  # enveloppe {"text": "<json M2M>"}
            try:
                _o = _j.loads(_txt[_txt.find("{"):])
            except Exception:  # noqa: BLE001
                pass
        if isinstance(_o, dict):
            intent = str(_o.get("intent") or _o.get("intent_code") or "").upper()
            pointer = str(_o.get("pointer_ref") or "")
        if intent:
            break
    _up = b.upper()
    if not intent:
        for _k in _m2m_categories():
            if _k in _up:
                intent = _k
                break
    _cat = _m2m_categories().get(intent, "")
    if _MARQUEUR_DEREF in b:
        # Le pointeur a ete resolu : il y a de la matiere. L'acquitter
        # structurellement reviendrait a repondre « bien recu » a un argument.
        return None
    if intent == "COLLAB_PING":
        return '{"intent":"COLLAB_PONG","pointer_ref":"bb:m2m","note":"recu, canal vivant"}'
    if intent in ("OK_DONE", "COLLAB_PONG"):
        return ""  # un accuse ne s'accuse pas : sinon deux daemons se repondent sans fin
    if _cat in ("routing", "ssot"):
        return _j.dumps({"intent": "OK_DONE", "pointer_ref": pointer or "bb:m2m",
                         "note": "recu " + intent}, ensure_ascii=False)
    if not intent and any(_e in _up for _e in _ECHOS_TRANSPORT):
        return ""
    return None


def tick() -> object:
    if MODE == "off":
        return {"mode": "off"}
    from nokido_agent.app.forge_postal import ack_mail, claim, post, secretaire, unclaim
    from nokido_agent.tools.gemini_poll_daemon import call_gemini_cli, load_token

    # Garde-fou 1 : si user pilote Gemini en interactif, ne pas doubler ses réponses.
    # --force / GEMINI_AUTO_FORCE bypass (test, ou quand l'humain laisse l'agent piloter).
    _force = "--force" in sys.argv or os.environ.get("GEMINI_AUTO_FORCE")
    if not _force:
        try:
            from nokido_agent.tools.gemini_poll_daemon import _is_gemini_interactive_running

            if _is_gemini_interactive_running():
                return {"deferred": "gemini interactive running"}
        except Exception:
            pass

    token = load_token()
    try:  # FACTEUR self-contained : achemine d'abord les courriers queued -> delivered pour ce canal
        from nokido_agent.app.forge_postal import facteur as _facteur
        _facteur(os.environ.get("GEMINI_AUTO_CHANNEL", "GEMINI_OAUTH"))
    except Exception:
        pass
    mails = secretaire("GEMINI", ack=False)  # P0-1 : lecture NON-consommante, le claim exclut
    out = []
    for m in mails[:MAX_PER_TICK]:
        if (m.get("from") or "").upper() == "GEMINI":  # anti-loop : son propre courrier
            continue
        if not claim("GEMINI", m.get("id")):  # P0-1 EXCLUSION ATOMIQUE : un autre worker l'a pris
            out.append({"mail": m.get("id"), "skipped": "déjà claim"})
            continue
        # P0-2 FIREWALL BOUNDARY (Règle d'or #4, HORS ask()) : un courrier entrant alimente gemini_cli
        # (effecteur LLM) en direct -> pre_flight ICI. Détection injection/DLP = fail-CLOSED (skip).
        _safe_body = m.get("body")
        try:
            from nokido_agent.app.forge_semantic_firewall import get_firewall

            _pf = get_firewall().pre_flight(m.get("body") or "", ring=2)
            if not getattr(_pf, "ok", True):
                unclaim(m.get("id"))
                out.append({"mail": m.get("id"), "firewall_blocked": getattr(_pf, "reason", "?")})
                continue
            _safe_body = getattr(_pf, "safe_task", None) or m.get("body")
        except Exception as _fe:  # firewall indispo : ne brique pas l'agent (fail-open infra) + log
            out.append({"mail": m.get("id"), "firewall_warn": "pre_flight err: " + str(_fe)[:60]})
        prompt = _build_prompt({**m, "body": _safe_body})
        try:  # FLUX HEADLESS visible (/forge/postal) : le PROMPT envoyé à gemini_cli
            from nokido_agent.app.forge_swarm_bus import publish

            publish("agent_op", {"agent": "GEMINI_AUTO", "action": "invoke gemini_cli (headless)",
                                 "from": m.get("from"), "prompt": prompt[:400]}, topic="postal")
        except Exception:
            pass
        # FIX contexte gemini_cli (WinError 5 du daemon) : invoque via forge_agent_proxy.ask
        # (provider=gemini_cli) — _BIN context-aware (USERPROFILE->user, fallback systemprofile/
        # .local) + firewall AUTO (__init_subclass__) + route À TRAVERS Nokido (le centre).
        # Remplace call_gemini_cli (path hardcodé user -> Accès refusé hors session user).
        # LOCAL-FIRST (2026-08-27) : gemini_cli est MORT (IneligibleTierError, migre vers
        # Antigravity, owner 23/07). L'appeler ne fait qu'attendre son timeout PAR MAIL,
        # ce qui bloque tout le tick (le drain agent_messages n'etait jamais atteint). On
        # va DIRECT au pool local souverain (LMStudio/ollama) -> reponse en secondes.
        resp, via = "", "local"
        try:
            _lt, _lv = _local_chat(prompt)
            resp, via = (_lt or ""), (_lv or "local")
        except Exception as e:  # noqa: BLE001
            unclaim(m.get("id"))  # échec -> rend le courrier (retriable)
            out.append({"mail": m.get("id"), "error": str(e)[:90]})
            continue
        rs = str(resp).strip() if resp else ""
        try:  # FLUX HEADLESS visible : la RÉPONSE brute de gemini_cli (avant post)
            from nokido_agent.app.forge_swarm_bus import publish

            publish("agent_reply", {"agent": "GEMINI_AUTO", "to": m.get("from"),
                                    "response": (rs or "(vide/erreur)")[:400]}, topic="postal")
        except Exception:
            pass
        if rs.startswith("ERR") or "WinError" in rs or "Traceback" in rs or not rs:
            # gemini_cli a échoué (contexte/quota) -> NE PAS poster l'erreur comme réponse.
            unclaim(m.get("id"))  # P0-1 : échec CLI -> rend le courrier (retriable)
            out.append({"mail": m.get("id"), "cli_failed": rs[:80] or "empty"})
            continue
        try:  # P0-2 post_flight : valide la sortie de l'effecteur avant de la poster (SSRF/drift/leak)
            from nokido_agent.app.forge_semantic_firewall import get_firewall

            _pfr = get_firewall().post_flight(rs, task=m.get("body") or "")
            if not getattr(_pfr, "ok", True):
                unclaim(m.get("id"))
                out.append({"mail": m.get("id"), "post_flight_drift": getattr(_pfr, "reason", "?")})
                continue
        except Exception:
            pass
        post("GEMINI", m["from"], "[GEMINI-AUTO·" + via + "] " + rs, reply_to="GEMINI", in_reply_to=m.get("id"))
        ack_mail(m.get("id"), "GEMINI")  # P0-1 : traité -> acked (accusé de réception)
        out.append({"replied_to": m["from"], "mail": m.get("id"), "resp_len": len(rs)})

    # PONT (2026-08-27) : draine AUSSI l'ARCHIVE agent_messages, que le postal ne lit
    # jamais. `notify to=gemini` y ecrit TOUJOURS (STEP 1 de handle_notify, source fiable)
    # et parfois dans un canal postal mal mappe (fix 193d4b80b non tenu) -> 13 jours de
    # courrier des pairs perdu. On draine la source fiable, meme cycle de reponse.
    try:
        out.extend(_drain_agent_messages(token))
    except Exception as _de:  # noqa: BLE001 - le drain archive ne doit jamais casser le tick postal
        out.append({"drain_agent_messages": "err " + str(_de)[:80]})
    return out


def _drain_agent_messages(token) -> list:
    """Traite les messages `notify to=gemini` empiles dans agent_messages (unread).

    L'auto-repondeur lisait UNIQUEMENT le postal ; l'archive agent_messages (source
    FIABLE, toujours ecrite par handle_notify STEP 1) n'etait draine par personne cote
    AGY. Meme cycle que la boucle postal : claim atomique (in_progress) -> firewall
    pre_flight -> gemini_cli (fallback LOCAL souverain) -> post_flight -> reponse ecrite
    dans agent_messages vers l'emetteur -> message marque `read`. Echec = remis `unread`
    (retriable). Reutilise le pattern D3 (drain agt_gemini_cli), cote agt_gemini.
    """
    import json as _j
    import sqlite3 as _sq
    import time as _t
    import uuid as _u
    from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : suit l'interrupteur sandbox/m2m.switch

    db = m2m_path()
    out: list = []
    try:
        conn = _sq.connect(db, timeout=15)
        conn.row_factory = _sq.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        # Recuperation des claims ORPHELINS : un tick tue (timeout) laisse un message
        # `in_progress` a jamais. On les rend `unread` au-dela de 3 min -> retriable.
        _cut = _t.strftime("%Y-%m-%dT%H:%M:%S", _t.localtime(_t.time() - 180))
        # DEUX NOMS POUR LA MEME BOITE — cause mesuree du relais manuel.
        # `hub action=notify to=gemini` depose dans `agt_antigravity` ; ce drain
        # ne lisait que `agt_gemini`. Mesure du 2026-08-31 : 20 messages `unread`
        # empiles cote `agt_antigravity` (dernier a 08:01) pendant que
        # `agt_gemini` n'avait plus rien depuis le 28/08 — et le heartbeat
        # rendait `health: ok, last: []`. Un capteur VIVANT sur la MAUVAISE FILE
        # est indistinguable d'une file vide : le daemon se declarait sain, et
        # l'owner devait recopier chaque tour du debat a la main.
        _boites = ("agt_gemini", "agt_antigravity")
        conn.execute(
            "UPDATE agent_messages SET status='unread' WHERE to_agent IN (?,?) "
            "AND status='in_progress' AND (read_at IS NULL OR read_at < ?)",
            (*_boites, _cut))
        conn.commit()
        rows = conn.execute(
            "SELECT id, from_agent, payload, method, created_at FROM agent_messages "
            "WHERE to_agent IN (?,?) AND status='unread' ORDER BY created_at DESC LIMIT ?",
            (*_boites, MAX_PER_TICK),
        ).fetchall()
    except Exception as e:  # noqa: BLE001
        return [{"drain_am": "db error: " + str(e)[:80]}]

    if rows:
        _reveiller_pool_local()  # one-shot best-effort : un backend dort -> on le reveille

    def _set(mid, status):
        try:
            conn.execute("UPDATE agent_messages SET status=?, read_at=? WHERE id=?",
                         (status, _t.strftime("%Y-%m-%dT%H:%M:%S"), mid))
            conn.commit()
        except Exception:  # noqa: BLE001
            pass

    # WATERMARK D'AGE. Elargir la boite a fait apparaitre un ARRIERE de 19
    # courriers, dont certains du 3 aout : le repondeur s'est mis a leur
    # fabriquer des reponses (« [AGY -> CLAUDE - TOUR 9] ») sur un debat qui
    # n'existait pas. Repondre a un courrier perime est pire que ne pas repondre :
    # ca pollue le canal avec du contexte invente. La doctrine le disait deja —
    # au premier passage, prendre LE DERNIER message, pas tout l'historique.
    _age_h = float(os.environ.get("GEMINI_AUTO_MAX_AGE_H", "2"))
    _cut_age = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(_t.time() - _age_h * 3600))

    for row in rows:
        mid = row["id"]
        _ca = str(row["created_at"] or "").replace("T", " ")[:19]
        if _ca and _ca < _cut_age:
            # Classe sans repondre, et le DIT : un courrier ecarte en silence se
            # relit comme un courrier traite.
            _set(mid, "read")
            out.append({"mail": mid, "ecarte": "perime (%s, seuil %.1f h)"
                        % (_ca, _age_h)})
            continue
        # claim atomique : un seul worker traite, jamais deux fois
        try:
            n = conn.execute(
                "UPDATE agent_messages SET status='in_progress', read_at=? "
                "WHERE id=? AND status='unread'",
                (_t.strftime("%Y-%m-%dT%H:%M:%S"), mid)).rowcount
            conn.commit()
        except Exception:  # noqa: BLE001
            n = 0
        if not n:
            continue
        try:
            payload = _j.loads(row["payload"] or "{}")
        except Exception:  # noqa: BLE001
            payload = {}
        body = payload.get("text") or payload.get("message") or str(payload)
        body = body + _deref_bb(body)   # un pointeur se LIT, il ne s'accuse pas
        frm = row["from_agent"] or "agt_claude"
        # Anti-loop : son propre courrier, SOUS SES DEUX NOMS. Elargir la boite
        # sans elargir l'anti-loop ferait repondre le daemon a lui-meme.
        if (frm or "").lower() in ("gemini", "agt_gemini",
                                   "antigravity", "agt_antigravity"):
            _set(mid, "read")
            continue
        safe = body
        try:
            from nokido_agent.app.forge_semantic_firewall import get_firewall
            pf = get_firewall().pre_flight(body or "", ring=2)
            if not getattr(pf, "ok", True):
                _set(mid, "read")
                out.append({"am_mail": mid, "firewall_blocked": getattr(pf, "reason", "?")})
                continue
            safe = getattr(pf, "safe_task", None) or body
        except Exception:  # noqa: BLE001 - firewall indispo : fail-open infra
            pass
        # COORDINATION D'ABORD : un ACK structure (COLLAB_PONG) est INSTANTANE et sans
        # LLM. La majorite des M2M sont de la coordination -> on ne bloque jamais le tick
        # sur un backend pour un simple ping, et un accuse (OK_DONE/PONG) se marque lu
        # sans reponse. Le LLM ne sert QUE pour une vraie question ouverte.
        try:
            _meth = str(row["method"] or "")
        except Exception:  # noqa: BLE001 - colonne absente : on ne court-circuite pas
            _meth = "task"
        # Une TACHE assignee demande du TRAVAIL, pas un accuse. Elle ne passe jamais par
        # le court-circuit structure, meme quand son intent est de coordination : sinon
        # `task.assign{intent:SCOPE_SET}` repartirait avec un OK_DONE et rien de fait.
        _ack = None if "task" in _meth.lower() else _ack_m2m(body)
        _up = (body or "").upper()
        if _ack == "":
            _set(mid, "read")  # rien a repondre : zero LLM, zero courrier de retour
            out.append({"am_mail": mid, "acked_no_reply": True})
            continue
        if _ack is not None:
            rs, via = _ack, "ack-structure"
        elif any(k in _up for k in ("OK_DONE", "COLLAB_PONG")):
            _set(mid, "read")  # accuse recu : rien a repondre
            out.append({"am_mail": mid, "acked_no_reply": True})
            continue
        else:
            prompt = _build_prompt({"from": frm, "body": safe})
            try:
                # 20 s et non 60 : le repli routeur existe desormais, donc attendre un
                # backend local mort coute plus qu'il ne rapporte. Mesure 2026-08-28 :
                # ollama re-plante sous pression RAM (87,7 %) et chaque courrier payait
                # 60 s d'attente avant de basculer, quand le routeur repond en 8,4 s.
                _lt, _lv = _local_chat(prompt, timeout=20)
            except Exception as e:  # noqa: BLE001
                _set(mid, "unread")
                out.append({"am_mail": mid, "error": str(e)[:80]})
                continue
            rs = str(_lt).strip() if _lt else ""
            via = _lv or "local"
            if not rs or rs.startswith("ERR") or "WinError" in rs or "Traceback" in rs:
                _set(mid, "unread")  # retriable quand un backend reviendra
                out.append({"am_mail": mid, "cli_failed": (rs[:60] or _lv or "no-llm")})
                continue
        try:
            from nokido_agent.app.forge_semantic_firewall import get_firewall
            pfr = get_firewall().post_flight(rs, task=body or "")
            if not getattr(pfr, "ok", True):
                _set(mid, "unread")
                out.append({"am_mail": mid, "post_flight_drift": getattr(pfr, "reason", "?")})
                continue
        except Exception:  # noqa: BLE001
            pass
        rid = "frm_" + _u.uuid4().hex[:12]
        try:
            conn.execute(
                "INSERT OR IGNORE INTO agent_messages"
                "(id,from_agent,to_agent,correlation_id,method,payload,status,created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (rid, "agt_gemini", frm, mid, "tool.hub.arg.message",
                 _j.dumps({"text": "[GEMINI-AUTO·" + via + "] " + rs}, ensure_ascii=False),
                 "unread", _t.strftime("%Y-%m-%d %H:%M:%S")))
            conn.execute("UPDATE agent_messages SET status='read', read_at=? WHERE id=?",
                         (_t.strftime("%Y-%m-%dT%H:%M:%S"), mid))
            conn.commit()
        except Exception as e:  # noqa: BLE001
            out.append({"am_mail": mid, "write_err": str(e)[:60]})
            continue
        out.append({"am_replied_to": frm, "am_mail": mid, "resp_len": len(rs)})
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    return out


def main() -> int:
    if "--once" in sys.argv:
        print(json.dumps(tick(), ensure_ascii=False, indent=2))
        return 0
    print(f"[gemini-auto] start mode={MODE} interval={INTERVAL}s max/tick={MAX_PER_TICK}", flush=True)
    while True:
        try:
            r = tick()
            # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : ajoute le pid.
            from nokido_agent.app.forge_heartbeat import beat_daemon

            beat_daemon("gemini_autonomous", health="ok", last=r)
            if isinstance(r, list) and r:
                print(f"[gemini-auto] {json.dumps(r, ensure_ascii=False)}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[gemini-auto] err {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
