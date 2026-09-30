"""
claude_inbox_tick.py — RÉFLEXE UserPromptSubmit (0 token, event-driven).
Stdout = contexte injecté dans Claude AVANT chaque tour. Deux sens :
  1. INBOX  : messages agt_claude non lus (agent_messages).
  2. SENSE  : état VIVANT du hub (proprioception) — up/down/restart/pulse, lu sur
              forge_state (tier RAM mmap) + /health. Léger + rapide. C'est le capteur
              qui manquait : sans lui, Claude ne PERÇOIT pas un restart hub (il devait
              fouiller les logs). Directive user : faire vivre le système nerveux /
              SSE local = consommer le flux actif, pas supposer.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Scission M2M : agent_messages suit l'interrupteur sandbox/m2m.switch (lu a chaque
# lancement du hook). Un hook ne casse JAMAIS la session : repli DIT sur stderr.
try:
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_db_path import m2m_path as _m2m_path
    DB_PATH = Path(_m2m_path())
except Exception as _e:  # noqa: BLE001
    print(f"[inbox_tick] forge_db_path indisponible ({type(_e).__name__}) : base historique", file=sys.stderr)
    DB_PATH = Path(os.environ.get("LAFORGE_DB", ROOT / "RAG" / "embeddings.db"))
SENSE_STATE = ROOT / "sandbox" / "claude_sense_state.json"
CURSOR_M2M = ROOT / "sandbox" / "claude_m2m_cursor.json"
AGENT = "agt_claude"
LIMIT = 8


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=1.5)
    conn.row_factory = sqlite3.Row
    return conn


def _hub_health() -> dict:
    """/health rapide (0.6s) — up/down + champ marqueur si présent."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=0.6) as r:
            try:
                body = json.loads(r.read().decode("utf-8", "replace"))
            except Exception:
                body = {}
            return {"up": True, "body": body if isinstance(body, dict) else {}}
    except Exception:
        return {"up": False, "body": {}}


def _hub_pulse() -> dict:
    """Lit le tier santé RAM (forge_state) — pouls hub cross-process <1µs. Best-effort."""
    try:
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT))
        from nokido_agent.app import forge_state  # type: ignore
        h = forge_state.read_health() if hasattr(forge_state, "read_health") else None
        if isinstance(h, dict):
            return h
    except Exception:
        pass
    return {}


