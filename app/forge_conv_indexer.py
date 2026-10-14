# -*- coding: utf-8 -*-
"""
forge_conv_indexer.py — Indexation conversations CLI (Claude, Gemini, AGY, Codex) dans RAG
==========================================================================================
Transforme les sessions JSONL/JSON des CLIs en chunks RAG searchables.
Sources:
  - Claude CLI : ~/.claude/projects/<project>/*.jsonl
  - Gemini CLI : ~/.gemini/tmp/<project>/chats/session-*.json et session-*.jsonl (TOUS les projets)
  - Codex CLI  : ~/.codex/sessions/AAAA/MM/JJ/rollout-<horodatage>-<uuid>.jsonl
  - AGY CLI    : ~/.gemini/antigravity-cli/brain/<uuid>/.system_generated/logs/transcript.jsonl
  - Swarm      : ABSENT (reconnaissance 2026-10-13 : pas de journaux de conversation continus)

Chunks produits: source = conv_claude/<session_id>/<turn_idx>
                          conv_gemini/<session_id>/<turn_idx>
                          conv_codex/<session_id>/<turn_idx>
                          conv_agy/<session_id>/<turn_idx>
Dedup: INSERT OR IGNORE sur id = sha256(source+text)[:16]
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re as _re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterator

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

log = logging.getLogger("forge.conv_indexer")

ROOT = Path(__file__).resolve().parent.parent
RAG_DB = ROOT / "RAG" / "embeddings.db"

# HOME du PROPRIETAIRE, pas du process.
#
# `Path.home()` vaut `C:\Users\Default` des que le module tourne sous un compte de
# service (LaForgeTrusted, LaForgeSbx*) : l'indexeur cherchait alors
# `C:\Users\Default\.claude\projects`, ne trouvait rien, et rendait « aucun projet
# Claude CLI » — en SILENCE, avec `ok: false` que personne ne lisait. Il ne pouvait
# donc indexer QUE lors d'une execution en session owner (mesure 2026-08-12, meme
# classe que le gotcha `expanduser("~")` du 2026-08-11).
#
# Les historiques a indexer sont ceux de l'OWNER. On derive donc son HOME du chemin
# du depot (<home>/Script python IA/Nokido), ce qui reste vrai quel que soit le
# compte qui execute. Surchargeable par LAFORGE_OWNER_HOME.
OWNER_HOME = Path(os.environ.get("LAFORGE_OWNER_HOME") or ROOT.parent.parent)

# Dossiers sources
CLAUDE_HISTORY = OWNER_HOME / ".claude" / "projects"
GEMINI_HISTORY = OWNER_HOME / ".gemini" / "tmp"
CODEX_HISTORY = OWNER_HOME / ".codex"
# AGY / Antigravity CLI : un dossier par session (UUID), transcript sous
# <uuid>/.system_generated/logs/transcript.jsonl. 150 sessions mesurees le
# 2026-08-12, ZERO ingeree -- cette source n'existait tout simplement pas ici.
AGY_HISTORY = OWNER_HOME / ".gemini" / "antigravity-cli" / "brain"
# Claude Desktop export: dossier contenant conversations.json + projects/*.json
CLAUDE_DESKTOP_DEFAULT = ROOT.parent / "data-Claude-Desktop-03052026"
# Gemini Web export: dossier contenant les *.txt (NousSave exporter format)
GEMINI_WEB_DEFAULT = ROOT.parent / "SessionGeminiWeb"

# ─────────────────────────────────────────────────────────────────────────────
# REGISTRE DECLARATIF DES SOURCES
# ─────────────────────────────────────────────────────────────────────────────
# Chaque source etait codee en dur, donc un nouveau CLI restait INVISIBLE jusqu'a
# ce que quelqu'un s'en souvienne. Le 2026-08-12 : Claude plafonne a 20 sessions,
# AGY totalement absent, Gemini CLI pointe sur un chemin mort depuis sa disparition.
# Trois symptomes, une seule cause : aucun endroit ou un agent puisse se declarer.
#
# Ce registre est la source de verite de ce qui est COUVERT. Il sert a deux choses :
#   1. documenter/ajouter une source sans toucher au code (une entree = un agent) ;
#   2. alimenter le detecteur d'agents INCONNUS (forge_regression_sweep, axe
#      `agents`) : tout transcript qu'aucune entree ne couvre est signale.
# `motif` est un glob relatif a `racine`, evalue paresseusement (les racines
# peuvent ne pas exister sur une autre machine).
SOURCES: list[dict] = [
    {"nom": "claude_cli", "prefixe": "conv_claude", "motif": "**/*.jsonl"},
    {"nom": "gemini_cli", "prefixe": "conv_gemini", "motif": "*/chats/session-*.json"},
    {"nom": "gemini_cli_jsonl", "prefixe": "conv_gemini", "motif": "*/chats/session-*.jsonl"},
    {"nom": "codex_cli", "prefixe": "conv_codex", "motif": "sessions/**/*.jsonl"},
    {"nom": "agy_antigravity", "prefixe": "conv_agy",
     "motif": "*/.system_generated/logs/transcript.jsonl"},
    {"nom": "claude_desktop", "prefixe": "conv_claude_desktop", "motif": "conversations.json"},
    {"nom": "gemini_web", "prefixe": "conv_gemini_web", "motif": "*.txt"},
]


def racines_couvertes() -> dict[str, Path]:
    """Racine de chaque source declaree. Resolue tard : les chemins dependent du poste."""
    return {
        "claude_cli": CLAUDE_HISTORY,
        "gemini_cli": GEMINI_HISTORY,
        "gemini_cli_jsonl": GEMINI_HISTORY,
        "codex_cli": CODEX_HISTORY,
        "agy_antigravity": AGY_HISTORY,
        "claude_desktop": CLAUDE_DESKTOP_DEFAULT,
        "gemini_web": GEMINI_WEB_DEFAULT,
    }


def fichiers_couverts() -> set[Path]:
    """Ensemble des fichiers qu'au moins une source declaree sait indexer."""
    racines = racines_couvertes()
    couverts: set[Path] = set()
    for s in SOURCES:
        racine = racines.get(s["nom"])
        if racine is None or not racine.exists():
            continue
        try:
            couverts.update(p.resolve() for p in racine.glob(s["motif"]) if p.is_file())
        except OSError:
            continue  # muet-ok : racine illisible = non couverte, le detecteur de couverture le dit
    return couverts


# Taille max chunk texte (chars)
CHUNK_MAX = 2000
# Taille min pour indexer (évite les one-liners vides)
CHUNK_MIN = 40


# ─────────────────────────────────────────────────────────────────────────────
# Extraction Claude CLI JSONL
# ─────────────────────────────────────────────────────────────────────────────


