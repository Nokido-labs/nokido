#!/usr/bin/env python3
"""
claude_precompact.py — Hook PreCompact Claude Code
===================================================
Déclenché juste avant que Claude Code compacte le contexte.

Pipeline :
  1. Lire stdin JSON (PreCompactHookInput: session_id, transcript_path, ...)
  2. Charger transcript → extraire turns utilisables
  3. Purger : stack traces > 10 lignes, schemas JSON tools (garder nom+statut)
  4. Appeler Groq (llama-3.3-70b-versatile) → résumé JSON structuré
  5. Stocker dans rag_chunks(domain='session_summary')
  6. Mettre à jour claude_session_start context (CONTEXT_SUMMARY.md)
  7. Exit 0 → laisser compaction se dérouler

Exit 2 ou {"decision":"block"} → bloque la compaction (pas utilisé ici).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB = "http://127.0.0.1:8766/mcp"
DB = ROOT / "RAG" / "embeddings.db"
SUMMARY = ROOT / "CONTEXT_SUMMARY.md"

# Source unique pour le parsing — pas de re-implémentation inline
sys.path.insert(0, str(ROOT))
# Scission M2M : agent_messages suit l'interrupteur sandbox/m2m.switch ; DB reste la
# base du RAG pour rag_chunks. Un hook ne casse jamais la session : repli DIT.
try:
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_db_path import m2m_path as _m2m_path
    M2M = Path(_m2m_path())
except Exception as _e:  # noqa: BLE001
    print(f"[precompact] forge_db_path indisponible ({type(_e).__name__}) : base historique", file=sys.stderr)
    M2M = DB
from nokido_agent.tools.cli_capture_lib import normalize_anthropic_content  # type: ignore

MAX_TURNS = 40  # tours max à analyser
MAX_CHARS_TURN = 800  # tronque chaque tour à N chars
STACK_KEEP_LINES = 10  # lignes max par stack trace
MAX_PAYLOAD_CHARS = 12000  # payload max envoyé à Groq

GROQ_KEY = ""


def _load_env() -> None:
    global GROQ_KEY
    GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
    if GROQ_KEY:
        return
    env = ROOT / "Nokido.env"
    if env.exists():
        for line in env.read_text(errors="ignore").splitlines():
            if line.startswith("GROQ_API_KEY=") and not line.startswith("#"):
                GROQ_KEY = line.split("=", 1)[1].strip()
                return


def _purge_turn(text: str) -> str:
    """Purge stack traces et schémas JSON tools."""
    # Tronque stack traces (lignes commençant par spaces + "at " ou "File ")
    lines = text.splitlines()
    out, trace_count = [], 0
    for line in lines:
        is_trace = bool(re.match(r'\s+(at |File "|Traceback|  File)', line))
        if is_trace:
            trace_count += 1
            if trace_count <= STACK_KEEP_LINES:
                out.append(line)
            elif trace_count == STACK_KEEP_LINES + 1:
                out.append(f"  ... [{len(lines)} lignes de trace tronquées]")
        else:
            trace_count = 0
            out.append(line)
    text = "\n".join(out)

    # Purge blocs JSON volumineux (> 300 chars entre accolades)
    def _shrink_json(m: re.Match) -> str:
        s = m.group(0)
        if len(s) > 300 and ('"inputSchema"' in s or '"properties"' in s or '"description"' in s):
            return "{...schema_omis...}"
        return s

    text = re.sub(r"\{[^{}]{200,}\}", _shrink_json, text, flags=re.DOTALL)

    return text[:MAX_CHARS_TURN]


def _load_from_agent_messages(session_id: str) -> tuple[list[dict], str]:
    """Source primaire. Retourne (turns, last_created_at_iso)."""
    if not M2M.exists():
        return [], ""
    try:
        conn = sqlite3.connect(str(M2M), timeout=5)
        rows = conn.execute(
            "SELECT payload, created_at FROM agent_messages "
            "WHERE correlation_id=? AND from_agent='cli_claude' "
            "AND method='conversation.turn' "
            "ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        conn.close()
        turns, last_ts = [], ""
        for payload_json, created_at in rows:
            try:
                p = json.loads(payload_json)
                role = p.get("role", "")
                if role not in ("user", "assistant"):
                    continue
                turns.append({"role": role, "content": _purge_turn(p.get("content", ""))})
                last_ts = created_at or last_ts
            except Exception:
                continue
        return turns[-MAX_TURNS:], last_ts
    except Exception:
        return [], ""


def _load_transcript_after(path: str, after_ts: str) -> list[dict]:
    """Fallback JSONL : lit uniquement les lignes avec timestamp > after_ts.
    Évite le split-brain si le watcher cli_tail_capture n a pas encore tourné."""
    turns = []
    try:
        p = Path(path)
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-500:]:
            try:
                obj = json.loads(line)
                # Filtre timestamp strict pour éviter doublons avec agent_messages
                if after_ts:
                    line_ts = obj.get("timestamp", "")
                    if line_ts and line_ts <= after_ts:
                        continue
                msg = obj.get("message", {})
                role = msg.get("role", "")
                if role not in ("user", "assistant"):
                    continue
                content = normalize_anthropic_content(msg.get("content", ""))
                turns.append({"role": role, "content": _purge_turn(content)})
            except Exception:
                continue
    except Exception:
        pass
    return turns[-MAX_TURNS:]


def _dernier_resume(session_id: str) -> dict | None:
    """Le résumé le plus récent de CETTE session, ou None.

    POURQUOI (mesure du 2026-09-19). `forge_session_provenance` attache bien
    `compaction_seq` et `parent_summary_id` à chaque résumé : la FILIATION est
    enregistrée. Mais rien ne relisait le parent — `_build_prompt` ne recevait
    que les derniers tours. La chaîne existait, la CONTINUITÉ non :

        avant :  resume N = f(derniers tours)
        apres :  resume N = f(resume N-1, delta)

    Conséquence concrète : une décision prise tôt et non re-mentionnée
    disparaissait dès la deuxième compaction, alors qu'elle restait vraie.

    Fail-soft : en cas d'échec on rend None et l'appelant retombe sur le
    comportement d'origine. Perdre l'héritage est regrettable ; perdre le
    résumé le serait bien plus.
    """
    if not DB.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB), timeout=5)
        cur = conn.execute(
            "SELECT text FROM rag_chunks WHERE domain='session_summary' "
            "AND source=? ORDER BY ingested_at DESC, rowid DESC LIMIT 1",
            (f"session/{session_id}",),
        )
        row = cur.fetchone()
        conn.close()
        if not row or not row[0]:
            return None
        parent = json.loads(row[0])
        return parent if isinstance(parent, dict) else None
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        # Jamais muet : sans cet avertissement, un resume reparti de zero se lit
        # comme un resume normal, et la perte est invisible.
        _lg.getLogger(__name__).warning(
            "[precompact] resume parent NON relu (%s: %s) | consequence: ce resume "
            "repart des derniers tours seuls, ce qui a ete etabli plus tot et non "
            "re-mentionne sera PERDU",
            type(e).__name__, str(e)[:90])
        return None


def _build_prompt(payload: str, session_id: str, parent: dict | None = None) -> str:
    entete = (
        f"Tu es un compresseur de contexte système.\n"
        f"Analyse cet historique de session et génère un objet JSON STRICT avec exactement ces clés :\n"
        f"{{\n"
        f'  "session_id": "{session_id}",\n'
        f'  "decisions": ["décision architecturale 1", ...],\n'
        f'  "open_bugs": ["bug non résolu 1", ...],\n'
        f'  "files_modified": ["chemin/fichier.py", ...],\n'
        f'  "tools_used": ["nom_tool", ...],\n'
        f'  "key_context": "résumé dense en 3-5 phrases max de l état actuel du travail"\n'
        f"}}\n"
        f"Ne produis QUE le JSON. Aucun texte avant ou après.\n\n"
    )
    if not parent:
        # Première compaction de la session : rien à hériter.
        return entete + f"HISTORIQUE:\n{payload}"

    # On ne redonne que les champs d'ETAT, pas l'objet entier : `tools_used` et
    # les metadonnees de provenance gonfleraient le prompt sans rien porter.
    etat = {k: parent.get(k) for k in ("decisions", "open_bugs", "files_modified",
                                       "key_context") if parent.get(k)}
    return (
        entete
        + "Tu MET À JOUR un état existant. Ce n'est PAS un résumé des derniers "
          "tours : c'est l'état précédent, corrigé par ce qui vient de se passer.\n"
          "Règles :\n"
          "- CONSERVE tout élément de l'état qui reste vrai, même s'il n'est pas "
          "re-mentionné dans l'historique ci-dessous. Ne pas le répéter n'est pas "
          "l'annuler.\n"
          "- RETIRE ce que l'historique montre comme résolu ou réfuté.\n"
          "- AJOUTE ce qui est nouveau.\n\n"
        + "ÉTAT PRÉCÉDENT (compaction n°%s) :\n%s\n\n"
          % (parent.get("compaction_seq", "?"),
             json.dumps(etat, ensure_ascii=False, indent=2))
        + f"NOUVEAUX ÉCHANGES DEPUIS :\n{payload}"
    )


def _parse_json_response(text: str) -> dict:
    """Extrait le premier objet JSON valide du texte."""
    text = text.strip()
    # Tentative directe
    try:
        return json.loads(text)
    except Exception:
        pass
    # Cherche {} dans le texte (cas markdown ```)
    m = re.search(r"\{[\s\S]+\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


def _call_openai_compat(
    url: str,
    api_key: str,
    model: str,
    payload: str,
    session_id: str,
    timeout: int = 18,
    json_format: bool = True,
) -> dict:
    """Appel générique OpenAI-compat (Groq, Ollama, LM Studio)."""
    _parent = _dernier_resume(session_id)
    if _parent:
        print("[precompact] heritage : etat de la compaction n°%s relu"
              % _parent.get("compaction_seq", "?"), file=sys.stderr, flush=True)
    prompt = _build_prompt(payload, session_id, _parent)
    body_obj: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600,
        "temperature": 0.1,
    }
    if json_format:
        body_obj["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        url, data=json.dumps(body_obj).encode("utf-8"), headers=headers, method="POST"
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    text = resp["choices"][0]["message"]["content"]
    result = _parse_json_response(text)
    if result and "error" not in result:
        result.setdefault("session_id", session_id)
        return result
    return {}


# Plafonds par liste heritee. Volontairement differents : une DECISION se perd
# plus gravement qu'un nom de fichier, qui reste retrouvable par git.
_PLAFOND_LISTE = {
    "decisions": 30,
    "open_bugs": 20,
    "files_modified": 24,
    "tools_used": 16,
}


def _fusionner_etat(parent: dict | None, neuf: dict) -> dict:
    """Ajoute le neuf à l'état hérité, sans perdre l'ancien.

    INVARIANT tenu ici : une information portée par HEAD_N et qu'aucun événement
    ultérieur n'invalide reste présente dans HEAD_N+k. Le repli extractif ne
    sait pas juger qu'un fait est devenu faux — il CONSERVE donc, plutôt que de
    laisser disparaître en silence. C'est le bon compromis pour un repli : la
    perte est irrattrapable, la redondance ne l'est pas.

    L'ordre est volontaire : l'hérité d'abord, le neuf ensuite. Ce qui a été
    établi tôt reste en tête de liste et survit aux troncatures.
    """
    if not parent:
        return neuf
    ecarte: dict[str, int] = {}
    for cle in ("decisions", "open_bugs", "files_modified", "tools_used"):
        herites = [x for x in (parent.get(cle) or []) if x]
        nouveaux = [x for x in (neuf.get(cle) or []) if x]
        vus, fusion = set(), []
        for x in herites + nouveaux:      # herite D'ABORD
            if x not in vus:
                vus.add(x)
                fusion.append(x)
        # BORNE, posee sur une dette MESUREE le 2026-09-19 : sur 12 compactions
        # simulees, `decisions` et `files_modified` croissent LINEAIREMENT
        # (~+145 c d'etat par compaction, sans plafond), la ou `key_context` se
        # stabilise parce qu'il en a une. Extrapole, l'etat depasserait
        # MAX_PAYLOAD_CHARS vers la 80e compaction.
        #
        # On garde les DEUX bouts : les plus ANCIENS (ils ont survecu a N
        # compactions, donc ils sont les plus etablis) ET les plus RECENTS (le
        # travail en cours). Ce qui tombe est le milieu -- et il est COMPTE.
        plafond = _PLAFOND_LISTE.get(cle, 24)
        if len(fusion) > plafond:
            garde_debut = plafond // 2
            garde_fin = plafond - garde_debut
            ecarte[cle] = len(fusion) - plafond
            fusion = fusion[:garde_debut] + fusion[-garde_fin:]
        neuf[cle] = fusion
    if ecarte:
        # La borne DIT combien, et elle le dit DANS l'artefact : un log
        # disparait, l'etat voyage. Sans ce champ, une troncature se lirait
        # comme une liste complete -- le defaut `text[:3000]` du 2026-07-25.
        neuf["_tronque"] = ecarte
    # `key_context` est une PHRASE : on ne la concatène pas indéfiniment, on
    # garde la plus récente en rappelant qu'un état antérieur existe.
    if parent.get("key_context") and neuf.get("key_context"):
        neuf["key_context"] = "%s | [hérité c%s] %s" % (
            neuf["key_context"], parent.get("compaction_seq", "?"),
            str(parent["key_context"])[:400])
    return neuf


def _extractive_fallback(turns: list[dict], session_id: str,
                         parent: dict | None = None) -> dict:
    """Résumé extractif sans LLM — toujours disponible.

    ⚠️ HÉRITE du parent depuis le 2026-09-19. Sans cela, le repli contournait
    l'héritage ajouté au chemin LLM : dès que le modèle était indisponible — le
    cas le PLUS probable, puisque c'est précisément pour cela qu'un repli
    existe — la compaction repartait de zéro. Le garde tenait une porte et pas
    l'autre, cinquième occurrence de ce motif dans la même journée.
    """
    files, tools, decisions = set(), set(), []
    for t in turns:
        c = t.get("content", "")
        # fichiers modifiés (patterns app/, tools/, etc.)
        for f in re.findall(r"(?:app|tools|proxy_deno|tests)/[\w/._-]+\.(?:py|ts|js|md)", c):
            files.add(f)
        # tools appelés
        for tk in re.findall(r"\[tool:([\w_]+)\]", c):
            tools.add(tk)
        # lignes "décision" heuristique (assistant commence par verbe fort)
        if t["role"] == "assistant":
            for line in c.splitlines()[:3]:
                line = line.strip()
                if len(line) > 40 and any(
                    line.lower().startswith(v)
                    for v in (
                        "fix",
                        "add",
                        "créé",
                        "modif",
                        "supprim",
                        "ajout",
                        "migrat",
                        "refact",
                        "corrig",
                    )
                ):
                    decisions.append(line[:120])
    return _fusionner_etat(parent, {
        "session_id": session_id,
        "decisions": decisions[:5],
        "open_bugs": [],
        "files_modified": sorted(files)[:10],
        "tools_used": sorted(tools)[:10],
        "key_context": f"[extractif] Session {session_id} — {len(turns)} tours analysés.",
        "_source": "extractive",
    })


def _call_groq(payload: str, session_id: str) -> dict:
    """Cascade : Groq → Ollama :11434 → LM Studio :1234 → extractif."""
    # 1. Groq (cloud, JSON natif)
    if GROQ_KEY:
        try:
            r = _call_openai_compat(
                "https://api.groq.com/openai/v1/chat/completions",
                GROQ_KEY,
                "llama-3.3-70b-versatile",
                payload,
                session_id,
                timeout=20,
                json_format=True,
            )
            if r:
                r["_source"] = "groq"
                return r
        except Exception:
            pass

    # 2. Ollama local :11434 (OpenAI-compat, JSON via response_format)
    try:
        r = _call_openai_compat(
            "http://127.0.0.1:11434/v1/chat/completions",
            "",
            "qwen2.5-coder:7b",  # tag RÉEL installé (l'ancien 'qwen2.5-coder:7b-instruct' = 404)
            payload,
            session_id,
            timeout=30,
            json_format=True,
        )
        if r:
            r["_source"] = "ollama"
            return r
    except Exception:
        pass

    # 3. LM Studio :1234 (OpenAI-compat, pas toujours json_format)
    try:
        r = _call_openai_compat(
            "http://127.0.0.1:1234/v1/chat/completions",
            "",
            "local-model",
            payload,
            session_id,
            timeout=30,
            json_format=False,
        )
        if r:
            r["_source"] = "lmstudio"
            return r
    except Exception:
        pass

    return {}  # signale qu'on doit utiliser l'extractif (géré dans main)


def _store_summary(summary: dict, session_id: str) -> None:
    """Stocke dans rag_chunks(domain='session_summary') + CONTEXT_SUMMARY.md."""
    if not summary or "error" in summary:
        return
    if not DB.exists():
        return

    # Provenance cross-compaction (#2 roadmap hermes) : tague ce résumé avec son
    # rang dans la lignée + l'id du résumé précédent (chaîne traçable des compactions
    # d'une même session marathon). cf tools/forge_session_provenance.py. Fail-soft.
    try:
        from nokido_agent.tools.forge_session_provenance import enrich_with_provenance
        summary = enrich_with_provenance(summary, session_id)
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "[precompact] provenance NON attachee au resume (%s: %s) | consequence: "
            "ce resume ne pourra pas etre rattache a la lignee des compactions de la "
            "meme session, et la chaine paraitra interrompue",
            type(e).__name__, str(e)[:90])

    text = json.dumps(summary, ensure_ascii=False, indent=2)
    chunk_id = "sess_" + hashlib.sha256(f"{session_id}{time.time()}".encode()).hexdigest()[:16]

    try:
        conn = sqlite3.connect(str(DB), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT OR REPLACE INTO rag_chunks(id,source,text,domain,ingested_at) VALUES(?,?,?,?,?)",
            (
                chunk_id,
                f"session/{session_id}",
                text,
                "session_summary",
                time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        # Le resume de session est ce qui permet a la session SUIVANTE de reprendre.
        # Perdu en silence, il ne manque a personne sur le moment — et la reprise
        # repart d'une page blanche sans savoir qu'une page existait.
        _lg.getLogger(__name__).error(
            "[precompact] resume de session NON enregistre (%s: %s) | consequence: la "
            "prochaine session reprendra SANS ce contexte et rien ne le signalera",
            type(e).__name__, str(e)[:90])

    # Met à jour CONTEXT_SUMMARY.md pour réinjection SessionStart
    try:
        ts = time.strftime("%Y-%m-%d %H:%M")
        md = f"## Session Summary — {ts}\n\n"
        if summary.get("key_context"):
            md += f"**Contexte :** {summary['key_context']}\n\n"
        if summary.get("decisions"):
            md += "**Décisions :** " + " · ".join(summary["decisions"][:5]) + "\n\n"
        if summary.get("open_bugs"):
            md += "**Bugs ouverts :** " + " · ".join(summary["open_bugs"][:3]) + "\n\n"
        if summary.get("files_modified"):
            md += "**Fichiers :** " + " · ".join(summary["files_modified"][:8]) + "\n\n"
        md += "---\n"
        SUMMARY.write_text(md, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).error(
            "[precompact] resume lisible NON ecrit dans %s (%s: %s) | consequence: la "
            "version humaine du contexte manque, meme si la base l'a peut-etre gardee",
            SUMMARY, type(e).__name__, str(e)[:90])


def main() -> int:
    _load_env()

    # Lire stdin (PreCompactHookInput JSON)
    hook_input: dict = {}
    try:
        raw = sys.stdin.read()
        if raw.strip():
            hook_input = json.loads(raw)
    except Exception:
        pass

    session_id = hook_input.get("session_id", f"unknown_{int(time.time())}")
    transcript_path = hook_input.get("transcript_path", "")

    # Source 1 : agent_messages (normalisé + purgé par cli_capture_lib)
    turns, last_ts = _load_from_agent_messages(session_id)
    # Source 2 : JSONL → uniquement les tours postérieurs au dernier en base
    # (élimine doublons, couvre les assistant-turns mid-session non capturés)
    if transcript_path:
        extra = _load_transcript_after(transcript_path, last_ts)
        turns = (turns + extra)[-MAX_TURNS:]
    if not turns:
        return 0  # rien à résumer, laisser compaction

    # Construire payload texte compact
    lines = []
    for t in turns:
        prefix = "U:" if t["role"] == "user" else "A:"
        lines.append(f"{prefix} {t['content']}")
    payload = "\n".join(lines)[:MAX_PAYLOAD_CHARS]

    # Cascade LLM → extractif garanti
    # Etat herite, lu UNE fois et partage par TOUS les chemins de la cascade.
    # Il etait auparavant lu dans `_call_openai_compat` seulement : le repli
    # extractif n'y avait pas acces, et `_parent` y aurait leve un NameError --
    # invisible a la compilation, puisque Python ne resout pas les noms avant
    # l'execution. Le lire ici garantit que tous les chemins heritent, pas
    # seulement celui qui a un modele disponible.
    _parent = _dernier_resume(session_id)
    if _parent:
        print("[precompact] heritage : etat de la compaction n %s relu"
              % _parent.get("compaction_seq", "?"), file=sys.stderr, flush=True)

    summary = _call_groq(payload, session_id)
    if not summary or "error" in summary:
        summary = _extractive_fallback(turns, session_id, _parent)

    # Stockage
    _store_summary(summary, session_id)

    # Log hub (fail-silent)
    try:
        # SON marqueur d'abord, et le COFFRE avant le fichier (regle DPAPI).
        # Corrige le 2026-09-02 : ce hook portait le credential de CLAUDE
        # (ring 1) en se declarant CLAUDE_HOOK (ring 4). Emprunter le marqueur
        # d'un voisin est ce que la doctrine interdit, et cela faisait circuler
        # un credential privilegie dans un hook qui n'en a pas besoin.
        tok = ""
        try:
            sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_secrets import get_secret  # type: ignore

            tok = get_secret("FORGE_TOKEN_CLAUDE_HOOK") or ""
        except Exception:  # muet-ok : coffre indisponible -> replis ci-dessous, un hook ne casse jamais la session
            tok = ""
        if not tok:
            tok = os.environ.get("FORGE_TOKEN_CLAUDE_HOOK", "") or os.environ.get(
                "FORGE_TOKEN_CLAUDE", "")
        if not tok:
            env = ROOT / "Nokido.env"
            if env.exists():
                for line in env.read_text(errors="ignore").splitlines():
                    if line.startswith("FORGE_TOKEN_CLAUDE_HOOK="):
                        tok = line.split("=", 1)[1].strip()
                        break
                    if line.startswith("FORGE_TOKEN_CLAUDE="):
                        tok = line.split("=", 1)[1].strip()
        if tok:
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "event",
                        "arguments": {
                            "action": "publish",
                            "topic": "agent.claude.precompact",
                            "kind": "info",
                            "data": {
                                "session_id": session_id,
                                "turns_processed": len(turns),
                                "summary_stored": bool(summary and "error" not in summary),
                            },
                        },
                    },
                }
            ).encode()
            req = urllib.request.Request(
                HUB,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {tok}",
                    # Nom canonique (RFC 6648) + repli legacy pendant la transition.
                    "LaForge-Agent-Name": "CLAUDE_HOOK",
                    "X-Agent-Name": "CLAUDE_HOOK",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass

    return 0  # exit 0 = laisser compaction se dérouler


if __name__ == "__main__":
    sys.exit(main())