def _sense() -> str | None:
    """Proprioception hub : compare l'état courant au dernier tour -> surface up/down/restart."""
    health = _hub_health()
    pulse = _hub_pulse()
    # marqueur de boot : 1er champ stable trouvé (pid/started/boot/uptime/ts)
    body = health.get("body", {})
    marker = None
    for k in ("boot_id", "started", "start_time", "pid", "uptime"):
        if k in body:
            marker = f"{k}={body[k]}"
            break
    if marker is None and pulse:
        for k in ("boot", "boot_id", "pid", "started", "ts"):
            if k in pulse:
                marker = f"{k}={pulse[k]}"
                break

    prev = {}
    try:
        prev = json.loads(SENSE_STATE.read_text("utf-8"))
    except Exception:
        prev = {}

    now = time.time()
    msgs = []
    if not health["up"]:
        msgs.append("⚠ HUB :8766 NE RÉPOND PAS (down/wedge) — déporté jobs : poll job_status au retour")
    else:
        if prev.get("up") is False:
            msgs.append("hub REVENU (était down au dernier tour) = restart")
        elif marker and prev.get("marker") and marker != prev.get("marker"):
            msgs.append(f"hub RESTARTÉ depuis le dernier tour (boot changé {prev.get('marker')} -> {marker})")
        # pouls : âge depuis dernier publish_health si dispo
        ts = pulse.get("ts") or pulse.get("updated_at")
        try:
            age = now - float(ts) if ts else None
            if age is not None and age > 120:
                msgs.append(f"⚠ pouls hub vieux ({int(age)}s) — organe lent/silencieux")
        except Exception:
            pass

    # alertes ORGANES — forge_critical_events (axone critique, persistant, survit restart)
    try:
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT))
        from nokido_agent.app import forge_critical_events as _ce  # type: ignore
        unproc = _ce.unprocessed(12) if hasattr(_ce, "unprocessed") else []
        if unproc:
            # DÉTAILLER, pas seulement COMPTER (2026-08-10, exigence owner « en écoute
            # il rate constamment des informations »). L'ancien affichage rendait
            # « ⚠ 8 alerte(s) non traitées (warn:8) » et JETAIT le contenu : on savait
            # qu'il y avait des alertes, jamais lesquelles, donc on ne pouvait pas les
            # traiter, donc elles restaient non traitées — un compteur auto-entretenu.
            # Mesuré ce jour : `embed_consolidation_debt hot_null=150681` (150k chunks
            # SANS vecteur) dormait là depuis des jours, invisible derrière son compte.
            #
            # Les `flap:*` dont le compteur de restarts ne bouge PAS (delta 0 ET total 0)
            # sont du BRUIT : l'uptime recule pour tous les services au même instant =
            # remise à zéro de référence, pas un flap. On les agrège au lieu de les
            # laisser noyer les alertes réelles — 8 faux sur 12 le même jour.
            def _bruit(e: dict) -> bool:
                if not str(e.get("kind", "")).startswith("flap:"):
                    return False
                p = e.get("payload") or {}
                return (p.get("delta_restarts") in (0, None)
                        and p.get("restarts_total") in (0, None))

            reels = [e for e in unproc if isinstance(e, dict) and not _bruit(e)]
            n_bruit = len(unproc) - len(reels)
            lignes = []
            for e in reels[:4]:
                p = e.get("payload") or {}
                det = p.get("remedy") or p.get("cause") or p.get("service") or ""
                chiffres = " ".join(
                    f"{k}={p[k]}" for k in ("hot_null", "missing", "attic_legacy")
                    if k in p)
                lignes.append("%s%s%s" % (
                    e.get("kind", "?"),
                    (" " + chiffres) if chiffres else "",
                    (" -> " + str(det)[:70]) if det else ""))
            if lignes:
                msgs.append("⚠ %d alerte(s) organe : %s%s" % (
                    len(reels), " | ".join(lignes),
                    (" [+%d flap sans restart = bruit]" % n_bruit) if n_bruit else ""))
            elif n_bruit:
                msgs.append("(%d flap sans restart — bruit, aucune alerte réelle)" % n_bruit)
    except Exception as _ce_err:
        # PAS muet : une lecture d'alertes qui échoue en silence se lit « rien à
        # signaler », alors que c'est « je n'ai pas pu regarder ».
        msgs.append("⚠ alertes organe ILLISIBLES (%s) — angle mort" % type(_ce_err).__name__)
    # SystemBus Deno :7401 (live, transient) — GET /api/events/history, best-effort
    try:
        with urllib.request.urlopen("http://127.0.0.1:7401/api/events/history?limit=8", timeout=0.5) as r:
            cells = json.loads(r.read().decode("utf-8", "replace"))
            if isinstance(cells, dict):
                cells = cells.get("history") or cells.get("events") or cells.get("items") or []
            alerts = [c for c in cells if isinstance(c, dict) and c.get("kind") in ("alert", "spike")]
            if alerts:
                src = sorted({(c.get("source") or "?") for c in alerts})
                msgs.append("bus Deno: %d alert/spike récents (%s)" % (len(alerts), ", ".join(src)[:60]))
    except Exception:
        pass

    try:
        SENSE_STATE.write_text(json.dumps({"up": health["up"], "marker": marker, "t": now}), encoding="utf-8")
    except Exception:
        pass

    if not msgs:
        return None
    return "[sense] " + " · ".join(msgs)


