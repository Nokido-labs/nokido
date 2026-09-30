#!/usr/bin/env python3
"""
claude_session_start.py — Hook SessionStart Claude Code

Au boot Claude :
1. Brief RAG compact (règles + leçons récentes + anchres) → injecté 1× dans contexte
2. Pull inbox agent_messages pour to_agent='agt_claude'
3. Notify hub session online

Tout ce qui est ici remplace CLAUDE.md pour économiser ~6k tokens/tour.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `acquitter_audit` — `--audit-fait [--modele M] [--version V]` : l'audit couvre ce qui a ete VU (ou ce qui est donne).
- `alerte_cout_reprise` — SessionStart porte `prompt_cache_likely_expired` / `context_tokens` / `estimated_cache_write_usd`.
- `modele_normalise` — `claude-opus-5-5[1m]` et `claude-opus-5-5` sont le MEME modele : la fenetre n'en fait pas un autre.
- `rappel_audit` — (texte du rappel ou None, etat mis a jour). Le rappel TIENT tant que l'audit n'est pas acquitte.
- `section_audit` — Entree brute du hook -> rappel ou None. Ne casse JAMAIS la session : un defaut est DIT.
- `section_changement_modele` — Hook PostModelSwitch (`from_model` / `to_model`) -> rappel ou None ; sa sortie est livree a Claude.
- `version_du_transcript` — Derniere version de Claude Code portee par une ligne du transcript, ou None (ILLISIBLE).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB = "http://127.0.0.1:8766/mcp"
DB = ROOT / "RAG" / "embeddings.db"
# Scission M2M : agent_messages suit l'interrupteur sandbox/m2m.switch ; DB reste la
# base du RAG pour rag_chunks. Un hook ne casse jamais la session : repli DIT.
try:
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_db_path import m2m_path as _m2m_path
    M2M = Path(_m2m_path())
except Exception as _e:  # noqa: BLE001
    print(f"[session_start] forge_db_path indisponible ({type(_e).__name__}) : base historique", file=sys.stderr)
    M2M = DB
SUMMARY = ROOT / "CONTEXT_SUMMARY.md"

REGLES = """\
=== Nokido — Règles actives ===
LAFORGE_PYTHON = %USERPROFILE%/miniforge3/python.exe  (jamais `python` brut)
Hub :8766 avant tout fichier Read. GitHub sidecar :9200 pour repos RAM.
1. Jamais SQL LIKE raw - rag_fts ou RAGEngine.search
2. Jamais forge_*.py sans query rag_fts préalable
3. Jamais INSERT rag_chunks sans id explicite (TEXT PRIMARY KEY)
4. Jamais envoi cloud sans SemanticFirewall pre_flight + post_flight
5. anchor_solution après décision architecturale
6. LAFORGE_PYTHON, jamais python brut
Stack: :8766 hub | :11434 ollama | :9200 github-sidecar | :7500 netcfg | :3210 lobehub"""

# ── Audit de prompts au changement de modele ou de CLI ─────────────────────────
# Owner 2026-09-26 : « il aura fallu quand meme que je tape la commande de moi-meme ». Rien ne
# declenchait l'audit des surfaces toujours chargees quand le modele ou Claude Code changeait.
# Le modele vient de l'entree du hook (champ `model`, doc hooks) ; la version du CLI n'y est
# pas : elle se lit dans le transcript et, illisible, elle reste INCONNUE -- jamais devinee.
ETAT_AUDIT = Path(os.environ.get("NOKIDO_CLAUDE_AUDIT_ETAT") or ROOT / "sandbox" / "claude_audit_prompts.json")
_RE_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def modele_normalise(modele):
    """`claude-opus-5-5[1m]` et `claude-opus-5-5` sont le MEME modele : la fenetre n'en fait pas un autre."""
    m = (modele or "").strip().lower().split("[", 1)[0].strip()
    return m or None