def _extract_text(content) -> str:
    """Normalise le contenu d'un message (str, list, dict) → texte plat."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item["text"]))
                elif "content" in item:
                    parts.append(_extract_text(item["content"]))
        return " ".join(parts).strip()
    if isinstance(content, dict):
        return _extract_text(content.get("text") or content.get("content") or "")
    return str(content).strip()


def _ts_epoch(val) -> "int | None":
    """Horodatage ISO d'un message -> epoch, ou None.

    Mesure 2026-08-12 : les transcripts portent un `timestamp` par message (2 962
    dans la seule session du jour) et l'indexeur les JETAIT. Resultat en base :
    `created_at` NULL sur 37 715 chunks, `sequence_id` NULL sur 37 715 — donc
    aucune chronologie, donc impossible de respecter l'EVOLUTION des demandes
    (une consigne de mars annulee en aout etait indiscernable d'une consigne
    vivante). Le schema prevoit pourtant `superseded_by` / `active` / `version` :
    tout ce mecanisme etait inalimentable faute de dates.

    ⚠️ Ne pas confondre avec `ingested_at` (quand NOUS avons lu la ligne) : c'est
    exactement la confusion qui avait produit un « verdict artefactuel » le
    2026-07-29.
    """
    if not val:
        return None
    # AGY ecrit parfois un epoch numerique la ou Claude ecrit de l'ISO : accepter
    # les deux, sinon la moitie du corpus reste sans date pour une question de
    # format. Borne de sanite : on refuse tout ce qui tombe hors [2020, 2100[,
    # une date absurde etant pire qu'une absence de date (elle fausserait
    # silencieusement tout arbitrage de chronologie).
    try:
        if isinstance(val, (int, float)):
            n = float(val)
        else:
            s = str(val).strip()
            if s.replace(".", "", 1).isdigit():
                n = float(s)
            else:
                import datetime as _d

                n = _d.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        if n > 4102444800:      # millisecondes -> secondes
            n /= 1000.0
        return int(n) if 1577836800 <= n < 4102444800 else None
    except Exception:
        return None


def _lignes_json(lignes: list[str], chemin: Path) -> Iterator[dict]:
    """Objets JSON d'une session JSONL. Une ligne non JSON (ecriture coupee, corruption) ou qui n'est
    pas un objet est ECARTEE ET COMPTEE : le total est dit en WARNING, jamais avale en silence (gate
    recidive, 2026-10-13). Un objet non-dict faisait aussi planter `msg.get` sur la session entiere."""
    ecartees = 0
    for ligne in lignes:
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            msg = json.loads(ligne)
        except json.JSONDecodeError:
            ecartees += 1
            continue
        if isinstance(msg, dict):
            yield msg
        else:
            ecartees += 1
    if ecartees:
        log.warning("[conv_indexer] %s : %d ligne(s) non JSON ou non objet ecartee(s)", chemin, ecartees)


# ── DIGESTION (owner 14/10 : « ne garder que la substantifique moelle, sinon la base va exploser ») ──────────
# Mesure du 14/10 (session 7f39f6bd) : 2 146 tool_result, 2 488 rappels systeme, 4 970 entrees meta/reflexion/
# piece jointe/systeme pour quelques dizaines de messages humains ; `_extract_text` descendait dans `content` et
# indexait chaque sortie d'outil comme un tour « user » (2 203 segments user pour 1 017 assistant en base).
_RAPPEL = _re.compile(r"<system-reminder>.*?</system-reminder>", _re.S)
_ENVELOPPES = _re.compile(r"</?(command-name|command-message|command-args|local-command-stdout|"
                          r"local-command-stderr|bash-input|bash-stdout|bash-stderr)>")
PREFIXE_EPURE = "conv_claude_m"              # un fragment par message retenu, identite stable
MOTIF_GEL = "affinage:conv_epure_v2"          # motif des fenetres anciennes gelees (reversible)


def _nettoyer(texte: str) -> str:
    return _ENVELOPPES.sub("", _RAPPEL.sub("", texte)).strip()


def tours_epures(entrees) -> tuple[list, dict]:
    """ETAGE 1 : humain = `content` chaine ; tool_result, thinking, tool_use, isMeta, attachment ecartes ; resume
    de compaction garde. Rend ([(role, texte, horodatage)], compte PAR MOTIF d'ecart)."""
    tours, vus = [], set()
    compte = {"humain": 0, "assistant": 0, "resume": 0, "sortie_outil": 0, "reflexion_ou_appel": 0,
              "meta": 0, "trivial": 0, "doublon": 0}
    for e in entrees:
        if not isinstance(e, dict):
            continue
        t = e.get("type")
        if t not in ("user", "assistant") or e.get("isMeta"):
            compte["meta"] += 1
            continue
        contenu = (e.get("message") or {}).get("content")
        role = "resume" if e.get("isCompactSummary") else ("humain" if t == "user" else "assistant")
        textes = []
        if isinstance(contenu, str):
            textes.append(contenu)
        elif isinstance(contenu, list):
            for b in contenu:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    textes.append(str(b.get("text") or ""))
                elif b.get("type") == "tool_result":
                    compte["sortie_outil"] += 1
                else:
                    compte["reflexion_ou_appel"] += 1
        texte = _nettoyer("\n".join(textes))
        if len(texte) < CHUNK_MIN:
            if textes:
                compte["trivial"] += 1
            continue
        cle = (role, _re.sub(r"\s+", " ", texte).lower())
        if cle in vus:
            compte["doublon"] += 1
            continue
        vus.add(cle)
        compte[role] += 1
        tours.append((role, texte, e.get("timestamp")))
    return tours, compte


def moelle(tours: list) -> tuple[list, int]:
    """ETAGE 2 : par tour de parole, l'humain + le DERNIER texte assistant (celui qui conclut) ; resumes gardes ;
    la narration intermediaire est ecartee (le transcript reste sur disque). Rend (gardes, narrations ecartees)."""
    gardes, attente, ecartees = [], None, 0
    for role, texte, ts in tours:
        if role == "assistant":
            ecartees += attente is not None
            attente = (role, texte, ts)
            continue
        if attente is not None:
            gardes.append(attente)
            attente = None
        gardes.append((role, texte, ts))
    if attente is not None:
        gardes.append(attente)
    return gardes, ecartees


def _decouper_sans_perte(texte: str, taille: int) -> list:
    """ETAGE 3 : un message long est DECOUPE (fin de ligne ou d'espace si possible), jamais tronque."""
    out, reste = [], texte
    while len(reste) > taille:
        coupe = max(reste.rfind("\n", 0, taille), reste.rfind(" ", 0, taille))
        coupe = coupe if coupe > taille // 2 else taille
        out.append(reste[:coupe])
        reste = reste[coupe:].lstrip()
    if reste:
        out.append(reste)
    return out


def iter_claude_chunks(jsonl_path: Path) -> Iterator[tuple]:
    """
    Génère (source, text) pour chaque tour utilisateur/assistant.
    source = conv_claude/<session_id>/<idx>
    """
    session_id = jsonl_path.stem
    turns: list = []  # (role, text, ts_epoch|None)

    try:
        lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        log.warning("Impossible de lire %s: %s", jsonl_path, e)
        return

    for msg in _lignes_json(lines, jsonl_path):
        mtype = msg.get("type", "")
        if mtype not in ("user", "assistant"):
            continue

        raw = msg.get("message", {})
        if isinstance(raw, dict):
            content = raw.get("content", "")
        else:
            content = raw

        text = _extract_text(content)
        if len(text) >= CHUNK_MIN:
            turns.append((mtype, text, _ts_epoch(msg.get("timestamp"))))

    # Regroupe en fenêtres user+assistant pour contexte
    idx = 0
    i = 0
    while i < len(turns):
        role, text, ts_msg = turns[i]
        # Inclure le prochain tour si ça rentre
        window = text
        if i + 1 < len(turns) and len(text) + len(turns[i + 1][1]) < CHUNK_MAX:
            window = f"[{role}] {text}\n[{turns[i + 1][0]}] {turns[i + 1][1]}"
            i += 2
        else:
            window = f"[{role}] {text}"
            i += 1

        # Tronquer si trop long
        window = window[:CHUNK_MAX]
        source = f"conv_claude/{session_id}/{idx}"
        # 3e element = QUAND la phrase a ete prononcee. Sans lui, 37 715 chunks
        # sans aucune date exploitable : impossible de savoir si une demande de
        # mars a ete remplacee en aout. Cf `_ts_epoch`.
        yield source, window, ts_msg
        idx += 1


def iter_claude_epure(jsonl_path: Path, motifs: dict) -> Iterator[tuple]:
    """(source, texte, horodatage) par message RETENU (etages 1 a 3). Source = conv_claude_m/<session>/<id12>[.k] :
    l'identite depend du message, pas d'une fenetre -- un transcript qui grandit re-produit les memes fragments.
    `motifs` additionne les ecarts PAR MOTIF : c'est la mesure que la base n'avait pas."""
    sid = jsonl_path.stem
    try:
        lignes = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        log.warning("[conv_indexer] %s illisible (%s) : session NON digeree", jsonl_path.name, type(e).__name__)
        motifs["sessions_illisibles"] = motifs.get("sessions_illisibles", 0) + 1
        return
    tours, compte = tours_epures(_lignes_json(lignes, jsonl_path))
    gardes, narrations = moelle(tours)
    compte["narration_intermediaire"] = narrations
    for k, v in compte.items():
        motifs[k] = motifs.get(k, 0) + v
    yield from _fragments_claude(sid, gardes)


def _fragments_claude(sid: str, gardes: list) -> Iterator[tuple]:
    """Formatage UNIQUE des fragments epures (passe complete ET incrementale) : meme message = meme identite."""
    for role, texte, ts_iso in gardes:
        ident = hashlib.sha256("|".join(["claude", sid, role, str(ts_iso or ""),
                                         _re.sub(r"\s+", " ", texte).lower()]).encode()).hexdigest()[:12]
        entete = "[%s] %s\n" % (role, str(ts_iso or "date ?")[:10])
        parts = _decouper_sans_perte(texte, CHUNK_MAX - len(entete))
        for k, p in enumerate(parts):
            yield ("%s/%s/%s%s" % (PREFIXE_EPURE, sid, ident, ".%d" % k if len(parts) > 1 else ""),
                   entete + p, _ts_epoch(ts_iso))


def geler_ancien(session_id: str, db_path: Path | None = None) -> int:
    """Gele (active=0 + MOTIF_GEL, reversible, jamais supprime) les fenetres de l'ANCIEN schema de CETTE session.
    Plage de source indexee (idx_rag_source) : `conv_claude/<id>/` <= source < `conv_claude/<id>0` ('0' suit '/')
    -- jamais LIKE ; `+active` pour ne pas partir sur l'index peu selectif d'active."""
    db_path = db_path or RAG_DB
    bas = "conv_claude/%s/" % session_id
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("UPDATE rag_chunks SET active=0, retraction_status=? "
                    "WHERE source >= ? AND source < ? AND +active = 1", (MOTIF_GEL, bas, bas[:-1] + "0"))
        n = con.execute("SELECT changes()").fetchone()[0]
        con.commit()
        return n
    finally:
        con.close()


# ─────────────────────────────────────────────────────────────────────────────
# Extraction AGY / Antigravity CLI (transcript.jsonl)
# ─────────────────────────────────────────────────────────────────────────────


def iter_agy_chunks(jsonl_path: Path) -> Iterator[tuple[str, str]]:
    """
    Génère (source, text) depuis un transcript AGY.

    Schéma mesuré (2026-08-12) : une ligne JSON par étape, avec
    {step_index, source, type, status, created_at, content, tool_calls[{name,args}]}.

    Les `tool_calls` sont conservés sous forme de marqueurs `[tool: nom]` DANS le
    texte : c'est la seule trace de SÉQUENCE d'outils disponible côté AGY, et donc
    la matière première du graphe de dépendances (network_log, lui, n'a pas de
    session_id exploitable). Les jeter reviendrait à indexer la conversation en
    perdant ce qu'elle prouve.

    On lit `transcript.jsonl` et non `transcript_full.jsonl` : même contenu utile,
    moitié moins de volume, et pas de doublon dans le RAG.
    """
    session_id = jsonl_path.parent.parent.parent.name[:16]
    turns: list = []  # (role, texte, ts_epoch|None)

    try:
        lignes = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        log.warning("Impossible de lire %s: %s", jsonl_path, e)
        return

    for msg in _lignes_json(lignes, jsonl_path):
        role = str(msg.get("source") or msg.get("type") or "agy")[:20]
        texte = _extract_text(msg.get("content", ""))

        outils = []
        for tc in msg.get("tool_calls") or []:
            if isinstance(tc, dict) and tc.get("name"):
                outils.append(str(tc["name"])[:40])
        if outils:
            texte = (texte + " " if texte else "") + " ".join(f"[tool: {o}]" for o in outils)

        if len(texte) >= CHUNK_MIN:
            # AGY porte `created_at` dans chaque etape — la meme information que
            # le `timestamp` des transcripts Claude. Elle etait jetee ici aussi :
            # 10 611 chunks AGY sans aucune date, donc hors chronologie.
            turns.append((role, texte, _ts_epoch(msg.get("created_at"))))

    idx = 0
    i = 0
    while i < len(turns):
        role, texte, ts_msg = turns[i]
        if i + 1 < len(turns) and len(texte) + len(turns[i + 1][1]) < CHUNK_MAX:
            fenetre = f"[{role}] {texte}\n[{turns[i + 1][0]}] {turns[i + 1][1]}"
            i += 2
        else:
            fenetre = f"[{role}] {texte}"
            i += 1
        yield f"conv_agy/{session_id}/{idx}", fenetre[:CHUNK_MAX], ts_msg
        idx += 1


def index_agy_sessions(brain_dir: Path | None = None, limit_sessions: int = 0) -> dict:
    """Indexe les sessions AGY / Antigravity CLI. `limit_sessions=0` = TOUTES."""
    brain_dir = brain_dir if brain_dir is not None else AGY_HISTORY
    if not brain_dir.exists():
        return {"ok": False, "error": f"dossier AGY introuvable ou illisible: {brain_dir}"}

    tous = sorted(brain_dir.glob("*/.system_generated/logs/transcript.jsonl"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    fichiers = tous if limit_sessions <= 0 else tous[:limit_sessions]
    if not fichiers:
        return {"ok": False, "error": f"aucun transcript.jsonl sous {brain_dir}"}

    total: list[tuple[str, str]] = []
    stats: dict[str, int] = {}
    for f in fichiers:
        morceaux = list(iter_agy_chunks(f))
        total.extend(morceaux)
        stats[f.parent.parent.parent.name[:16]] = len(morceaux)

    inserted = _insert_chunks(total)
    log.info("[conv_indexer] AGY: %d sessions, %d chunks, %d inserted",
             len(fichiers), len(total), inserted)
    return {"ok": True, "sessions": len(fichiers), "chunks": len(total),
            "inserted": inserted, "per_file": stats}


# ─────────────────────────────────────────────────────────────────────────────
# Extraction Gemini CLI JSON
# ─────────────────────────────────────────────────────────────────────────────


def _fenetres_sans_perte(turns: list, prefixe: str, session_id: str) -> Iterator[tuple[str, str, int | None]]:
    """Fenetres (source, texte, ts) d'une source NEUVE : deux tours se groupent s'ils tiennent dans
    CHUNK_MAX ; une fenetre plus longue est DECOUPEE en suites au lieu d'etre coupee a CHUNK_MAX (owner
    2026-10-13 : le retenu ne se tronque pas). Les sources deja en base (Claude, AGY, Gemini .json)
    gardent leur `window[:CHUNK_MAX]` : changer leur fenetrage renumeroterait leurs morceaux."""
    idx = 0
    i = 0
    while i < len(turns):
        role, text, ts = turns[i]
        if i + 1 < len(turns) and len(text) + len(turns[i + 1][1]) < CHUNK_MAX:
            fenetre = f"[{role}] {text}\n[{turns[i + 1][0]}] {turns[i + 1][1]}"
            i += 2
        else:
            fenetre = f"[{role}] {text}"
            i += 1
        for k in range(0, len(fenetre), CHUNK_MAX):
            yield f"{prefixe}/{session_id}/{idx}", fenetre[k:k + CHUNK_MAX], ts
            idx += 1


def iter_gemini_jsonl_chunks(jsonl_path: Path) -> Iterator[tuple[str, str, int | None]]:
    """
    Génère (source, text, ts_epoch|None) pour chaque message d'une session Gemini CLI au format JSONL.
    source = conv_gemini/<session_id>/<idx>

    Forme mesuree le 2026-10-13 (44 sessions) : 1re ligne = en-tete `{"sessionId", ...}`, puis un tour
    par ligne `{"timestamp", "type": "user"|"gemini"|"info", "content": [{"text"}]}`. L'identifiant vient
    de `sessionId` : `stem[:16]` vaut `session-2026-07-` pour toutes les sessions d'un meme mois.
    """
    session_id = ""
    turns: list[tuple[str, str, int | None]] = []

    try:
        lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        log.warning("Impossible de lire %s: %s", jsonl_path, e)
        return

    for msg in _lignes_json(lines, jsonl_path):
        if not session_id and msg.get("sessionId"):
            session_id = str(msg["sessionId"])[:16]

        mtype = str(msg.get("type") or msg.get("role") or msg.get("source") or "")
        raw_content = msg.get("content") or msg.get("parts") or msg.get("message") or msg.get("text") or ""
        if isinstance(raw_content, dict):
            mtype = str(raw_content.get("role") or raw_content.get("type") or mtype)
            content = raw_content.get("content") or raw_content.get("text") or ""
        else:
            content = raw_content

        if mtype not in ("user", "gemini", "model", "assistant"):
            continue

        text = _extract_text(content)
        if len(text) >= CHUNK_MIN:
            ts_epoch = _ts_epoch(msg.get("timestamp") or msg.get("created_at") or msg.get("time"))
            turns.append((mtype, text, ts_epoch))

    yield from _fenetres_sans_perte(turns, "conv_gemini", session_id or jsonl_path.stem)


def iter_gemini_chunks(json_path: Path) -> Iterator[tuple[str, str, int | None]]:
    """
    Génère (source, text, ts_msg) pour chaque message user/gemini significatif (.json ou .jsonl).
    source = conv_gemini/<session_id>/<idx>
    """
    if json_path.suffix == ".jsonl":
        yield from iter_gemini_jsonl_chunks(json_path)
        return

    try:
        data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        log.warning("Impossible de lire %s: %s", json_path, e)
        return

    session_id = data.get("sessionId", json_path.stem)[:16]
    messages = data.get("messages", [])
    turns: list[tuple[str, str, int | None]] = []

    for msg in messages:
        mtype = msg.get("type", "")
        if mtype not in ("user", "gemini"):
            continue
        content = msg.get("content", "")
        text = _extract_text(content)
        if len(text) >= CHUNK_MIN:
            ts_epoch = _ts_epoch(msg.get("timestamp") or msg.get("created_at") or msg.get("time"))
            turns.append((mtype, text, ts_epoch))

    idx = 0
    i = 0
    while i < len(turns):
        role, text, ts_msg = turns[i]
        window = text
        if i + 1 < len(turns) and len(text) + len(turns[i + 1][1]) < CHUNK_MAX:
            window = f"[{role}] {text}\n[{turns[i + 1][0]}] {turns[i + 1][1]}"
            i += 2
        else:
            window = f"[{role}] {text}"
            i += 1

        window = window[:CHUNK_MAX]
        source = f"conv_gemini/{session_id}/{idx}"
        yield source, window, ts_msg
        idx += 1


# ─────────────────────────────────────────────────────────────────────────────
# Extraction Gemini Web (NousSave exporter — *.txt Markdown + YAML frontmatter)
# ─────────────────────────────────────────────────────────────────────────────


def _parse_gemini_web_frontmatter(text: str) -> dict:
    """Extrait le frontmatter YAML simplifié (title, date, url)."""
    m = _re.match(r"^---\n(.*?)\n---", text, _re.DOTALL)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
    return meta


def _strip_gemini_web_boilerplate(raw: str) -> str:
    """
    Supprime le frontmatter YAML, le bloc de stats, les artefacts NousSave
    et nettoie les marqueurs de rôle pour livrer du Markdown propre
    passable au MarkdownChunker.
    """
    # 1. Supprimer le frontmatter --- ... ---
    text = _re.sub(r"^---\n.*?\n---\n", "", raw, flags=_re.DOTALL)
    # 2. Supprimer le titre H1 redondant (déjà dans frontmatter)
    text = _re.sub(r"^# .+\n", "", text, count=1)
    # 3. Supprimer le bloc de stats (🔗 / 📅 / > Statistiques)
    text = _re.sub(r"🔗 \*\*Lien.*?\n", "", text)
    text = _re.sub(r"📅 \*\*Export.*?\n", "", text)
    text = _re.sub(r"> \*\*Statistiques\*\*.*?(?=\n\n)", "", text, flags=_re.DOTALL)
    # 4. Supprimer les ancres HTML <a id="..."></a>
    text = _re.sub(r'<a id="[^"]*"></a>\n', "", text)
    # 5. Nettoyer les lignes de timestamp *🕐 ...*
    text = _re.sub(r"\*🕐[^\n]*\*\n", "", text)
    # 6. Supprimer "> Vous avez dit" et dépiler le blockquote (> ) des msgs user
    text = _re.sub(r"> Vous avez dit\n", "", text)
    text = _re.sub(r"^> ", "", text, flags=_re.MULTILINE)
    # 7. Renommer les headers de rôle en Markdown propre
    text = text.replace("## 👤 Utilisateur", "## [user]")
    text = text.replace("## 🤖 gemini", "## [gemini]")
    # 8. Footer NousSave
    text = _re.sub(r"\*Généré par \[NousSave.*\n?", "", text)
    # 9. Supprimer les séparateurs --- orphelins
    text = _re.sub(r"\n---\n", "\n", text)
    return text.strip()


def iter_gemini_web_chunks(txt_path: Path) -> Iterator[tuple[str, str]]:
    """
    Génère (source, text) depuis un fichier .txt export NousSave Gemini Web.
    Utilise MarkdownChunker sur le contenu nettoyé — même pipeline que les docs.
    source = conv_gemini_web/<url_id[:16]>/<idx>
    """
    try:
        raw = txt_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        log.warning("Impossible de lire %s: %s", txt_path, e)
        return

    meta = _parse_gemini_web_frontmatter(raw)
    url = meta.get("url", "")
    url_id = url.rstrip("/").split("/")[-1][:16] if url else txt_path.stem.replace(" ", "_")[:16]
    title = meta.get("title", "")[:80]

    # Nettoyer le Markdown
    clean_md = _strip_gemini_web_boilerplate(raw)
    if not clean_md:
        return

    # MarkdownChunker — même pipeline que forge_rag_store pour les docs
    try:
        from nokido_agent.app.forge_rag_store import MarkdownChunker

        raw_chunks = MarkdownChunker.chunk(clean_md, max_chunk_chars=CHUNK_MAX, overlap_chars=150)
    except ImportError:
        # Fallback: chunk naïf par paragraphes
        raw_chunks = [{"text": p, "header_path": ""} for p in clean_md.split("\n\n") if len(p.strip()) >= CHUNK_MIN]

    for idx, c in enumerate(raw_chunks):
        text = c.get("text", "").strip()
        if len(text) < CHUNK_MIN:
            continue
        # Préfixer avec le titre de la session pour le contexte
        header_path = c.get("header_path", "")
        if title and header_path:
            text = f"[{title} | {header_path}]\n{text}"
        elif title:
            text = f"[{title}]\n{text}"
        text = text[:CHUNK_MAX]
        source = f"conv_gemini_web/{url_id}/{idx}"
        yield source, text


def index_gemini_web_sessions(data_dir: Path | None = None) -> dict:
    """Indexe les exports Gemini Web (.txt NousSave) depuis data_dir."""
    if data_dir is None:
        data_dir = GEMINI_WEB_DEFAULT
    if not data_dir.exists():
        return {"ok": False, "error": f"dossier Gemini Web introuvable: {data_dir}"}

    txt_files = sorted(data_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not txt_files:
        return {"ok": False, "error": f"aucun .txt dans {data_dir}"}

    total_chunks: list[tuple[str, str]] = []
    stats: dict[str, int] = {}

    for tf in txt_files:
        chunks = list(iter_gemini_web_chunks(tf))
        total_chunks.extend(chunks)
        stats[tf.name] = len(chunks)

    inserted = _insert_chunks(total_chunks)
    log.info("[conv_indexer] GeminiWeb: %d files, %d chunks, %d inserted", len(txt_files), len(total_chunks), inserted)
    return {"ok": True, "files": len(txt_files), "chunks": len(total_chunks), "inserted": inserted, "per_file": stats}


# ─────────────────────────────────────────────────────────────────────────────
# Extraction Claude Desktop JSON (conversations.json export)
# ─────────────────────────────────────────────────────────────────────────────


def iter_desktop_conv_chunks(conv: dict) -> Iterator[tuple[str, str]]:
    """
    Génère (source, text) depuis une conversation Claude Desktop.
    conv: dict avec uuid, name, chat_messages (sender=human/assistant, text)
    source = conv_claude_desktop/<uuid[:16]>/<idx>
    """
    conv_id = conv.get("uuid", "unknown")[:16]
    messages = conv.get("chat_messages", [])
    turns: list[tuple[str, str]] = []

    for msg in messages:
        sender = msg.get("sender", "")
        if sender not in ("human", "assistant"):
            continue
        text = ""
        # Préférer content[].text (plus complet) sinon text direct
        content = msg.get("content", [])
        if content and isinstance(content, list):
            parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("text")]
            text = " ".join(parts).strip()
        if not text:
            text = str(msg.get("text", "")).strip()
        if len(text) >= CHUNK_MIN:
            turns.append((sender, text))

    idx = 0
    i = 0
    while i < len(turns):
        role, text = turns[i]
        window = text
        if i + 1 < len(turns) and len(text) + len(turns[i + 1][1]) < CHUNK_MAX:
            window = f"[{role}] {text}\n[{turns[i + 1][0]}] {turns[i + 1][1]}"
            i += 2
        else:
            window = f"[{role}] {text}"
            i += 1
        window = window[:CHUNK_MAX]
        source = f"conv_claude_desktop/{conv_id}/{idx}"
        yield source, window
        idx += 1


def index_desktop_sessions(data_dir: Path | None = None) -> dict:
    """
    Indexe les conversations Claude Desktop depuis conversations.json.
    data_dir: dossier contenant conversations.json (défaut: CLAUDE_DESKTOP_DEFAULT)
    """
    if data_dir is None:
        data_dir = CLAUDE_DESKTOP_DEFAULT
    conv_file = data_dir / "conversations.json"
    if not conv_file.exists():
        return {"ok": False, "error": f"conversations.json introuvable: {conv_file}"}

    try:
        convs = json.loads(conv_file.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not isinstance(convs, list):
        return {"ok": False, "error": "Format inattendu: conversations.json n'est pas un array"}

    total_chunks: list[tuple[str, str]] = []
    stats: dict[str, int] = {}
    processed = 0

    for conv in convs:
        msgs = conv.get("chat_messages", [])
        if not msgs:
            continue
        chunks = list(iter_desktop_conv_chunks(conv))
        total_chunks.extend(chunks)
        name = conv.get("name", conv.get("uuid", "?"))[:60]
        stats[name] = len(chunks)
        processed += 1

    inserted = _insert_chunks(total_chunks)
    log.info("[conv_indexer] Desktop: %d convs, %d chunks, %d inserted", processed, len(total_chunks), inserted)
    return {
        "ok": True,
        "conversations": processed,
        "chunks": len(total_chunks),
        "inserted": inserted,
        "per_conv": stats,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Extraction Codex CLI (~/.codex/sessions/AAAA/MM/JJ/rollout-<horodatage>-<uuid>.jsonl)
# ─────────────────────────────────────────────────────────────────────────────

_UUID = _re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", _re.IGNORECASE)
CODEX_ROLES = ("user", "assistant", "system", "human", "bot", "model", "codex")


def _codex_message(msg: dict):
    """(role, contenu, horodatage) d'une ligne de session Codex, ou None si ce n'est pas un tour.

    Forme REELLE, mesuree le 2026-10-13 sur les 26 sessions du poste : chaque tour est ENVELOPPE,
    `{"timestamp", "type": "response_item", "payload": {"type": "message", "role", "content": [{"type":
    "input_text"|"output_text", "text"}]}}`. Les `event_msg` repetent les memes tours (ignores, sinon
    doublons) ; `session_meta` et `turn_context` ne sont pas des tours ; le role `developer` (consignes
    du harnais) non plus. La forme plate (`role`/`content`, ou `message: {...}`) reste lue. Ne lire que
    la forme plate rendait ZERO morceau des vraies sessions."""
    payload = msg.get("payload")
    if isinstance(payload, dict):
        if msg.get("type") != "response_item" or payload.get("type") != "message":
            return None
        return str(payload.get("role") or ""), payload.get("content"), msg.get("timestamp")
    raw = msg.get("message")
    if isinstance(raw, dict):
        return (str(raw.get("role") or msg.get("role") or msg.get("type") or ""),
                raw.get("content") or raw.get("text"), msg.get("timestamp") or raw.get("timestamp"))
    return (str(msg.get("role") or msg.get("type") or msg.get("source") or ""),
            msg.get("content") or msg.get("text") or raw, msg.get("timestamp") or msg.get("created_at"))


def _codex_session_id(jsonl_path: Path) -> str:
    """UUID de la session, lu dans le nom (`rollout-<horodatage>-<uuid>`) ; a defaut le nom entier.
    Jamais `stem[:16]` : il vaut `rollout-2026-09-` pour TOUTES les sessions d'un meme mois."""
    m = _UUID.search(jsonl_path.stem)
    if m:
        return m.group(0).lower()
    if jsonl_path.stem in ("transcript", "session", "log"):
        return jsonl_path.parent.name
    return jsonl_path.stem


def iter_codex_chunks(jsonl_path: Path) -> Iterator[tuple[str, str, int | None]]:
    """
    Génère (source, text, ts_msg) pour chaque tour utilisateur/assistant d'une session Codex CLI.
    Source = conv_codex/<uuid de session>/<idx>
    """
    turns: list[tuple[str, str, int | None]] = []
    try:
        lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        log.warning("Impossible de lire %s: %s", jsonl_path, e)
        return

    for msg in _lignes_json(lines, jsonl_path):
        tour = _codex_message(msg)
        if tour is None:
            continue
        role, content, ts = tour
        if role not in CODEX_ROLES:
            continue
        text = _extract_text(content)
        if len(text) >= CHUNK_MIN:
            turns.append((role, text, _ts_epoch(ts)))

    yield from _fenetres_sans_perte(turns, "conv_codex", _codex_session_id(jsonl_path))


def index_codex_sessions(sessions_dir: Path | None = None, limit_sessions: int = 0) -> dict:
    """Indexe les sessions Codex CLI (~/.codex/sessions/**/*.jsonl). `limit_sessions=0` = TOUTES."""
    if sessions_dir is None:
        sessions_dir = CODEX_HISTORY / "sessions"
    if not sessions_dir.exists():
        return {"ok": False, "error": f"dossier Codex CLI introuvable: {sessions_dir}"}

    tous = sorted(sessions_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    fichiers = tous if limit_sessions <= 0 else tous[:limit_sessions]
    if not fichiers:
        return {"ok": False, "error": f"aucun .jsonl sous {sessions_dir}"}

    total: list[tuple[str, str, int | None]] = []
    stats: dict[str, int] = {}
    for f in fichiers:
        morceaux = list(iter_codex_chunks(f))
        total.extend(morceaux)
        stats[f.name] = len(morceaux)

    inserted = _insert_chunks(total)
    log.info("[conv_indexer] Codex: %d sessions, %d chunks, %d inserted", len(fichiers), len(total), inserted)
    return {
        "ok": True,
        "sessions": len(fichiers),
        "chunks": len(total),
        "inserted": inserted,
        "per_file": stats,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Insertion RAG
# ─────────────────────────────────────────────────────────────────────────────


def _chunk_id(source: str, text: str) -> str:
    return hashlib.sha256(f"{source}{text}".encode()).hexdigest()[:16]


def _caviarde(texte: str) -> str:
    """Neutralise les secrets AVANT insertion en base.

    Ce module ecrivait le texte BRUT en SQLite sans jamais appeler le moindre garde.
    Audit du 2026-08-12 sur 53 947 chunks : 86 portaient des motifs a haute
    confiance — 61 Bearer, 10 FORGE_MCP_TOKEN, 9 cles Google, 3 Groq, 3 GitHub.
    Une conversation d'agent colle des jetons ; les indexer les rend cherchables.

    Le motif `Hex-64` est VOLONTAIREMENT exclu : `[A-Za-z0-9]{64}` matche tout SHA
    git, toute cle de cache, tout hash de chunk (311 declenchements, quasi tous du
    bruit). Le caviarder detruirait des references legitimes — un filtre qui abime
    la donnee saine finit desactive, donc ne protege plus rien.

    Echec d'import du garde -> on NE bloque pas l'indexation, mais on le journalise :
    un filtre absent doit se voir, pas se deviner.
    """
    try:
        from nokido_agent.app.forge_secret_guard import _OUTBOUND_PATTERNS
    except Exception as e:  # noqa: BLE001
        if not getattr(_caviarde, "_prevenu", False):
            _caviarde._prevenu = True
            log.error("[conv_indexer] DLP INDISPONIBLE (%s) — indexation en texte BRUT",
                      type(e).__name__)
        return texte
    for motif, label in _OUTBOUND_PATTERNS:
        if label.startswith("Hex-64"):
            continue
        texte = motif.sub(f"[REDACTED:{label}]", texte)
    return texte


def _insert_chunks(chunks: list[tuple[str, str]], db_path: Path | None = None) -> int:
    """INSERT OR IGNORE dans rag_chunks + rag_fts. Retourne nb insérés."""
    if db_path is None:
        db_path = RAG_DB
    if not db_path.exists():
        log.warning("RAG DB introuvable: %s", db_path)
        return 0

    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode=WAL")
    inserted = 0
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    try:
        for item in chunks:
            # 2-uple (source, text) ou 3-uple (source, text, ts_message). Les
            # iterateurs qui ne savent pas encore dater restent compatibles :
            # created_at vaut alors NULL, comme avant, plutot qu'une date fausse.
            source, text, *_extra = item
            ts_msg = _extra[0] if _extra else None
            text = _caviarde(text)
            cid = _chunk_id(source, text)
            try:
                # Forme sans existant (2026-10-01) : un id deja present n'arme plus le
                # trigger rag_chunks_fts_bi, qui le sortait du lexical ; changes() vaut 0.
                con.execute(
                    "INSERT OR IGNORE INTO rag_chunks "
                    "(id, source, text, domain, ingested_at, created_at) SELECT ?,?,?,?,?,? "
                    "WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)",
                    (cid, source, text, "conv", ts, ts_msg, cid),
                )
                # Le compteur d'inserees se lit ICI, avant toute autre ecriture :
                # `changes()` rend le nombre de lignes de la DERNIERE requete, donc
                # un UPDATE intercale le fausserait.
                _neuf = con.execute("SELECT changes()").fetchone()[0]
                # RATTRAPAGE. `INSERT OR IGNORE` laisse intactes les lignes deja
                # presentes : sans ceci, les 37 715 chunks ingeres AVANT que
                # l'indexeur sache dater resteraient sans date pour toujours et la
                # chronologie ne commencerait qu'aujourd'hui. On ne remplit que le
                # VIDE (`created_at IS NULL`) : une date deja posee n'est jamais
                # ecrasee.
                if ts_msg and not _neuf:
                    con.execute(
                        "UPDATE rag_chunks SET created_at=? "
                        "WHERE id=? AND created_at IS NULL",
                        (ts_msg, cid),
                    )
                if _neuf:
                    # Sync FTS
                    try:
                        con.execute(
                            # `chunk_id` MANQUAIT : la ligne partait avec une cle NULL,
                            # donc impossible a joindre a rag_chunks et invisible a toute
                            # purge ciblee. 54 264 lignes ainsi orphelines au 2026-08-23.
                            "INSERT OR IGNORE INTO rag_fts (rowid, chunk_id, source, text) "
                            "VALUES ((SELECT rowid FROM rag_chunks WHERE id=?), ?, ?, ?)",
                            (cid, cid, source, text),
                        )
                    except Exception as e_fts:
                        # Le morceau est en base mais INVISIBLE a la recherche lexicale : le dire.
                        log.warning("[conv_indexer] %s absent de rag_fts : %s", cid, e_fts)
                    inserted += 1
            except Exception as e:
                log.debug("Insert skip %s: %s", cid, e)

        con.commit()
    finally:
        con.close()

    return inserted


# ─────────────────────────────────────────────────────────────────────────────
# Entry points publics
# ─────────────────────────────────────────────────────────────────────────────


def index_claude_sessions(project_dir: Path | None = None, limit_sessions: int = 0) -> dict:
    """
    Indexe les sessions Claude CLI d'un projet. `limit_sessions=0` = TOUTES.

    ⚠️ Le defaut etait 20 PAR PROJET, plus recentes d'abord. Mesure du 2026-08-12 :
    57 transcripts sur disque, **22 sessions seulement** dans `conv_claude`
    (20 du projet courant + 2 de l'ancien `...-IA-LaForge`) -> 61 % de l'historique
    JAMAIS indexe. Le plafond etait journalise (« PLAFONNE — couverture partielle »)
    mais personne ne le levait : un avertissement que rien ne lit ne protege de rien.
    Le defaut est desormais ILLIMITE ; qui veut un echantillon le demande.
    """
    # Le projet s'appelait LAFORGE avant Nokido, et ces dossiers sont nommes d'apres
    # le CWD : `C--Users-user-Script-python-IA` et `...-IA-LaForge`. Le glob
    # "*Nokido*" ne matchait donc RIEN, et le repli prenait `candidates[0]`, soit UN
    # seul projet choisi par l'ordre du systeme de fichiers — l'autre, avec ses
    # sessions d'AVRIL, n'etait jamais indexe (mesure 2026-07-30). Un filtre par NOM
    # ne peut pas connaitre les noms a venir ni ceux du passe : on prend TOUS les
    # projets, et le decompte par projet rend la couverture verifiable.
    if project_dir is None:
        dossiers = (
            sorted(d for d in CLAUDE_HISTORY.iterdir() if d.is_dir())
            if CLAUDE_HISTORY.exists()
            else []
        )
    else:
        dossiers = [project_dir] if project_dir.exists() else []

    if not dossiers:
        return {"ok": False, "error": f"aucun projet Claude CLI sous {CLAUDE_HISTORY}"}
    project_dir = dossiers[0]

    jsonl_files: list[Path] = []
    par_projet: dict[str, int] = {}
    for _d in dossiers:
        # rglob, pas glob : les transcripts de SOUS-AGENTS vivent dans
        # <session>/subagents/agent-*.jsonl et etaient donc invisibles (6 fichiers
        # rates au 2026-08-12). Un sous-agent porte du raisonnement, pas du bruit.
        _lot = sorted(_d.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        _garde = _lot if limit_sessions <= 0 else _lot[:limit_sessions]
        par_projet[_d.name] = len(_garde)
        if limit_sessions > 0 and len(_lot) > limit_sessions:
            log.warning(
                "[conv_indexer] %s : %d sessions, PLAFONNE a %d — couverture partielle",
                _d.name, len(_lot), limit_sessions,
            )
        jsonl_files.extend(_garde)
    log.info("[conv_indexer] projets indexes: %s", par_projet)
    # DIGESTION (14/10) : chaine epuree, insertion SESSION PAR SESSION (memoire bornee a une session) ; l'ancien
    # schema d'une session n'est gele que si son remplacant epure existe (une session vide ne gele rien).
    stats, motifs = {}, {}
    total, inserted, geles = 0, 0, 0
    for jf in jsonl_files:
        chunks = list(iter_claude_epure(jf, motifs))
        stats[jf.name] = len(chunks)
        total += len(chunks)
        if chunks:
            inserted += _insert_chunks(chunks)
            geles += geler_ancien(jf.stem)
    log.info("[conv_indexer] Claude: %d sessions, %d fragments epures, %d inseres, %d anciens geles, ecarts %s",
             len(jsonl_files), total, inserted, geles, motifs)
    return {
        "ok": True,
        "sessions": len(jsonl_files),
        "chunks": total,
        "inserted": inserted,
        "anciens_geles": geles,
        "motifs_ecartes": motifs,
        "per_file": stats,
    }


def index_gemini_sessions(project_name: str | Path | None = "laforge", limit_sessions: int = 0) -> dict:
    """Indexe les sessions Gemini CLI (.json et .jsonl). `project_name=None` = TOUS les projets
    (`index_all` : mesure 2026-10-13, 44 sessions .jsonl reparties sur 7 projets dont `laforge` n'en
    porte qu'une). Un nom de projet absent retombe sur tous les projets. `limit_sessions=0` = TOUTES."""
    if isinstance(project_name, Path):
        chats_dirs = [project_name] if project_name.exists() else []
    elif project_name and (GEMINI_HISTORY / project_name / "chats").exists():
        chats_dirs = [GEMINI_HISTORY / project_name / "chats"]
    elif GEMINI_HISTORY.exists():
        chats_dirs = sorted(p for p in GEMINI_HISTORY.glob("*/chats") if p.is_dir())
    else:
        chats_dirs = []
    if not chats_dirs:
        return {"ok": False, "error": f"dossier Gemini CLI introuvable: {GEMINI_HISTORY} (projet {project_name})"}

    fichiers_candidats: list[Path] = []
    for cd in chats_dirs:
        fichiers_candidats.extend(list(cd.glob("session-*.json")) + list(cd.glob("session-*.jsonl")))
    fichiers_candidats.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    json_files = fichiers_candidats if limit_sessions <= 0 else fichiers_candidats[:limit_sessions]
    total_chunks = []
    stats = {}

    for jf in json_files:
        chunks = list(iter_gemini_chunks(jf))
        total_chunks.extend(chunks)
        stats[jf.name] = len(chunks)

    inserted = _insert_chunks(total_chunks)
    log.info("[conv_indexer] Gemini: %d sessions (%d json/jsonl, %d projets), %d chunks, %d inserted",
             len(json_files), len(fichiers_candidats), len(chats_dirs), len(total_chunks), inserted)
    return {
        "ok": True,
        "sessions": len(json_files),
        "chunks": len(total_chunks),
        "inserted": inserted,
        "per_file": stats,
    }


def index_all(limit_sessions: int = 0) -> dict:
    """Indexe Claude CLI + Gemini CLI (tous projets) + AGY + Claude Desktop + Gemini Web + Codex CLI."""
    r_claude = index_claude_sessions(limit_sessions=limit_sessions)
    r_gemini = index_gemini_sessions(project_name=None, limit_sessions=limit_sessions)
    r_agy = index_agy_sessions(limit_sessions=limit_sessions)
    r_desktop = index_desktop_sessions()
    r_gemini_web = index_gemini_web_sessions()
    r_codex = index_codex_sessions(limit_sessions=limit_sessions)
    return {
        "claude": r_claude,
        "gemini": r_gemini,
        "agy": r_agy,
        "desktop": r_desktop,
        "gemini_web": r_gemini_web,
        "codex": r_codex,
        "total_inserted": (
            r_claude.get("inserted", 0)
            + r_gemini.get("inserted", 0)
            + r_agy.get("inserted", 0)
            + r_desktop.get("inserted", 0)
            + r_gemini_web.get("inserted", 0)
            + r_codex.get("inserted", 0)
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Hook post-session: appeler en fin de session pour indexer immédiatement
# ─────────────────────────────────────────────────────────────────────────────


def index_latest_session(agent: str = "claude") -> dict:
    """
    Indexe uniquement la session la plus récente du CLI donné.
    Conçu pour être appelé en hook de fin de session.
    """
    if agent.lower() == "gemini":
        return index_gemini_sessions(limit_sessions=1)
    else:
        return index_claude_sessions(limit_sessions=1)


def _etat_racine(racine: Path) -> str:
    """OK / ABSENT / ILLISIBLE. Un dossier qu'on ne peut pas LISTER n'est pas un dossier vide : `glob`
    y rend [] sans erreur. Mesure 2026-10-13 sous LaForgeTrusted : Gemini et Codex sortaient `n: 0`
    alors que 44 + 26 sessions existent (ACL du profil owner) -- UNKNOWN pris pour NO."""
    try:
        with os.scandir(racine):
            return "OK"
    except FileNotFoundError:
        return "ABSENT"
    except OSError:
        return "ILLISIBLE"


def couverture() -> dict:
    """Depuis QUAND chaque source est-elle couverte ?

    Question posee par l'owner le 2026-08-12 (« refais une passe depuis mars 2026 »)
    et jusque-la SANS REPONSE : la date d'une session n'est stockee nulle part — ni
    dans `rag_chunks` (qui porte `ingested_at`, la date d'INDEXATION, pas celle de la
    conversation), ni dans la source du chunk. On mesure donc la fenetre a partir des
    dates de modification des fichiers, seule horloge disponible.

    ⚠️ `mtime` n'est PAS la date de la conversation : une session rejouee ou recopiee
    porte une date recente. C'est une borne, pas une verite — et il faut le dire
    plutot que d'afficher une fenetre rassurante.
    """
    import datetime as _dt

    def _fenetre(fichiers: list) -> dict:
        ts = []
        illisibles = 0
        for f in fichiers:
            try:
                ts.append(f.stat().st_mtime)
            except OSError:
                illisibles += 1  # compte, pas avale : `n` ne doit pas sous-compter en silence
        if not ts:
            return {"n": 0, "illisibles": illisibles} if illisibles else {"n": 0}
        return {"n": len(ts), **({"illisibles": illisibles} if illisibles else {}),
                "plus_ancien": _dt.datetime.fromtimestamp(min(ts)).strftime("%Y-%m-%d"),
                "plus_recent": _dt.datetime.fromtimestamp(max(ts)).strftime("%Y-%m-%d")}

    def _source(racine: Path, motif: str) -> dict:
        etat = _etat_racine(racine)
        if etat == "ILLISIBLE":
            return {"n": None, "etat": "ILLISIBLE", "racine": str(racine)}
        if etat == "ABSENT":
            return {"n": 0, "etat": "ABSENT"}
        return _fenetre(list(racine.glob(motif)))

    out: dict = {}
    etat_claude = _etat_racine(CLAUDE_HISTORY)
    if etat_claude == "OK":
        for d in sorted(p for p in CLAUDE_HISTORY.iterdir() if p.is_dir()):
            out[f"claude:{d.name}"] = _fenetre(list(d.rglob("*.jsonl")))
    else:
        out["claude"] = {"n": None if etat_claude == "ILLISIBLE" else 0, "etat": etat_claude}
    out["agy"] = _source(AGY_HISTORY, "*/.system_generated/logs/transcript.jsonl")
    out["gemini_cli"] = _source(GEMINI_HISTORY, "*/chats/session-*.json")
    out["gemini_cli_jsonl"] = _source(GEMINI_HISTORY, "*/chats/session-*.jsonl")
    out["codex_cli"] = _source(CODEX_HISTORY, "sessions/**/*.jsonl")
    out["_note"] = ("mtime = derniere modification du fichier, PAS la date de la "
                    "conversation ; borne inferieure de couverture uniquement. n=None + "
                    "ILLISIBLE = racine non listable par CE compte, pas une source vide ; un "
                    "sous-dossier illisible sous une racine lisible reste invisible a glob")
    return out


def installer_tache_nocturne(heure: str = "03:00") -> dict:
    """Pose la tâche `Nokido-ConvIndex` SOUS LE COMPTE QUI EXÉCUTE ce script.

    ⚠️ Le compte compte. Posée le 2026-08-12 depuis `run action=shell`, la tâche a
    hérité de `LaForgeSbxOffline` en `LogonType=Interactive` : ce compte n'ouvre
    jamais de session, donc la tâche n'a JAMAIS pu démarrer
    (`LastTaskResult 267011` = SCHED_S_TASK_HAS_NOT_RUN) — et il n'a de toute façon
    pas l'ACL sur les historiques de l'owner, que seul `LaForgeTrusted` détient.

    Lancer ce mode via `run action=trusted_script` : la tâche est alors posée pour
    `LaForgeTrusted`, avec `LogonType=S4U` — exécution sans session ouverte et sans
    mot de passe stocké. Une tâche qui ne peut pas se déclencher est pire qu'absente :
    elle occupe la place de celle qui marcherait.
    """
    import getpass
    import subprocess as _sp

    compte = getpass.getuser()
    ps = (
        "$ErrorActionPreference='Stop';"
        f"$a=New-ScheduledTaskAction -Execute '{sys.executable}' "
        f"-Argument '\"{Path(__file__).resolve()}\"';"
        f"$t=New-ScheduledTaskTrigger -Daily -At {heure};"
        f"$p=New-ScheduledTaskPrincipal -UserId '{compte}' -LogonType S4U -RunLevel Limited;"
        "Register-ScheduledTask -TaskName 'Nokido-ConvIndex' -Action $a -Trigger $t "
        "-Principal $p -Description 'Consolidation nocturne des historiques agents' -Force "
        "| Out-Null; 'OK'"
    )
    r = _sp.run(["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, errors="replace", timeout=120)
    ok = r.returncode == 0
    log.info("[conv_indexer] tache nocturne (%s, S4U) : %s", compte, "OK" if ok else "ECHEC")
    return {"ok": ok, "compte": compte, "heure": heure,
            "sortie": ((r.stdout or "") + (r.stderr or "")).strip()[:400]}


# ── DIGESTION INCREMENTALE ET AUTOREGULEE (owner 14/10 : « 03:00 n'est que tres rarement atteint, un cycle plus
# court, toujours autoregule sans saturer le poste ») : une passe toutes les 15 min ne coute que le DELTA. ─────
ETAT_INCREMENTAL = ROOT / "logs" / "conv_indexer_etat.json"
INACTIF_S = 1800              # fichier immobile depuis 30 min : session close, le dernier tour est solde
BUDGET_OCTETS = 64 << 20      # au plus 64 Mo lus par fichier et par passe (le reste attend, et le DIT)


def doit_differer(jobs_dir: Path | None = None, mesure=None, seuil_ram: float = 85.0,
                  seuil_disque_mbs: float = 40.0) -> tuple[bool, str]:
    """(differer, raison). Differer coute 15 min, jamais une donnee. Ordre : CI/job lourd VIVANT (pid verifie,
    jamais un statut declare), bail prioritaire ACTIF, pression RAM/disque mesuree. Une sonde ILLISIBLE est DITE
    et ne bloque pas seule (ni feu vert silencieux, ni blocage perpetuel)."""
    illisibles = []
    try:
        import psutil
        for j in (jobs_dir or ROOT / "sandbox" / "jobs").glob("job_*.json"):
            if j.with_suffix(".rc").exists():
                continue
            try:
                meta = json.loads(j.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                illisibles.append("%s ILLISIBLE (%s)" % (j.name, type(e).__name__))
                continue
            lourd = any(m in str(meta.get("script", "")) for m in ("ci_local.py", "forge_reindex", "run_swarm"))
            if lourd and meta.get("pid") and psutil.pid_exists(int(meta["pid"])):
                return True, "job lourd vivant %s (%s)" % (meta.get("job_id"), Path(str(meta.get("script"))).name)
    except Exception as e:  # noqa: BLE001 - dit dans la raison rendue
        illisibles.append("jobs ILLISIBLES (%s)" % type(e).__name__)
    try:
        from nokido_agent.app import forge_resource_manager as _rm
        actifs = [b for b in _rm._lire_baux() if b.get("etat") == "ACTIF"]
        if actifs:
            return True, "bail prioritaire actif (%s)" % actifs[0].get("motif", "?")
    except Exception as e:  # noqa: BLE001 - dit dans la raison rendue
        illisibles.append("baux ILLISIBLES (%s)" % type(e).__name__)
    try:
        ram, disque = (mesure or _mesure_pression)()
        if ram >= seuil_ram:
            return True, "RAM %.0f %% >= %.0f %%" % (ram, seuil_ram)
        if disque >= seuil_disque_mbs:
            return True, "disque %.0f Mo/s >= %.0f Mo/s" % (disque, seuil_disque_mbs)
    except Exception as e:  # noqa: BLE001 - dit dans la raison rendue
        illisibles.append("pression ILLISIBLE (%s)" % type(e).__name__)
    return False, "aucun motif" + (" ; " + " ; ".join(illisibles) if illisibles else "")


def _mesure_pression(fenetre_s: float = 2.0) -> tuple[float, float]:
    import psutil
    a = psutil.disk_io_counters()
    time.sleep(fenetre_s)
    b = psutil.disk_io_counters()
    mbs = ((b.read_bytes - a.read_bytes) + (b.write_bytes - a.write_bytes)) / fenetre_s / 1e6
    return psutil.virtual_memory().percent, mbs


def _lignes_depuis(chemin: Path, position: int, budget: int = BUDGET_OCTETS) -> tuple[list, int, bool]:
    """([(position_debut, objet)], position_fin, tronque_par_budget) -- seules les lignes COMPLETES comptent."""
    with open(chemin, "rb") as fh:
        fh.seek(position)
        brut = fh.read(budget + 1)
    tronque = len(brut) > budget
    brut = brut[:budget]
    fin = brut.rfind(b"\n")
    if fin < 0:
        return [], position, tronque
    sortie, curseur = [], position
    for ligne in brut[:fin + 1].split(b"\n")[:-1]:
        debut = curseur
        curseur += len(ligne) + 1
        try:
            o = json.loads(ligne.decode("utf-8", "replace"))
        except ValueError:  # muet-ok : ligne illisible ecartee, comptee dans les motifs par l'appelant
            continue
        if isinstance(o, dict):
            sortie.append((debut, o))
    return sortie, curseur, tronque


def passe_claude(jf: Path, etat: dict | None, motifs: dict, maintenant: float | None = None) -> tuple[list, dict]:
    """(fragments a inserer, nouvel etat du fichier). Seuls les tours FERMES (suivis d'une parole humaine) entrent ;
    le tour ouvert est retenu (position = son debut), ou solde quand le fichier est immobile depuis INACTIF_S."""
    st = jf.stat()
    e = dict(etat or {})
    if e.get("taille") == st.st_size and e.get("mtime") == int(st.st_mtime) and not e.get("ouvert"):
        return [], e
    lus, fin, tronque = _lignes_depuis(jf, int(e.get("position", 0)))
    inactif = ((maintenant or time.time()) - st.st_mtime) >= INACTIF_S
    humains = [i for i, (_p, o) in enumerate(lus)
               if o.get("type") == "user" and isinstance((o.get("message") or {}).get("content"), str)]
    if inactif or not humains or tronque:
        fermes, reprise, ouvert = lus, fin, False
    else:
        fermes, reprise, ouvert = lus[:humains[-1]], lus[humains[-1]][0], True
    tours, compte = tours_epures([o for _p, o in fermes])
    gardes, narrations = moelle(tours)
    compte["narration_intermediaire"] = narrations
    for k, v in compte.items():
        motifs[k] = motifs.get(k, 0) + v
    e.update(position=reprise, taille=st.st_size, mtime=int(st.st_mtime), ouvert=ouvert, tronque=tronque)
    return list(_fragments_claude(jf.stem, gardes)), e


DERNIER_PASSAGE = ROOT / "logs" / "conv_indexer_dernier.json"


def ecrire_dernier_passage(resultat: dict, chemin: Path | None = None) -> bool:
    """Ecrit le dernier passage d'`index_all` (fin, compte, resultat). La tache nocturne tourne sous
    pythonw, sans console : desactivee le 25/08, elle a fige le corpus conv 7 semaines sans que RIEN
    ne le dise. Ce fichier est la preuve datee qu'un passage a eu lieu -- son absence aussi parle."""
    import getpass

    chemin = chemin or DERNIER_PASSAGE
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps({"fin": time.strftime("%Y-%m-%dT%H:%M:%S"), "compte": getpass.getuser(),
                                      "resultat": resultat}, ensure_ascii=False, indent=1, default=str),
                          encoding="utf-8")
        return True
    except OSError as e:
        log.warning("[conv_indexer] dernier passage NON ecrit (%s) : %s", chemin, e)
        return False


def index_incremental(etat_path: Path | None = None, racine: Path | None = None) -> dict:
    """Une passe COURTE : la porte d'abord ; puis le DELTA des sessions Claude (positions par fichier) ; les sources
    peu actives (Gemini, AGY, Codex) en passe complete une fois par jour. Enumeration LEGERE (`*/*.jsonl` et
    `*/*/subagents/*.jsonl`) : le rglob des dossiers de resultats d'outils a coute 68 s le 14/10."""
    differer, raison = doit_differer()
    if differer:
        log.info("[conv_indexer] passe DIFFEREE : %s", raison)
        return {"ok": True, "verdict": "DIFFERE", "raison": raison}
    etat_path = etat_path or ETAT_INCREMENTAL
    racine = racine or CLAUDE_HISTORY
    try:
        etat = json.loads(etat_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        etat = {}
    except (OSError, ValueError) as e:
        log.warning("[conv_indexer] etat incremental ILLISIBLE (%s) : positions repartent de zero (dedup)",
                    type(e).__name__)
        etat = {}
    fichiers = (sorted(list(racine.glob("*/*.jsonl")) + list(racine.glob("*/*/subagents/*.jsonl")))
                if racine.exists() else [])
    motifs, inseres, geles, avec_nouveau = {}, 0, 0, 0
    for jf in fichiers:
        cle = str(jf)
        try:
            frags, nouvel = passe_claude(jf, etat.get(cle), motifs)
        except OSError as e:
            log.warning("[conv_indexer] %s illisible (%s) : non digere cette passe", jf.name, type(e).__name__)
            continue
        if frags:
            avec_nouveau += 1
            inseres += _insert_chunks(frags)
            if not (etat.get(cle) or {}).get("ancien_gele"):
                geles += geler_ancien(jf.stem)
                nouvel["ancien_gele"] = True
        etat[cle] = nouvel
    autres = None
    if time.time() - float(etat.get("_derniere_complete", 0)) > 86400:
        autres = {"gemini": index_gemini_sessions(project_name=None), "agy": index_agy_sessions(),
                  "codex": index_codex_sessions()}
        etat["_derniere_complete"] = time.time()
    tmp = etat_path.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(etat, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, etat_path)
    res = {"ok": True, "verdict": "PASSE", "porte": raison, "fichiers": len(fichiers),
           "fichiers_avec_nouveau": avec_nouveau, "inserted": inseres, "anciens_geles": geles,
           "motifs_ecartes": motifs, "autres_sources": autres}
    log.info("[conv_indexer] incremental : %s", {k: v for k, v in res.items() if k != "autres_sources"})
    return res


if __name__ == "__main__":
    # Sous pythonw (tache nocturne) stderr vaut None : sans fichier, le passage ne laisse aucune trace.
    _handlers: list = [logging.StreamHandler()] if sys.stderr is not None else []
    if "--coverage" not in sys.argv and "--install-nightly" not in sys.argv:
        try:
            _handlers.append(logging.FileHandler(ROOT / "logs" / "conv_indexer.log", encoding="utf-8"))
        except OSError as _e:
            if sys.stderr is not None:
                print(f"[conv_indexer] journal fichier impossible : {_e}", file=sys.stderr)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=_handlers)
    if "--install-nightly" in sys.argv:
        print(json.dumps(installer_tache_nocturne(), indent=2, ensure_ascii=False))
        raise SystemExit(0)
    if "--coverage" in sys.argv:
        print(json.dumps(couverture(), indent=2, ensure_ascii=False))
        raise SystemExit(0)
    result = index_incremental() if "--incremental" in sys.argv else index_all()
    ecrire_dernier_passage(result)
    print(f"[conv_indexer] Résultat: {json.dumps(result, indent=2, ensure_ascii=False)}")
