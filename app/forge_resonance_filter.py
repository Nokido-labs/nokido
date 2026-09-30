"""Note une proposition d'agent (répétition, dérive ADR, ring 0) et choisit l'action.

Entrées : resonance_check(agent_id, proposal, context, strict) renvoie pass, warn,
correct ou block, un prompt préfixé d'une « Correction de Cap » et les scores.
create_adr() ajoute un ADR dans adr_records et un chunk domain=adr dans rag_chunks.
Lit adr_records et system_rules dans RAG/embeddings.db ; lit et écrit resonance_log
dans sandbox/events.db ; publie resonance.* et adr.* via live_bridge. Embedding par
NPUEmbedder, sinon vecteur trigramme ; aucun appel LLM.
Utilisé par forge_dispatch_ai, forge_mmap_context, forge_pipeline_node et
mcp_server_tools.
"""
from __future__ import annotations

from typing import Optional

"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_164356_astdoc
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

"""
app/forge_resonance_filter.py
==============================
Filtre de Résonance — "Conscience Émanente" Nokido

Rôle : Avant qu'un agent ne réponde, compare sa proposition avec :
  1. Les 3 derniers timestamps du même agent (anti-répétition)
  2. Le manifeste ADR (anti-dérive architecturale)
  3. Les system_rules ring 0 (lois absolues)

Actions possibles :
  pass     — proposition alignée, aucune intervention
  warn     — drift léger, ajout silencieux d'un contexte ADR
  correct  — injection d'une "Correction de Cap" visible
  block    — proposition contradictoire avec une loi absolue (ring 0)

Intégration :
  Appelé depuis dispatch_ai AVANT la génération LLM :
    from forge_resonance_filter import resonance_check
    result = resonance_check(agent_id="CLAUDE", proposal=user_input)
    if result["action"] == "block": return  # stopper la génération
    enriched = result["enriched_prompt"]    # prompt augmenté ADR

Architecture :
  - Embedding NPU (minilm_int8) pour similarité sémantique
  - Fallback trigram si NPU indisponible
  - Zéro LLM call — pure logique vectorielle
  - Logs dans resonance_log (events.db)
  - Écriture état dans live_bridge mmap (gui peut visualiser)
"""

import hashlib
import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_EVENTS = ROOT / "sandbox" / "events.db"
DB = ROOT / "RAG" / "embeddings.db"  # ADR + resonance_log

# Seuils
SIMILARITY_REPEAT_THRESHOLD = 0.82  # au-dessus = répétition
DRIFT_WARN_THRESHOLD = 0.35  # score dérive > 35% → warn
DRIFT_CORRECT_THRESHOLD = 0.60  # > 60% → correction injectée
DRIFT_BLOCK_THRESHOLD = 0.90  # > 90% → blocage (loi absolue)

N_RECENT = 3  # nombre de timestamps à comparer


# ── Embedder léger ────────────────────────────────────────────────────────────


def _embed(text: str) -> Optional[list]:
    """
    NPU DML ou fallback trigram.

    Args:
        text (str): Texte à embedder.

    Returns:
        Optional[list]: Embedding vectoriel du texte.
    """
    try:
        import sys

        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_npu_embedder import NPUEmbedder

        emb = NPUEmbedder()
        vecs = emb.embed_texts([text[:512]])
        return vecs[0].tolist() if vecs is not None else None
    except Exception:
        return _trigram_vec(text)


def _trigram_vec(text: str) -> list:
    """
    Vecteur trigram 512-dim normalisé — fallback pur Python.

    Args:
        text (str): Texte à convertir en vecteur trigram.

    Returns:
        list: Vecteur trigram du texte.
    """
    vec = [0.0] * 512
    t = text.lower()
    for i in range(len(t) - 2):
        h = hash(t[i : i + 3]) % 512
        vec[h] += 1.0
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec] if norm > 0 else vec


def _cosine(a: list, b: list) -> float:
    """
    Calcul de la similarité cosinus entre deux vecteurs.

    Args:
        a (list): Premier vecteur.
        b (list): Deuxième vecteur.

    Returns:
        float: Similarité cosinus entre les deux vecteurs.
    """
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na * nb > 0 else 0.0