def version_du_transcript(chemin, max_octets=1_048_576):
    """Derniere version de Claude Code portee par une ligne du transcript, ou None (ILLISIBLE).

    Seul le champ `version` de PREMIER niveau compte : un `"version"` cite dans un resultat
    d'outil (un package.json lu) n'est pas celle du CLI."""
    try:
        with open(chemin, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - max_octets))
            fin = f.read().decode("utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return None
    for ligne in reversed(fin.splitlines()):
        try:
            d = json.loads(ligne)
        except ValueError:
            continue  # muet-ok : ligne coupee par la fenetre de lecture ou non JSON
        v = d.get("version") if isinstance(d, dict) else None
        if isinstance(v, str) and _RE_SEMVER.match(v):
            return v
    return None


def rappel_audit(etat, modele, version):
    """(texte du rappel ou None, etat mis a jour). Le rappel TIENT tant que l'audit n'est pas acquitte."""
    etat = dict(etat or {})
    vu = dict(etat.get("vu") or {})
    if modele_normalise(modele):
        vu["modele"] = modele_normalise(modele)
    if version:
        vu["version"] = version  # une lecture illisible n'efface pas la derniere version connue
    etat["vu"] = vu
    audite = etat.get("audite") or {}
    ecarts = []
    if not audite:
        ecarts.append("aucun audit enregistre (inconnu n'est pas audite)")
    else:
        if vu.get("modele") and vu["modele"] != audite.get("modele"):
            ecarts.append("modele %s -> %s" % (audite.get("modele") or "?", vu["modele"]))
        if vu.get("version") and vu["version"] != audite.get("version"):
            ecarts.append("CLI %s -> %s" % (audite.get("version") or "?", vu["version"]))
    if not ecarts:
        return None, etat
    return ("[audit-prompts] %s.\n"
            "  -> LANCE-LE TOI-MEME, sans attendre l'owner : skill claude-api, argument prompt-audit "
            "(CLAUDE.md, RULES_SHARED.md, descriptions MCP du registre, messages des hooks, MEMORY.md) ; "
            "rapport + diff proposes, application sur accord owner.\n"
            "  -> ce qui a change : changelog ingere, source "
            "claude_code_docs:code.claude.com/docs/en/changelog.md.\n"
            "  -> audit fait : LAFORGE_PYTHON tools/claude_session_start.py --audit-fait "
            "(sinon ce rappel revient a chaque demarrage)." % " ; ".join(ecarts)), etat


def _lire_etat_audit(chemin):
    try:
        d = json.loads(Path(chemin).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}  # absent ou illisible : traite comme NON audite, jamais comme audite


def _ecrire_etat_audit(chemin, etat):
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(etat, indent=1, ensure_ascii=False), encoding="utf-8")


def _entree_json(entree_brute):
    """Entree du hook -> dict ({} si absente ou illisible : rien n'est invente a partir d'elle)."""
    if isinstance(entree_brute, dict):
        return entree_brute
    try:
        entree = json.loads(entree_brute) if (entree_brute or "").strip() else {}
    except (TypeError, ValueError):
        entree = {}
    return entree if isinstance(entree, dict) else {}


def section_audit(entree_brute, chemin_etat):
    """Entree brute du hook -> rappel ou None. Ne casse JAMAIS la session : un defaut est DIT."""
    entree = _entree_json(entree_brute)
    chemin_t = entree.get("transcript_path")
    version = version_du_transcript(chemin_t) if chemin_t else None
    texte, etat = rappel_audit(_lire_etat_audit(chemin_etat), entree.get("model"), version)
    try:
        _ecrire_etat_audit(chemin_etat, etat)
    except OSError as exc:
        texte = (texte or "[audit-prompts]") + "\n  (etat NON ecrit : %s -- %s)" % (chemin_etat, type(exc).__name__)
    # Doc hooks : SessionStart ne porte `model` que PARFOIS ; PostModelSwitch suit le modele. Absent
    # ici alors qu'un modele est deja connu = rien a dire ; absent ET jamais vu = on le DIT.
    if not modele_normalise(entree.get("model")) and not (etat.get("vu") or {}).get("modele"):
        texte = (texte + "\n" if texte else "") + (
            "[audit-prompts] modele ILLISIBLE (absent de l'entree, jamais vu) : changement de modele non verifiable.")
    return texte


def section_changement_modele(entree_brute, chemin_etat):
    """Hook PostModelSwitch (`from_model` / `to_model`) -> rappel ou None ; sa sortie est livree a Claude."""
    entree = _entree_json(entree_brute)
    vers = modele_normalise(entree.get("to_model"))
    if not vers:
        return "[audit-prompts] PostModelSwitch sans `to_model` lisible : changement ILLISIBLE, etat inchange."
    texte, etat = rappel_audit(_lire_etat_audit(chemin_etat), vers, None)
    try:
        _ecrire_etat_audit(chemin_etat, etat)
    except OSError as exc:
        texte = (texte or "[audit-prompts]") + "\n  (etat NON ecrit : %s -- %s)" % (chemin_etat, type(exc).__name__)
    return texte