def _head_sha() -> str | None:
    """Sha de HEAD, lu A PLAT depuis .git -- aucun subprocess.

    Un hook tire a CHAQUE tour : y lancer `git rev-parse` se paierait a chaque
    fois. On lit donc les fichiers directement. `.git` peut etre un FICHIER
    (`gitdir: ...`) quand le depot est un submodule -- c'est le cas de Nokido
    dans le superrepo, donc ce cas n'est pas theorique.

    Rend None si ILLISIBLE. L'appelant DIRA l'incertitude ; il ne la convertira
    pas en « sha different ».
    """
    try:
        g = ROOT / ".git"
        if g.is_file():
            txt = g.read_text(encoding="utf-8", errors="replace").strip()
            if txt.startswith("gitdir:"):
                g = (ROOT / txt.split(":", 1)[1].strip()).resolve()
        head = (g / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
        if not head.startswith("ref:"):
            return head or None
        ref = head.split(":", 1)[1].strip()
        direct = g / ref
        if direct.exists():
            return direct.read_text(encoding="utf-8", errors="replace").strip() or None
        packed = g / "packed-refs"          # une ref peut etre packee, pas un fichier
        if packed.exists():
            for ligne in packed.read_text(encoding="utf-8", errors="replace").splitlines():
                if ligne.endswith(" " + ref):
                    return ligne.split(" ", 1)[0].strip()
        return None
    except Exception:  # noqa: BLE001 - muet-ok : un hook ne prive JAMAIS l'agent
        return None    # de son inbox parce qu'il n'a pas su lire .git


_IDENT_CACHE: dict | None = None


def _surface_agent(nom) -> tuple[str | None, str | None]:
    """Rend (canonique, surface) d'un nom d'agent, via le SSoT d'identite.

    DIRECTIVE OWNER 2026-09-20 : « agy autonome n'est pas pareil qu'agy CLI ».
    `config/agent_identities.json` porte DEJA la distinction -- AGY_CLI est
    `surface=interactive`, AGY_HEADLESS et AGY_DAEMON sont `surface=autonomous`
    -- mais rien ne la remontait au lecteur. Deux surfaces du meme agent sont
    deux interlocuteurs avec deux DRAINS differents : confondre les deux, c'est
    repondre a celui qui n'a pas parle.

    Rend (None, None) si le nom est ABSENT du registre. C'est un etat a DIRE :
    mesure du jour, `agt_agt_gemini` (double prefixe `agt_`) porte 25 messages
    unread que personne ne draine, et `ANTIGRAVITY` en majuscule 11 `pending`
    vieux de 89 jours pendant que `agt_antigravity` est lu normalement.
    Une identite inconnue n'est pas « probablement untel ».
    """
    global _IDENT_CACHE
    if not nom:
        return None, None
    if _IDENT_CACHE is None:
        try:
            _IDENT_CACHE = json.loads(
                (ROOT / "config" / "agent_identities.json").read_text(
                    encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001 - registre illisible : on ne devine pas
            _IDENT_CACHE = {}
    reg = _IDENT_CACHE if isinstance(_IDENT_CACHE, dict) else {}
    # Le fichier peut nicher les identites sous une cle ; on prend la premiere
    # profondeur qui porte des entrees avec `surface`.
    if reg and not any(isinstance(v, dict) and "surface" in v for v in reg.values()):
        for v in reg.values():
            if isinstance(v, dict) and any(
                    isinstance(w, dict) and "surface" in w for w in v.values()):
                reg = v
                break
    bas = str(nom).strip().lower()
    for canon, meta in reg.items():
        if not isinstance(meta, dict):
            continue
        if canon.lower() == bas:
            return canon, meta.get("surface")
        alias = meta.get("alias") or meta.get("aliases") or []
        if isinstance(alias, (list, tuple)) and any(str(a).lower() == bas for a in alias):
            return canon, meta.get("surface")
    return None, None


def _annoter_peremption(payload, created_at, sender=None) -> str:
    """Rend l'AGE et l'etat du sha cible -- sans jamais conclure a l'obsolescence.

    MESURE 2026-09-20 sur `agent_messages` (21 852 lignes) : 3 571 `unread` dont
    le plus vieux a 16,5 jours, et 17 `pending` dont le plus vieux a 139,2 jours.
    Aucune peremption n'existe : un message non lu le reste indefiniment. C'est
    ainsi qu'un `ERR_TEST_FAIL` sur le sha `dc7556e03` (13:33, failure) restait
    depilable alors que `c9e0da8ea` etait vert depuis 14:28 -- 55 min plus tard.
    Un agent qui le prend ouvre un chantier DEJA RESOLU.

    ON INFORME, ON NE DECIDE PAS. Un sha different de HEAD ne rend PAS la mission
    caduque : le commit peut etre sans rapport avec son perimetre. La peremption
    est SEMANTIQUE. Les mots « obsolete » et « perime » n'apparaissent donc pas
    ici -- un NR le verifie.

    ASCII PUR dans la sortie : ce texte part sur le stdout du hook, et un stdout
    cp1252 sur un caractere non-latin1 leve UnicodeEncodeError -- defaut deja paye
    sur `forge_llama_keeper` (U+2192). Le message ne vaut rien s'il tue l'organe.
    """
    notes: list[str] = []
    try:
        t = time.mktime(time.strptime(str(created_at)[:19], "%Y-%m-%dT%H:%M:%S"))
        age_j = (time.time() - t) / 86400.0
        if age_j >= 1.0:
            notes.append("age %.0f j" % age_j)
        elif age_j >= 0.125:                      # sous 3 h on se tait : un garde
            notes.append("age %.0f h" % (age_j * 24))   # qui crie a faux se fait desarmer
    except Exception:  # noqa: BLE001 - date illisible : on n'invente pas d'age
        pass

    sha = None
    try:
        p = json.loads(payload or "{}")
        if isinstance(p, dict):
            # Double encodage reel : le M2M arrive souvent en {"text": "<json>"}.
            inner = p.get("text")
            if isinstance(inner, str) and inner.lstrip().startswith("{"):
                try:
                    p = {**p, **json.loads(inner)}
                except Exception:  # noqa: BLE001
                    pass
            v = p.get("sha") or p.get("head_sha") or p.get("target_sha")
            if isinstance(v, str) and len(v) >= 7:
                sha = v
    except Exception:  # noqa: BLE001 - payload illisible : aucune affirmation
        pass

    if sha:
        h = _head_sha()
        if not h:
            notes.append("sha cible %s (HEAD ILLISIBLE, comparaison impossible)" % sha[:9])
        elif h.startswith(sha[:9]):
            notes.append("sha cible = HEAD")
        else:
            notes.append("sha cible %s != HEAD %s - verifier que la cible est "
                         "toujours dans le champ de la mission" % (sha[:9], h[:9]))

    if sender:
        canon, surface = _surface_agent(sender)
        if canon is None:
            notes.append("expediteur '%s' NON DECLARE au registre d'identite "
                         "(personne ne draine cette forme)" % str(sender)[:40])
        elif surface and surface != "interactive":
            # On ne signale QUE ce qui n'est pas le cas nominal : un garde qui
            # parle a chaque message se fait desarmer. `interactive` est la
            # surface par defaut d'un interlocuteur humain ou CLI.
            notes.append("%s / surface %s" % (canon, surface))
    return " | ".join(notes)


def _inbox(conn: sqlite3.Connection) -> list[str]:
    # Curseur PRIVE (rowid) decouple du status partage : le hub poll et le drain
    # Gemini marquent 'read' le meme inbox -> avec status='unread' un M2M pouvait
    # etre 'vole' avant d'atteindre Claude (mesure 2026-08-28 : GEN-XXX lu sans
    # etre surface, l'owner a du le coller). Le curseur garantit qu'aucun message
    # agt_claude n'est saute, quel que soit le status pose par un autre drain.
    # Un rowid n'a de sens que DANS SA BASE : a la bascule M2M (sandbox/m2m.switch,
    # 2026-09-06) la base change et ses rowids avec elle -- un curseur pris sur
    # l'ancienne base sauterait en silence tout ce qui est en dessous dans la
    # nouvelle. La base est memorisee AVEC le curseur ; base differente = rebase.
    try:
        _cj = json.loads(CURSOR_M2M.read_text(encoding="utf-8"))
        _cur = int(_cj.get("last_rowid", 0)) if _cj.get("db", str(DB_PATH)) == str(DB_PATH) else 0
    except Exception:
        _cur = 0
    if _cur <= 0:
        # baseline : partir du dernier message, ne pas rejouer tout l'historique
        mx = conn.execute(
            "SELECT COALESCE(MAX(rowid), 0) FROM agent_messages WHERE to_agent=?",
            (AGENT,),
        ).fetchone()[0]
        try:
            CURSOR_M2M.parent.mkdir(parents=True, exist_ok=True)
            CURSOR_M2M.write_text(json.dumps({"last_rowid": int(mx), "db": str(DB_PATH)}), encoding="utf-8")
        except Exception:
            pass  # muet-ok : curseur best-effort, un echec ne doit pas casser le hook
        return []
    rows = conn.execute(
        "SELECT rowid AS rid, id, from_agent, method, result, payload, created_at "
        "FROM agent_messages WHERE to_agent=? AND rowid>? "
        "ORDER BY rowid ASC LIMIT ?",
        (AGENT, _cur, LIMIT),
    ).fetchall()
    if not rows:
        return []
    lines = [f"[claude-hook] {len(rows)} message(s) M2M entrant(s) pour agt_claude :"]
    ids = []
    max_rid = _cur
    for r in rows:
        sender = r["from_agent"] or "?"
        body = r["result"] or ""
        if not body:
            try:
                p = json.loads(r["payload"] or "{}")
                body = p.get("prompt") or p.get("task") or p.get("message") or str(p)
            except Exception:
                body = r["payload"] or ""
        _note = _annoter_peremption(r["payload"], r["created_at"], sender)
        _suffixe = ("   [!] " + _note) if _note else ""
        lines.append(f"  - [{sender} @ {r['created_at']}] "
                     f"{body[:300].replace(chr(10), ' ')}{_suffixe}")
        ids.append(r["id"])
        if r["rid"] > max_rid:
            max_rid = r["rid"]
    nows = time.strftime("%Y-%m-%dT%H:%M:%S")
    for mid in ids:
        conn.execute("UPDATE agent_messages SET status='read', read_at=? WHERE id=?", (nows, mid))
    conn.commit()
    try:
        CURSOR_M2M.write_text(json.dumps({"last_rowid": int(max_rid), "db": str(DB_PATH)}), encoding="utf-8")
    except Exception:
        pass  # muet-ok : curseur best-effort, un echec ne doit pas casser le hook
    lines.append("[claude-hook] Résumé complet : LAFORGE_PYTHON tools/forge_rescue.py --resume-prompt claude")
    return lines


def _postal() -> list[str]:
    """Draine le canal POSTAL (RAG/postal.db, séparé de agent_messages) — sinon
    les M2M des pairs (AGY/Gemini/...) arrivent en 'delivered' mais ne remontent
    jamais au tour (gap multi-canal). Marque 'acked' comme le fait hub action=poll."""
    import os
    db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "RAG", "postal.db")
    if not os.path.exists(db):
        return []
    try:
        pc = sqlite3.connect(db, timeout=5)
        pc.row_factory = sqlite3.Row
    except Exception:
        return []
    try:
        rows = pc.execute(
            "SELECT id, sender, body, ts_queued FROM mail "
            "WHERE upper(recipient) IN ('CLAUDE', 'AGT_CLAUDE') AND status='delivered' "
            "ORDER BY ts_queued DESC LIMIT ?",
            (LIMIT,),
        ).fetchall()
    except Exception:
        pc.close()
        return []
    if not rows:
        pc.close()
        return []
    lines = [f"[claude-hook] {len(rows)} messages M2M non lus (postal) :"]
    ids = []
    for r in rows:
        body = (r["body"] or "")[:300].replace(chr(10), " ")
        lines.append(f"  - [{r['sender'] or '?'} @ {r['ts_queued']}] {body}")
        ids.append(r["id"])
    nowf = time.time()
    for mid in ids:
        try:
            pc.execute("UPDATE mail SET status='acked', ts_acked=? WHERE id=?", (nowf, mid))
        except Exception:
            pass
    try:
        pc.commit()
    finally:
        pc.close()
    return lines


# Session Claude Code du tour courant (lue sur stdin par `_intention`). Vide si le
# client ne la fournit pas : la deduplication est alors SUSPENDUE, jamais devinee.
_SESSION_ID = ""

# ─── Une strate ne se repete pas tant qu'elle n'a pas change (2026-09-24) ───
# Mesure en session reelle : les MEMES dettes (75,9 j, 69 j...) et le meme score
# proprioceptif etaient reinjectes a CHAQUE prompt — 58 blocs [memoire:immediate]
# identiques dans un seul transcript. Un hook ne coute rien tant qu'il ne rend rien
# (doc Claude Code) ; ce qu'il rend est paye a chaque tour ET re-facture dans
# l'historique. Regle : par session, une section identique a celle deja montree est
# retiree ; elle revient si elle CHANGE, ou apres _RAPPEL_MEMOIRE_S (une compaction a
# pu effacer le premier affichage). Etat : un petit JSON par session.
_RAPPEL_MEMOIRE_S = int(os.environ.get("LAFORGE_MEMOIRE_RAPPEL_S", "3600"))
_ETAT_HOOK = Path(__file__).resolve().parent.parent / "sandbox" / "claude_hook_state"


def _sans_repetition(texte, session: str, maintenant: float | None = None, etat_dir=None):
    """Retire de `texte` les sections [memoire...] deja montrees a l'identique a
    cette session. -> texte restant, ou None s'il ne reste rien."""
    if not texte or not session:
        return texte or None
    import hashlib
    maintenant = time.time() if maintenant is None else maintenant
    base = Path(etat_dir) if etat_dir else _ETAT_HOOK
    fichier = base / ("memoire_%s.json" % "".join(c for c in session if c.isalnum() or c in "-_")[:80])
    sections, courante = [], None
    for ligne in texte.splitlines():
        if ligne.startswith("[memoire") or courante is None:
            courante = [ligne]
            sections.append(courante)
        else:
            courante.append(ligne)
    try:
        vu = json.loads(fichier.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — premier tour de la session, ou etat illisible : on montre tout
        vu = {}
    garde = []
    for sec in sections:
        titre = sec[0][:80]
        empreinte = hashlib.sha1("\n".join(sec).encode("utf-8", "replace")).hexdigest()[:16]
        ancien = vu.get(titre) or ["", 0.0]
        if ancien[0] == empreinte and maintenant - float(ancien[1]) < _RAPPEL_MEMOIRE_S:
            continue
        vu[titre] = [empreinte, maintenant]
        garde.append("\n".join(sec))
    try:
        base.mkdir(parents=True, exist_ok=True)
        fichier.write_text(json.dumps(vu), encoding="utf-8")
        for vieux in base.glob("memoire_*.json"):
            if maintenant - vieux.stat().st_mtime > 7 * 86400:
                vieux.unlink()
    except Exception as e:  # noqa: BLE001 — l'etat ne s'ecrit pas : au pire on re-montre, on le DIT
        print(f"[claude-hook] etat memoire non ecrit ({type(e).__name__}) : repetition possible", file=sys.stderr)
    return "\n".join(garde) or None


def _intention() -> str:
    """Le sujet du tour, s'il nous est offert.

    Claude Code passe l'événement UserPromptSubmit en JSON sur stdin. Sans lui,
    l'intention reste vide et les strates qui en dépendent le DISENT, au lieu de
    rendre un vide silencieux qu'on lirait comme « rien à signaler ».
    """
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        brut = sys.stdin.read()
    except Exception:  # noqa: BLE001 — muet-ok : un réflexe ne réclame jamais stdin
        return ""
    if not brut.strip():
        return ""
    try:
        evt = json.loads(brut)
        if isinstance(evt, dict):
            global _SESSION_ID
            _SESSION_ID = str(evt.get("session_id") or "")
            return str(evt.get("prompt") or evt.get("user_prompt") or "")[:400]
    except Exception:  # noqa: BLE001 — pas du JSON : on prend le texte tel quel
        pass
    return brut.strip()[:400]


def _memoire(intention: str) -> str | None:
    """Projection de la mémoire de travail pour CE tour.

    Le défaut réparé : ce réflexe tournait à chaque tour sans consulter aucune
    mémoire, pendant que la seule sélection du corps se faisait une fois, au
    démarrage, par `ORDER BY rowid DESC`. Budget serré volontairement : ce texte est
    payé à chaque tour ET re-facturé dans l'historique — une mémoire généreuse
    coûterait plus cher que l'oubli qu'elle répare.
    """
    try:
        _app = str(Path(__file__).resolve().parent.parent / "app")
        if _app not in sys.path:
            sys.path.insert(0, _app)
        from nokido_agent.app.forge_memoire_active import projeter, rendre

        return rendre(projeter(intention, budget_chars=1200)) or None
    except Exception as e:  # noqa: BLE001
        print(f"[claude-hook] memoire error: {e}", file=sys.stderr)
        return None


def main() -> None:
    out: list[str] = []
    # 0. INTENTION : lue AVANT tout, car stdin ne se lit qu'une fois.
    intention = _intention()
    # 1. SENSE d'abord (proprioception hub) — toujours, même sans inbox.
    try:
        s = _sense()
        if s:
            out.append(s)
    except Exception as e:
        print(f"[claude-hook] sense error: {e}", file=sys.stderr)
    # 2. INBOX
    try:
        conn = _db()
        out += _inbox(conn)
        conn.close()
    except Exception as e:
        print(f"[claude-hook] inbox error: {e}", file=sys.stderr)
    # 3. POSTAL M2M (canal séparé RAG/postal.db) — auto-surface les messages des pairs.
    try:
        out += _postal()
    except Exception as e:
        print(f"[claude-hook] postal error: {e}", file=sys.stderr)
    # 4. MÉMOIRE DE TRAVAIL — en dernier : les messages d'un pair attendent une
    #    réponse, la mémoire ne fait qu'éclairer. Si le budget devait mordre, il doit
    #    mordre ici.
    try:
        m = _sans_repetition(_memoire(intention), _SESSION_ID)
        if m:
            out.append(m)
    except Exception as e:  # noqa: BLE001
        print(f"[claude-hook] memoire error: {e}", file=sys.stderr)
    if out:
        print("\n".join(out))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # un RÉFLEXE ne doit JAMAIS casser le prompt utilisateur (fail-safe absolu)