def _sha256(text: str) -> str:
    """
    Calcul du hash SHA-256 d'un texte.

    Args:
        text (str): Texte à hasher.

    Returns:
        str: Hash SHA-256 du texte.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ── Lecture contexte récent ───────────────────────────────────────────────────


def _get_recent_proposals(agent_id: str, n: int = N_RECENT) -> list:
    """
    Lit les N dernières propositions de cet agent depuis resonance_log.

    Args:
        agent_id (str): Identifiant de l'agent.
        n (int, optional): Nombre de propositions à récupérer. Defaults to N_RECENT.

    Returns:
        list: Liste des propositions récentes.
    """
    try:
        conn = sqlite3.connect(str(DB_EVENTS), timeout=5)
        rows = conn.execute(
            "SELECT proposal_text, proposal_hash, timestamp FROM resonance_log "
            "WHERE agent_id=? ORDER BY id DESC LIMIT ?",
            (agent_id, n),
        ).fetchall()
        conn.close()
        return [{"text": r[0], "hash": r[1], "ts": r[2]} for r in rows]
    except Exception:
        return []


def _get_active_adrs() -> list:
    """
    Lit les ADR Acceptés depuis events.db.

    Returns:
        list: Liste des ADR acceptés.
    """
    try:
        conn = sqlite3.connect(str(DB), timeout=5)
        rows = conn.execute(
            "SELECT adr_id, title, decision, consequences_neg, tags "
            "FROM adr_records WHERE status='Accepté' ORDER BY ring, id"
        ).fetchall()
        conn.close()
        return [
            {"id": r[0], "title": r[1], "decision": r[2], "cons_neg": r[3], "tags": json.loads(r[4] or "[]")}
            for r in rows
        ]
    except Exception:
        return []


def _get_ring0_rules() -> list:
    """
    Lit les system_rules ring 0 depuis events.db.

    Returns:
        list: Liste des règles ring 0.
    """
    try:
        conn = sqlite3.connect(str(DB), timeout=5)
        rows = conn.execute("SELECT tag, title, content FROM system_rules WHERE ring=0").fetchall()
        conn.close()
        return [{"tag": r[0], "title": r[1], "content": r[2]} for r in rows]
    except Exception:
        return []


# ── Scoring dérive ────────────────────────────────────────────────────────────


def _score_drift(proposal: str, adrs: list, rules: list) -> tuple[float, list]:
    """
    Retourne (drift_score, triggered_adrs).
    drift_score : 0.0 = aligné, 1.0 = contradiction totale.
    triggered_adrs : liste des ADR/règles pertinents à injecter.

    Args:
        proposal (str): Proposition à évaluer.
        adrs (list): Liste des ADR.
        rules (list): Liste des règles.

    Returns:
        tuple[float, list]: Score de dérive et liste des ADR/règles déclenchés.
    """
    proposal_lower = proposal.lower()
    triggered = []
    max_drift = 0.0

    # Check ADR keywords — recherche lexicale rapide
    adr_keywords = {
        "ADR-001": ["while proc.poll", "subprocess.run(", "blocking", "bloquant"],
        "ADR-002": ["udp", "socket.bind", "broadcast", "9765"],
        "ADR-003": ["git commit", "push", "sans test", "without test"],
        "ADR-004": ["watchdog", "terminate", "kill", "freeze"],
        "ADR-005": ["deux agents", "concurrent stream", "parallel rag"],
        "ADR-006": ["trust_score", "ring override", "bypass ring"],
    }

    for adr in adrs:
        adr_id = adr["id"]
        kws = adr_keywords.get(adr_id, [])
        # Vérifier si la proposition contredit l'ADR
        hits = [kw for kw in kws if kw.lower() in proposal_lower]
        if hits:
            # Dérive potentielle : l'agent veut faire quelque chose que l'ADR interdit
            triggered.append(adr)
            max_drift = max(max_drift, 0.4 + 0.1 * len(hits))

    # Check ring 0 — lois absolues
    ring0_violations = {
        "PAS DE TEST PAS DE LIVRABLE": ["commit", "push", "livr"],
        "JAMAIS de boucle bloquante": ["while", "poll(", "wait("],
        "REGLE ANTI-LENTEUR": ["subprocess.run(", "check_output("],
    }

    for rule in rules:
        for key, kws in ring0_violations.items():
            if key.lower() in rule["content"].lower():
                hits = [kw for kw in kws if kw in proposal_lower]
                if hits:
                    triggered.append(
                        {"id": "RULE-" + rule["tag"], "title": rule["title"], "decision": rule["content"][:200]}
                    )
                    max_drift = max(max_drift, 0.75)

    return min(max_drift, 1.0), triggered


# ── Vérification répétition ───────────────────────────────────────────────────


def _score_repetition(proposal_vec: list, recent: list) -> float:
    """
    Score de similarité max avec les N dernières propositions.

    Args:
        proposal_vec (list): Vecteur de la proposition.
        recent (list): Liste des propositions récentes.

    Returns:
        float: Score de similarité.
    """
    if not recent or not proposal_vec:
        return 0.0
    max_sim = 0.0
    for prev in recent:
        prev_vec = _embed(prev["text"])
        if prev_vec:
            sim = _cosine(proposal_vec, prev_vec)
            max_sim = max(max_sim, sim)
    return max_sim


# ── Injection correction ──────────────────────────────────────────────────────


def _build_correction(triggered: list, repeat_score: float, drift_score: float) -> str:
    """
    Construit le texte de Correction de Cap à injecter dans le prompt.
    Format compact — lisible par le LLM, transparent pour l'humain.

    Args:
        triggered (list): Liste des ADR/règles déclenchés.
        repeat_score (float): Score de répétition.
        drift_score (float): Score de dérive.

    Returns:
        str: Texte de correction.
    """
    parts = ["[CORRECTION DE CAP — Ring 10]"]

    if repeat_score >= SIMILARITY_REPEAT_THRESHOLD:
        parts.append(
            f"⚠ Résonance détectée ({repeat_score:.0%} similaire aux réponses récentes). "
            "Apporte une perspective nouvelle ou confirme explicitement la convergence."
        )

    for item in triggered[:3]:
        aid = item.get("id", "?")
        title = item.get("title", "")
        dec = item.get("decision", "")[:120]
        parts.append(f"📌 {aid} '{title}': {dec}")

    if drift_score >= DRIFT_BLOCK_THRESHOLD:
        parts.append(
            "🚫 Cette proposition contredit une loi absolue (ring 0). "
            "Reformule en respectant les contraintes architecturales."
        )

    return "\n".join(parts)


def _build_enriched_prompt(original: str, correction: str) -> str:
    """
    Insère la correction au début du prompt système.

    Args:
        original (str): Prompt original.
        correction (str): Texte de correction.

    Returns:
        str: Prompt enrichi.
    """
    return correction + "\n\n---\n\n" + original


# ── Logger resonance ──────────────────────────────────────────────────────────


def _log_resonance(
    agent_id: str,
    proposal_hash: str,
    proposal_text: str,
    similar_seqs: list,
    drift_score: float,
    adr_triggered: list,
    correction: str,
    action: str,
) -> int:
    """
    Enregistre dans resonance_log + broadcast mmap.

    Args:
        agent_id (str): Identifiant de l'agent.
        proposal_hash (str): Hash de la proposition.
        proposal_text (str): Texte de la proposition.
        similar_seqs (list): Liste des séquences similaires.
        drift_score (float): Score de dérive.
        adr_triggered (list): Liste des ADR/règles déclenchés.
        correction (str): Texte de correction.
        action (str): Action à prendre.

    Returns:
        int: ID de la ligne enregistrée.
    """
    try:
        conn = sqlite3.connect(str(DB_EVENTS), timeout=5)
        cur = conn.execute(
            "INSERT INTO resonance_log("
            "agent_id,proposal_hash,proposal_text,similar_seqs,"
            "drift_score,adr_triggered,correction,action) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                agent_id,
                proposal_hash,
                proposal_text[:500],
                json.dumps(similar_seqs),
                drift_score,
                json.dumps([a.get("id") for a in adr_triggered]),
                correction[:400],
                action,
            ),
        )
        conn.commit()
        row_id = cur.lastrowid
        conn.close()

        # Broadcast dans mmap
        try:
            import sys

            if str(ROOT / "app") not in sys.path:
                sys.path.insert(0, str(ROOT))
            from nokido_agent.app.live_bridge import bridge

            bridge.json_set("resonance.last_agent", agent_id)
            bridge.json_set("resonance.last_action", action)
            bridge.json_set("resonance.drift_score", round(drift_score, 3))
            bridge.json_set("resonance.ts", time.time())
        except Exception:
            pass

        return row_id
    except Exception:
        return -1


# ── API principale ────────────────────────────────────────────────────────────


def resonance_check(
    agent_id: str,
    proposal: str,
    context: str = "",
    strict: bool = False,
) -> dict:
    """
    Vérifie une proposition avant génération LLM.

    Args:
        agent_id (str): Identifiant de l'agent.
        proposal (str): Texte de la proposition.
        context (str, optional): Contexte additionnel. Defaults to "".
        strict (bool, optional): Si True, abaisse tous les seuils de 20%. Defaults to False.

    Returns:
        dict: Résultat de la vérification.
    """
    t0 = time.monotonic()
    proposal_hash = _sha256(proposal + agent_id)

    # Embed
    prop_vec = _embed(proposal)

    # Contexte récent
    recent = _get_recent_proposals(agent_id)

    # Scores
    repeat_score = _score_repetition(prop_vec, recent)
    adrs = _get_active_adrs()
    rules = _get_ring0_rules()
    drift_score, triggered = _score_drift(proposal, adrs, rules)

    # Ajuster seuils si strict
    factor = 0.8 if strict else 1.0
    thresh_warn = DRIFT_WARN_THRESHOLD * factor
    thresh_correct = DRIFT_CORRECT_THRESHOLD * factor
    thresh_block = DRIFT_BLOCK_THRESHOLD * factor

    # Décision
    action = "pass"
    correction = ""

    if repeat_score >= SIMILARITY_REPEAT_THRESHOLD:
        action = "warn"
        correction = _build_correction(triggered, repeat_score, drift_score)

    if drift_score >= thresh_block:
        action = "block"
        correction = _build_correction(triggered, repeat_score, drift_score)
    elif drift_score >= thresh_correct:
        action = "correct"
        correction = _build_correction(triggered, repeat_score, drift_score)
    elif drift_score >= thresh_warn:
        if action == "pass":
            action = "warn"
            correction = _build_correction(triggered, repeat_score, drift_score)

    enriched = _build_enriched_prompt(proposal, correction) if correction else proposal

    # Log
    similar_seqs = [{"hash": r["hash"], "ts": r["ts"]} for r in recent]
    log_id = _log_resonance(agent_id, proposal_hash, proposal, similar_seqs, drift_score, triggered, correction, action)

    elapsed_ms = (time.monotonic() - t0) * 1000

    return {
        "action": action,
        "drift_score": round(drift_score, 4),
        "repeat_score": round(repeat_score, 4),
        "enriched_prompt": enriched,
        "triggered_adrs": triggered,
        "correction": correction,
        "log_id": log_id,
        "elapsed_ms": round(elapsed_ms, 2),
    }


# ── ADR creator (helper) ──────────────────────────────────────────────────────


def create_adr(
    title: str,
    context: str,
    decision: str,
    consequences_pos: str = "",
    consequences_neg: str = "",
    tags: list = None,
    ring: int = 1,
    status: str = "Proposé",
) -> str:
    """
    Crée un nouvel ADR en DB et l'ingère dans le RAG.
    Retourne l'ADR_ID créé (ex: 'ADR-007').

    Args:
        title (str): Titre de l'ADR.
        context (str): Contexte de l'ADR.
        decision (str): Décision de l'ADR.
        consequences_pos (str, optional): Conséquences positives. Defaults to "".
        consequences_neg (str, optional): Conséquences négatives. Defaults to "".
        tags (list, optional): Tags de l'ADR. Defaults to None.
        ring (int, optional): Ring de l'ADR. Defaults to 1.
        status (str, optional): Statut de l'ADR. Defaults to "Proposé".

    Returns:
        str: ID de l'ADR créé.
    """
    tags = tags or []
    try:
        conn = sqlite3.connect(str(DB), timeout=10)
        # Prochain ID
        last = conn.execute("SELECT adr_id FROM adr_records ORDER BY id DESC LIMIT 1").fetchone()
        if last:
            n = int(last[0].split("-")[1]) + 1
        else:
            n = 1
        adr_id = f"ADR-{n:03d}"

        conn.execute(
            "INSERT INTO adr_records("
            "adr_id,title,status,context,decision,"
            "consequences_pos,consequences_neg,tags,ring) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (adr_id, title, status, context, decision, consequences_pos, consequences_neg, json.dumps(tags), ring),
        )
        conn.commit()

        # Ingérer dans RAG comme chunk ring 2
        adr_text = (
            f"# {adr_id}: {title}\n"
            f"Status: {status}\n"
            f"Contexte: {context}\n"
            f"Décision: {decision}\n"
            f"Conséquences+: {consequences_pos}\n"
            f"Conséquences-: {consequences_neg}\n"
        )
        # 2026-09-12 : INSERT sans `id` (TEXT PRIMARY KEY) — clef laissee NULLE.
        from nokido_agent.app.forge_db_path import ecrire_chunk  # type: ignore

        ecrire_chunk(conn, adr_id, "adr", adr_text)
        conn.commit()
        conn.close()

        # Broadcast mmap
        try:
            from nokido_agent.app.live_bridge import bridge

            bridge.json_set("adr.last_created", adr_id)
            bridge.json_set("adr.total", n)
        except Exception:
            pass

        return adr_id
    except Exception as e:
        return f"ERROR: {e}"


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        print("Test resonance_check...")
        r = resonance_check(agent_id="TEST", proposal="Je vais utiliser subprocess.run() pour installer pip bloquant")
        print(f"action={r['action']} drift={r['drift_score']} repeat={r['repeat_score']}")
        print("correction:", r["correction"][:200] if r["correction"] else "(none)")
        print(f"elapsed: {r['elapsed_ms']}ms")
    elif "--create-adr" in sys.argv:
        adr_id = create_adr(
            title="Test ADR",
            context="Test context",
            decision="Test decision",
            tags=["test"],
        )
        print("Created:", adr_id)
    else:
        print("Usage: python forge_resonance_filter.py --test | --create-adr")