def alerte_cout_reprise(entree_brute):
    """SessionStart porte `prompt_cache_likely_expired` / `context_tokens` / `estimated_cache_write_usd`.

    Cache expire sur un gros fil = tout le contexte est re-ecrit au prochain tour. On le DIT avec les
    chiffres du hook ; sans le drapeau, on ne pretend rien (UNKNOWN != NO)."""
    entree = _entree_json(entree_brute)
    if entree.get("prompt_cache_likely_expired") is not True:
        return None
    ctx, usd = entree.get("context_tokens"), entree.get("estimated_cache_write_usd")
    secs = entree.get("seconds_since_last_response")
    return ("[cout-reprise] cache de prompt probablement EXPIRE (%s sans reponse) : ~%s tokens de contexte "
            "a re-ecrire au prochain tour (~%s $). Si le fil n'a plus besoin de tout, proposer /compact a "
            "l'owner avant de continuer." % (
                "%d min" % (secs // 60) if isinstance(secs, (int, float)) else "duree ?",
                "{:,}".format(ctx).replace(",", " ") if isinstance(ctx, int) else "?",
                "%.2f" % usd if isinstance(usd, (int, float)) else "?"))


def acquitter_audit(chemin_etat, argv):
    """`--audit-fait [--modele M] [--version V]` : l'audit couvre ce qui a ete VU (ou ce qui est donne)."""
    def _opt(nom):
        return argv[argv.index(nom) + 1] if nom in argv and argv.index(nom) + 1 < len(argv) else None

    etat = _lire_etat_audit(chemin_etat)
    vu = etat.get("vu") or {}
    modele = modele_normalise(_opt("--modele")) or vu.get("modele")
    version = _opt("--version") or vu.get("version")
    if not modele:
        print("[audit-prompts] REFUS : aucun modele vu ni donne (--modele) -- rien a acquitter")
        return 2
    etat["audite"] = {"modele": modele, "version": version,
                      "le": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    _ecrire_etat_audit(chemin_etat, etat)
    print("[audit-prompts] audit acquitte : modele %s, CLI %s (%s)" % (modele, version or "INCONNUE", chemin_etat))
    return 0


def _entree_hook():
    """JSON passe par Claude Code sur stdin ; vide hors hook (console, test)."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        return sys.stdin.read()
    except (OSError, ValueError):
        return ""


def load_token() -> str:
    """Jeton du hook. SON marqueur d'abord -- pas celui d'un autre organe.

    Corrige le 2026-09-02 : ce hook portait `FORGE_TOKEN_CLAUDE`, c'est-a-dire
    le credential d'un organe ring 1, tout en se declarant `CLAUDE_HOOK`
    (ring 4). Emprunter le marqueur d'un voisin est ce que la doctrine interdit
    -- chaque organe porte le sien -- et faisait circuler un credential
    privilegie dans un hook qui n'en a pas besoin. `FORGE_TOKEN_CLAUDE_HOOK` a
    ete provisionne au coffre : le hook est ainsi ramene a SON ring, ce qui est
    un durcissement et non une perte.

    L'ordre suit aussi la regle DPAPI : le COFFRE d'abord, `Nokido.env` n'etant
    plus qu'un repli legacy.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        tok = get_secret("FORGE_TOKEN_CLAUDE_HOOK")
        if tok:
            return tok
    except Exception:  # muet-ok : coffre indisponible -> replis ci-dessous, le hook ne doit jamais casser la session
        pass

    tok = os.environ.get("FORGE_TOKEN_CLAUDE_HOOK", "") or os.environ.get(
        "FORGE_TOKEN_CLAUDE", "")
    if tok:
        return tok
    env = ROOT / "Nokido.env"
    if env.exists():
        for line in env.read_text(errors="ignore").splitlines():
            if line.startswith("FORGE_TOKEN_CLAUDE_HOOK="):
                return line.split("=", 1)[1].strip()
            if line.startswith("FORGE_TOKEN_CLAUDE="):
                return line.split("=", 1)[1].strip()
            if line.startswith("FORGE_MCP_TOKEN=") and not tok:
                tok = line.split("=", 1)[1].strip()
    return tok


def hub_call(token: str, name: str, args: dict) -> str:
    try:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": args},
            }
        ).encode()
        req = urllib.request.Request(
            HUB,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                # Nom canonique (RFC 6648) + repli legacy le temps de la transition.
                "LaForge-Agent-Name": "CLAUDE_HOOK",
                "X-Agent-Name": "CLAUDE_HOOK",
            },
            method="POST",
        )
        r = json.loads(urllib.request.urlopen(req, timeout=4).read())
        return r.get("result", {}).get("content", [{}])[0].get("text", "")
    except Exception as e:
        return f"ERR:{e}"


