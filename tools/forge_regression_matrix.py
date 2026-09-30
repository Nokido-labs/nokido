#!/usr/bin/env python3
"""
forge_regression_matrix.py — Transforme l'historique reel en matrice anti-regression.

PROBLEME TRAITE
===============
« Nokido oublie ses capacites » : une capacite livree cesse d'exister et RIEN ne crie.
Constate 3 fois le 2026-08-12 (montage V: disparu, sonde qui ment, 10 hooks morts).
Aucun juge LLM n'aurait vu ces trois-la : ce n'est pas de la derive de SORTIE, c'est de
la derive de CAPACITE. Cet outil couvre la seconde, en deterministe et sans quota.

SOURCE — mesuree, pas supposee (2026-08-12)
===========================================
`RAG/embeddings.db::network_log` (217 163 lignes) : ts, direction, method, tool, agent,
ring, latency_ms, status, payload_in, payload_out, headers, client_ip, channel, provider,
model, meta, session_id. C'est le seul journal qui porte les appels d'outils AVEC leurs
payloads, et `session_id` y donne le groupement en trajectoires.

`RAG/execution_traces.db::traces` a ete ECARTE apres mesure : 30 842 lignes mais seulement
2 `trace_id` distincts, `task_type` toujours 'tool_call', et `args` / `result_preview`
VIDES. Journal degenere, zero valeur de rejeu. Ne pas y revenir sans avoir reverifie.

SECURITE — pourquoi seulement les CLES
======================================
La matrice enregistre les CLES d'arguments et un hash de signature, JAMAIS les valeurs.
Le 2026-08-11, une sonde d'inventaire a fuite des jetons de service dans un rapport.
Ne pas stocker la valeur supprime la classe de fuite, au lieu d'esperer la filtrer.

REGLE DE SONDE (leçon du 2026-08-12)
====================================
Une sonde qui ne peut pas observer rend INDETERMINE — jamais OK, jamais PERDU.
Un rc!=0 prouve le REFUS, pas l'absence. `--check` sort 2 dans ce cas, pas 1.

USAGE
=====
    LAFORGE_PYTHON tools/forge_regression_matrix.py --stats
    LAFORGE_PYTHON tools/forge_regression_matrix.py --extract [--days 90] [--min-calls 2]
    LAFORGE_PYTHON tools/forge_regression_matrix.py --check      # 0 OK / 1 perdu / 2 indetermine

Sortie : sandbox/regression_matrix.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
NETLOG_DB = ROOT / "RAG" / "embeddings.db"
MATRIX = ROOT / "sandbox" / "regression_matrix.json"

OK_STATUS = {"ok", "OK", "200", "success", "SUCCESS", "completed"}
# Un outil qui a REUSSI il y a moins de N heures ne peut pas etre "perdu" : si
# l'inventaire le dit absent, c'est l'inventaire qui est faux (cf cmd_check).
RECENT_OK_HOURS = int(os.environ.get("LAFORGE_REGMATRIX_RECENT_H", "48"))


def _log(m: str) -> None:
    print(f"[regmatrix] {m}", flush=True)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{NETLOG_DB}?mode=ro", uri=True, timeout=20)
    c.row_factory = sqlite3.Row
    return c


def _scan_keys_truncated(s: str) -> list[str]:
    """Cles de profondeur 1 d'un JSON TRONQUE, sans le decoder.

    Une chaine suivie de ':' au niveau 1 est une cle ; les objets imbriques montent
    la profondeur et sont donc ignores. Aucune VALEUR n'est retenue.
    """
    keys: set[str] = set()
    depth, i, n = 0, 0, len(s)
    while i < n:
        ch = s[i]
        if ch == '"':
            j = i + 1
            while j < n:
                if s[j] == "\\":
                    j += 2
                    continue
                if s[j] == '"':
                    break
                j += 1
            if j >= n:
                break  # chaine coupee par la troncature : on s'arrete la
            token = s[i + 1:j]
            k = j + 1
            while k < n and s[k] in " \t\r\n":
                k += 1
            if depth == 1 and k < n and s[k] == ":":
                keys.add(token[:40])
            i = j + 1
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        i += 1
    return sorted(keys)


def _arg_keys(payload_in: str | None) -> list[str]:
    """Cles d'arguments d'un appel. JAMAIS les valeurs (cf section SECURITE).

    `payload_in` est TRONQUE dans network_log (mesure 2026-08-12 : json.loads leve
    `Unterminated string starting at ...` sur les gros appels). Un parseur strict
    rendait alors [] et faisait croire a des appels SANS arguments -- governed_edit
    et poll ressortaient a tort avec `keys=-`. On retombe sur un balayage lexical
    qui survit a la troncature.
    """
    if not payload_in:
        return []
    try:
        d = json.loads(payload_in)
    except ValueError:
        return _scan_keys_truncated(payload_in)
    # Forme MCP : {"params": {"name":..., "arguments": {...}}} ; sinon dict a plat.
    for path in (("params", "arguments"), ("arguments",), ()):
        node = d
        for k in path:
            node = node.get(k) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict) and node:
            return sorted(str(k)[:40] for k in node)
    return []


def _forme_sortie(payload_out) -> str:
    """Signature de FORME d'une reponse — jamais son contenu.

    Comble le seul angle mort que les autres axes ne voient pas : un outil qui
    existe toujours et repond DIFFEREMMENT. Les 11 axes de la passe verifient
    l'existence ; aucun ne verifie le comportement.

    On ne compare pas les valeurs (elles changent legitimement a chaque appel),
    on compare la STRUCTURE : les cles de premier niveau pour un objet, une classe
    de longueur pour du texte. Un `run` qui rendait {ok,stdout,exit_code} et rend
    soudain {error,reason} a change de contrat, meme si les deux sont valides.
    """
    if not payload_out:
        return "vide"
    s = str(payload_out).strip()
    if not s:
        return "vide"
    if s[0] in "{[":
        cles = _scan_keys_truncated(s)
        return ("obj:" + ",".join(cles[:8])) if cles else "obj:?"
    n = len(s)
    return "texte:" + ("court" if n < 80 else "moyen" if n < 400 else "long")


def _hours_since(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(str(ts)[:26])).total_seconds() / 3600.0
    except ValueError:
        return None


def _sig(tool: str, keys: list[str]) -> str:
    return hashlib.sha256(f"{tool}|{','.join(keys)}".encode()).hexdigest()[:10]


# ── stats : regarder AVANT de supposer ──────────────────────────────────────

def cmd_stats() -> int:
    if not NETLOG_DB.exists():
        _log(f"INDETERMINE : base absente ({NETLOG_DB}) -- V: monte ?")
        return 2
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM network_log").fetchone()[0]
        _log(f"network_log : {total} lignes")
        for label, sql in (
            ("status", "SELECT status, COUNT(*) n FROM network_log GROUP BY status ORDER BY n DESC LIMIT 8"),
            ("tool", "SELECT tool, COUNT(*) n FROM network_log WHERE tool IS NOT NULL GROUP BY tool ORDER BY n DESC LIMIT 12"),
            ("agent", "SELECT agent, COUNT(*) n FROM network_log GROUP BY agent ORDER BY n DESC LIMIT 8"),
        ):
            rows = c.execute(sql).fetchall()
            _log(f"-- {label} : " + " | ".join(f"{r[0]}={r[1]}" for r in rows))
        span = c.execute("SELECT MIN(ts), MAX(ts) FROM network_log").fetchone()
        _log(f"-- fenetre : {span[0]} -> {span[1]}")
    return 0


# ── extract : historique reussi -> matrice ──────────────────────────────────

def cmd_extract(days: int, min_calls: int) -> int:
    if not NETLOG_DB.exists():
        _log(f"INDETERMINE : base absente ({NETLOG_DB})")
        return 2
    ok_list = ",".join("?" for _ in OK_STATUS)
    sql = (
        f"SELECT tool, agent, ring, status, payload_in, latency_ms, session_id, ts, channel, payload_out "
        f"FROM network_log WHERE tool IS NOT NULL AND tool <> '' "
        f"AND status IN ({ok_list}) AND ts >= date('now', ?) ORDER BY ts"
    )
    caps: dict[tuple[str, str], dict] = {}
    sessions: dict[str, list[str]] = defaultdict(list)
    n = 0
    with _conn() as c:
        for r in c.execute(sql, (*sorted(OK_STATUS), f"-{days} days")):
            n += 1
            tool = str(r["tool"])[:80]
            keys = _arg_keys(r["payload_in"])
            sig = _sig(tool, keys)
            e = caps.setdefault(
                (tool, sig),
                {"tool": tool, "signature": sig, "arg_keys": keys, "calls": 0,
                 "first_ts": r["ts"], "last_ts": r["ts"], "agents": set(),
                 "rings": set(), "channels": set(), "lat_ms": [], "formes": {}},
            )
            e["calls"] += 1
            e["last_ts"] = r["ts"]
            if r["agent"]:
                e["agents"].add(str(r["agent"])[:40])
            if r["channel"]:
                e["channels"].add(str(r["channel"])[:40])
            f = _forme_sortie(r["payload_out"])
            fe = e["formes"].setdefault(f, {"n": 0, "first": r["ts"], "last": r["ts"]})
            fe["n"] += 1
            fe["last"] = r["ts"]
            if r["ring"] is not None:
                e["rings"].add(int(r["ring"]))
            if r["latency_ms"] is not None:
                e["lat_ms"].append(float(r["latency_ms"]))
            if r["session_id"]:
                seq = sessions[str(r["session_id"])]
                if not seq or seq[-1] != tool:
                    seq.append(tool)

    kept = [e for e in caps.values() if e["calls"] >= min_calls]
    for e in kept:
        lat = sorted(e.pop("lat_ms"))
        e["latency_p50_ms"] = round(lat[len(lat) // 2], 1) if lat else None
        e["agents"] = sorted(e["agents"])
        e["rings"] = sorted(e["rings"])
        e["channels"] = sorted(e["channels"])
        formes = e.pop("formes")
        if formes:
            dom = max(formes.items(), key=lambda kv: kv[1]["n"])[0]
            rec = max(formes.items(), key=lambda kv: str(kv[1]["last"]))[0]
            e["formes_n"] = len(formes)
            e["forme_dominante"] = dom[:90]
            e["forme_recente"] = rec[:90]
            # Derive = la forme la PLUS RECENTE n'est plus la forme DOMINANTE.
            # Ce n'est pas une preuve de panne : un outil peut legitimement enrichir
            # sa reponse. C'est un signal a arbitrer, jamais un verdict.
            e["derive_forme"] = dom != rec
    kept.sort(key=lambda e: -e["calls"])

    seq_goldens = [
        {"session_id": s, "tool_sequence": seq}
        for s, seq in sessions.items() if len(seq) >= 2
    ]
    seq_goldens.sort(key=lambda d: -len(d["tool_sequence"]))

    doc = {
        "generated_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "RAG/embeddings.db::network_log",
        "window_days": days,
        "min_calls": min_calls,
        "rows_scanned": n,
        "capabilities": kept,
        "sequences": seq_goldens[:200],
        "note": "arg_keys = CLES uniquement, jamais les valeurs (anti-fuite de jetons).",
    }
    MATRIX.parent.mkdir(parents=True, exist_ok=True)
    MATRIX.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    _log(f"{n} appels reussis scannes -> {len(kept)} capacites, "
         f"{len(seq_goldens)} sequences ({len(doc['sequences'])} gardees)")
    _log(f"ecrit : {MATRIX}")
    for e in kept[:10]:
        _log(f"  {e['calls']:>6}x {e['tool']:<26} keys={','.join(e['arg_keys'])[:60] or '-'}")
    return 0


# ── check : la capacite d'hier existe-t-elle encore ? ───────────────────────

def _tools_structural() -> tuple[set[str] | None, str]:
    """Inventaire STRUCTUREL : ce que le registre sait dispatcher.

    Source = les methodes `handle_<tool>` de ToolRegistry (80 mesurees le 2026-08-12).
    Independant du ring, de l'agent et de l'authentification -> repond exactement a
    « cette capacite existe-t-elle encore DANS LE CODE ».

    C'est le correctif du faux positif fondateur : `tools/list` est SCOPEE PAR RING
    (`get_tool_list(self, ring=4, agent=...)`) et ne rendait que 5 tools face a 29
    capacites historiques -> 24 « PERDU » dont `poll`, utilise 6 minutes plus tot.
    """
    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_mcp_registry import ToolRegistry  # type: ignore
    except Exception as e:  # import lourd : toute panne = NON OBSERVABLE
        return None, f"import forge_mcp_registry KO : {type(e).__name__}: {str(e)[:90]}"
    pre = "handle_"
    names = {a[len(pre):] for a in dir(ToolRegistry) if a.startswith(pre)}
    if not names:
        return None, "ToolRegistry sans methode handle_* -- forme inattendue"
    return names, "ToolRegistry.handle_*"


def _tools_exposed(ring: int = 0) -> tuple[set[str] | None, str]:
    """Inventaire EXPOSE au ring donne.

    L'ecart avec le structurel nomme une regression que rien d'autre ne voit :
    capacite encore CODEE mais PLUS OFFERTE. Ce n'est pas une perte de code, c'est
    une perte de surface -- et pour l'agent le resultat est le meme : il l'oublie.
    """
    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_mcp_registry import ToolRegistry  # type: ignore
        lst = ToolRegistry().get_tool_list(ring=ring)
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:90]}"
    names = {str(t.get("name")) for t in lst if isinstance(t, dict) and t.get("name")}
    return (names or None), f"get_tool_list(ring={ring})"


def cmd_check() -> int:
    if not MATRIX.exists():
        _log(f"INDETERMINE : matrice absente ({MATRIX}) -- lancer --extract")
        return 2
    doc = json.loads(MATRIX.read_text(encoding="utf-8"))
    struct, src = _tools_structural()
    if struct is None:
        _log(f"INDETERMINE : inventaire structurel NON OBSERVABLE ({src}).")
        _log("  Un refus n'est pas une absence -- aucune conclusion tiree.")
        return 2

    by_tool = {e["tool"]: e for e in doc.get("capabilities", [])}
    historiques = set(by_tool)
    # L'historique peut porter le prefixe MCP complet ; le registre expose le nom nu.
    def _base(t: str) -> str:
        return t.rsplit("__", 1)[-1]

    struct_base = {_base(t) for t in struct}
    _log(f"inventaire structurel : {len(struct)} tools ({src})")
    _log(f"capacites historiques : {len(historiques)}")

    exposed, esrc = _tools_exposed()
    if exposed is None:
        _log(f"surface exposee : INDETERMINE ({esrc})")
        _log("  Une seule source observable -> on ne peut pas conclure a une perte.")
        return 2
    exp_base = {_base(t) for t in exposed}
    _log(f"surface exposee (ring 0) : {len(exposed)} tools")

    # UNION obligatoire : `handle_*` rate les tools DYNAMIQUES (forge_deep_explore,
    # forge_spawn_swarm, nokido_ensure_service... sont exposes sans methode dediee).
    # Mesure du 2026-08-12 : la seule source structurelle produisait 5 faux "PERDU".
    connus = struct_base | exp_base
    perdus = sorted(t for t in historiques if _base(t) not in connus)

    # Ecart code/surface : encore code, plus offert. Pour l'agent, c'est un oubli.
    for t in sorted(historiques):
        if _base(t) in struct_base and _base(t) not in exp_base:
            _log(f"  MUET -- {t} existe dans le code mais n'est PLUS OFFERT "
                 f"({by_tool[t]['calls']} appels reussis, dernier {by_tool[t]['last_ts']})")

    if not perdus:
        _log("OK -- aucune capacite historique disparue.")
        return 0

    # Contre-preuve interne : un outil qui a reussi tres recemment EXISTE. Si
    # l'inventaire le dit absent, c'est l'inventaire qui est faux -- pas la capacite.
    contradictions = [
        t for t in perdus
        if (h := _hours_since(by_tool[t].get("last_ts"))) is not None and h <= RECENT_OK_HOURS
    ]
    if contradictions:
        _log("INDETERMINE -- l'inventaire CONTREDIT l'historique recent :")
        for t in sorted(contradictions):
            _log(f"  - {t} declare absent, or il a REUSSI il y a moins de {RECENT_OK_HOURS} h "
                 f"(dernier {by_tool[t]['last_ts']})")
        _log("  Donc l'inventaire est partiel ou faux. Aucune conclusion tiree.")
        return 2
    # Le journal agrege PLUSIEURS serveurs : netcfg-agent-mcp (:8767) et les endpoints
    # HTTP du hub y laissent des traces. Absent du registre du hub n'y vaut donc pas
    # "perdu" -- ca peut simplement ne pas etre un tool du hub. On separe les deux
    # au lieu d'accuser (2026-08-12 : `ingest` et `netcfg_ping` etaient dans ce cas).
    hub_ch = {"hub", "mcp", "stdio", "http"}
    vrais, a_trier = [], []
    for t in perdus:
        chans = set(by_tool[t].get("channels") or [])
        (vrais if chans & hub_ch else a_trier).append(t)

    for t in a_trier:
        e = by_tool[t]
        _log(f"  HORS-REGISTRE -- {t} (canaux={e.get('channels') or 'inconnu'}, "
             f"{e['calls']} appels, dernier {e['last_ts']}) : autre serveur MCP ou "
             f"endpoint HTTP ? a rattacher, pas une perte prouvee.")
    if not vrais:
        _log(f"OK -- 0 perte prouvee ; {len(a_trier)} entree(s) hors registre a rattacher.")
        return 0
    _log(f"PERDU -- {len(vrais)} capacite(s) du hub presente(s) dans l'historique, absente(s) aujourd'hui :")
    for t in vrais:
        e = by_tool[t]
        _log(f"  - {t}  ({e['calls']} appels reussis, dernier {e['last_ts']})")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Matrice anti-regression depuis network_log")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--stats", action="store_true", help="distributions reelles, sans rien supposer")
    g.add_argument("--extract", action="store_true", help="construit sandbox/regression_matrix.json")
    g.add_argument("--check", action="store_true", help="0 OK / 1 capacite perdue / 2 indetermine")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--min-calls", type=int, default=2)
    a = ap.parse_args()
    if a.stats:
        return cmd_stats()
    if a.extract:
        return cmd_extract(a.days, a.min_calls)
    return cmd_check()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