def fetch_unread_inbox(limit: int = 5) -> list:
    if not M2M.exists():
        return []
    try:
        conn = sqlite3.connect(str(M2M))
        rows = conn.execute(
            "SELECT from_agent, status, created_at, substr(payload,1,300) "
            "FROM agent_messages WHERE to_agent='agt_claude' AND status='unread' "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [{"from": r[0], "ts": r[2], "preview": r[3]} for r in rows]
    except Exception:
        return []


SEEN_FILE = ROOT / "sandbox" / "claude_hook_seen.json"


def _load_seen() -> set:
    try:
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")).get("seen", []))
    except Exception:
        return set()


def _save_seen(seen: set) -> None:
    try:
        SEEN_FILE.parent.mkdir(exist_ok=True)
        SEEN_FILE.write_text(json.dumps({"seen": list(seen)[-500:]}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def fetch_tasks_inbox(limit: int = 8) -> list:
    """Directives task-queue (sandbox/tasks.db) assignees a CLAUDE, encore pending."""
    db = ROOT / "sandbox" / "tasks.db"
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT id, job_id, created_at, substr(description,1,260) FROM tasks "
            "WHERE status='pending' AND upper(agent)='CLAUDE' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [{"id": "task:%s" % (r[1] or r[0]), "from": "task-queue", "ts": r[2],
                 "preview": "[%s] %s" % (r[1] or r[0], (r[3] or "").strip())} for r in rows]
    except Exception:
        return []


def fetch_blackboard_inbox(max_age_days: float = 3.0, limit: int = 12) -> list:
    """Faits blackboard recents d'AUTRES agents (discovered_facts + scratch) = M2M entrants.
    Lecture DIRECTE de RAG/swarm.db (pas de hub_call : zero dependance auth/ring au boot)."""
    db = ROOT / "RAG" / "swarm.db"
    if not db.exists():
        return []
    try:
        cutoff = time.time() - max_age_days * 86400
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT zone, key, value, worker_id, updated_at FROM swarm_blackboard "
            "WHERE zone IN ('discovered_facts','scratch') AND upper(worker_id) NOT LIKE 'CLAUDE%' "
            "AND updated_at > ? ORDER BY updated_at DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    out = []
    for zone, key, value, wid, ts in rows:
        vs = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        out.append({"id": "blk:%s:%s:%s" % (zone, key, ts), "from": "%s@%s" % (wid, zone),
                    "ts": ts, "preview": "%s -- %s" % (key, (vs or "")[:200])})
    return out


def recent_lessons(max_chars: int = 1200) -> str:
    """Dernières leçons depuis lessons_learned.md — dédupliquées."""
    path = ROOT / "logs" / "lessons_learned.md"
    if not path.exists():
        return ""
    def _magnet(title: str) -> bool:
        # Exclut de l'injection de boot : blocs retires/perimes, et l'aimant de
        # vocabulaire declencheur du 2026-09-26 (source preservee sur disque ;
        # cf. feedback_anti_reflag_cyber_ne_pas_rapatrier_en_bloc).
        t = title or ""
        if "[PERIME]" in t or "[NOINJECT]" in t:
            return True
        if "2026-09-26" in t and "La fiche li" in t:
            return True
        return False
    try:
        text = path.read_text(errors="replace")
        # Extraire blocs ### uniques (dedup par titre)
        seen, blocks, current = set(), [], []
        for line in text.splitlines():
            if line.startswith("### "):
                if current:
                    body = "\n".join(current)
                    title = current[0]
                    # Dedup: ignorer si même titre/contenu déjà vu
                    key = title[:80]
                    if key not in seen and not _magnet(title):
                        seen.add(key)
                        blocks.append(body)
                current = [line]
            else:
                current.append(line)
        if current:
            key = current[0][:80]
            if key not in seen and not _magnet(current[0]):
                blocks.append("\n".join(current))
        # Garder les N derniers blocs uniques tenant dans max_chars
        result = []
        total = 0
        for b in reversed(blocks):
            if total + len(b) > max_chars:
                break
            result.insert(0, b)
            total += len(b)
        return "\n".join(result).strip()
    except Exception:
        return ""


def recent_anchors(limit: int = 4) -> str:
    """Anchres RAG récentes (hors beir_*) pour rappel contexte."""
    if not DB.exists():
        return ""
    try:
        conn = sqlite3.connect(str(DB))
        rows = conn.execute(
            "SELECT source, substr(text,1,120) FROM rag_chunks "
            "WHERE domain IN ('solution','error','architecture','session','rag','security','llm') "
            "ORDER BY rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        if not rows:
            return ""
        lines = ["=== Anchres RAG récentes ==="]
        for src, txt in rows:
            lines.append(f"  [{src}] {txt.strip()[:100]}")
        return "\n".join(lines)
    except Exception:
        return ""


def fetch_postal_inbox(limit: int = 6) -> list:
    """Canal POSTAL (RAG/postal.db) — séparé de agent_messages ; sinon les M2M
    des pairs (AGY/Gemini/...) arrivent en 'delivered' mais ne remontent jamais
    au boot. Read-only : la dedup se fait via seen.json comme les autres canaux."""
    db = Path(__file__).resolve().parents[1] / "RAG" / "postal.db"
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(str(db), timeout=5)
        rows = conn.execute(
            "SELECT id, sender, ts_queued, substr(body,1,300) FROM mail "
            "WHERE upper(recipient) IN ('CLAUDE', 'AGT_CLAUDE') AND status='delivered' "
            "ORDER BY ts_queued DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [{"id": "postal:%s" % r[0], "from": r[1], "ts": r[2], "preview": r[3]} for r in rows]
    except Exception:
        return []


def refresh_symptom_index(max_age_h: float = 12.0) -> None:
    """Rafraichit l'index d'enquetes s'il vieillit — DETACHE, jamais bloquant.

    Un index d'enquetes PERIME est pire qu'absent : interroge sur un symptome deja
    explore, il repond « terrain neuf » et rend le faux negatif invisible. C'est
    exactement le defaut que cet index sert a corriger, applique a lui-meme.

    Le `--build` lit ~64 transcripts + le corpus RAG (~1 min) : on ne fait PAS
    attendre le demarrage de session, on lance en fond et on le DIT. Et un index
    absent est distingue d'un index vieux, jamais confondu avec un index frais.
    """
    import subprocess

    idx = ROOT / "sandbox" / "enquetes_index.json"
    outil = ROOT / "tools" / "forge_symptom_index.py"
    if not outil.exists():
        print(f"[claude-hook] index d'enquetes : outil absent ({outil.name})")
        return
    # MEMOIRE PARTAGEE : generisee, versionnee, livree dans le dist — alors que
    # l'index local ne l'est pas. Chez un contributeur elle est la SEULE memoire,
    # et sans ce rappel il croirait n'en avoir aucune et lancerait un `--build`
    # qui n'a aucun transcript a lire.
    partage = ROOT / "docs" / "enquetes_partagees.jsonl"
    if idx.exists():
        age_h = (time.time() - idx.stat().st_mtime) / 3600.0
        if age_h < max_age_h:
            print(f"[claude-hook] index d'enquetes frais ({age_h:.1f} h) — "
                  f"`forge_symptom_index.py --ask <symptome>` avant toute enquete")
            return
        etat = f"perime ({age_h:.0f} h)"
    else:
        etat = "ABSENT"
        if partage.is_file():
            print("[claude-hook] index local absent, mais la memoire PARTAGEE est "
                  "la (docs/enquetes_partagees.jsonl) — `forge_symptom_index.py "
                  "--ask <symptome>` la lit deja")
            return
    try:
        subprocess.Popen(
            [sys.executable, str(outil), "--build"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(ROOT),
        )
        print(f"[claude-hook] index d'enquetes {etat} -> rebuild lance en fond")
    except Exception as e:  # noqa: BLE001
        print(f"[claude-hook] rebuild index IMPOSSIBLE ({type(e).__name__}) — "
              f"les rappels « deja explore » seront muets jusqu'a un build manuel")


def roadmap_summary() -> str:
    """Roadmap SSoT au démarrage — pour que les PROJETS GARÉS resurgissent chaque session.

    Ajouté le 2026-08-02 : le boot surfaçait inbox/tâches/leçons/ancres mais PAS le
    roadmap. Résultat mesuré : un projet validé par l'owner (architecture hybride,
    forge_debate_job) est resté garé 2 semaines parce que rien ne le rappelait au
    démarrage. Le SSoT (docs/roadmap_state.json, alimenté par forge_ssot_maintainer
    depuis le blackboard) porte current/next/blockers — on les MONTRE.
    """
    doc = Path(__file__).resolve().parent.parent / "docs" / "roadmap_state.json"
    try:
        data = json.loads(doc.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return ""  # muet-ok : pas de SSoT = pas de rappel, le reste du boot suffit
    # Le FICHIER roadmap_state.json porte les clés au TOP-LEVEL ; c'est forge_ssot.point()
    # qui les enveloppe sous "answer". On lit le fichier -> top-level (vérifié 2026-08-02).
    cur = (data.get("current_milestone") or "").strip()
    nxt = (data.get("next_milestone") or "").strip()
    blk = data.get("blockers") or []
    if not (cur or nxt or blk):
        return ""
    lignes = ["=== Roadmap SSoT (projets suivis — ne pas laisser tomber) ==="]
    if cur:
        lignes.append(f"  CURRENT : {cur[:200]}")
    if nxt:
        lignes.append(f"  NEXT    : {nxt[:200]}")
    for b in blk[:4]:
        lignes.append(f"  BLOCKER : {str(b)[:180]}")
    return "\n".join(lignes)


def main() -> int:
    # Fix encodage Windows cp1252 → utf-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--audit-fait" in sys.argv:
        return acquitter_audit(ETAT_AUDIT, sys.argv)
    if "--changement-modele" in sys.argv:  # hook PostModelSwitch : seulement le rappel, rien d'autre
        texte = section_changement_modele(_entree_hook(), ETAT_AUDIT)
        if texte:
            print(texte)
        return 0

    token = load_token()

    # ── 1. Brief RAG compact ──────────────────────────────────────────────────
    print(REGLES)

    entree_hook = _entree_hook()
    for bloc in (section_audit(entree_hook, ETAT_AUDIT), alerte_cout_reprise(entree_hook)):
        if bloc:
            print("\n" + bloc)

    # Résumé session précédente (généré par PreCompact hook)
    if SUMMARY.exists():
        try:
            summary_text = SUMMARY.read_text(encoding="utf-8", errors="replace").strip()
            if summary_text:
                print(f"\n{summary_text}")
        except Exception:
            pass

    lessons = recent_lessons(1200)
    if lessons:
        print(f"\n=== Leçons récentes (dédupl.) ===\n{lessons}")

    anchors = recent_anchors(4)
    if anchors:
        print(f"\n{anchors}")

    roadmap = roadmap_summary()
    if roadmap:
        print(f"\n{roadmap}")

    # ── 2. Inbox agent_messages ───────────────────────────────────────────────
    # Digest MULTI-CANAL : UN point de lecture au boot. Peu importe ou l'agent
    # emetteur ecrit (agent_messages / tasks.db / blackboard), rien ne se perd.
    # Dedup via sandbox/claude_hook_seen.json (jamais re-surface le meme msg).
    seen = _load_seen()
    items = []
    for m in fetch_unread_inbox(limit=6):
        m.setdefault("id", "msg:%s:%s" % (m.get("from"), m.get("ts")))
        items.append(m)
    items.extend(fetch_tasks_inbox(limit=8))
    items.extend(fetch_blackboard_inbox(max_age_days=3.0, limit=12))
    items.extend(fetch_postal_inbox(limit=6))
    fresh = [it for it in items if it.get("id") not in seen]
    if fresh:
        print(f"\n[claude-hook] INBOX MULTI-CANAL — {len(fresh)} message(s) non vu(s) :")
        for it in fresh:
            prev = (it.get("preview") or "")[:150].replace("\n", " ")
            print(f"  - [{it.get('from')} @ {it.get('ts')}] {prev}")
        print("[claude-hook] canaux: agent_messages + tasks.db + blackboard(discovered_facts,scratch) + postal")
        for it in fresh:
            seen.add(it.get("id"))
        _save_seen(seen)
    else:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"\n[claude-hook] inbox multi-canal propre ({now})")

    # ── 3bis. Index d'enquetes (non bloquant) ─────────────────────────────────
    refresh_symptom_index()

    # ── 4. Notify hub ─────────────────────────────────────────────────────────
    if token:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        hub_call(
            token,
            "hub",
            {"action": "notify", "message": f"[GEMINI] [CLAUDE-HOOK] session online {now}"},
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
