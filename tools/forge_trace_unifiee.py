#!/usr/bin/env python3
"""forge_trace_unifiee.py — tout ce qui entre et sort, et ce qu'on NE trace PAS.

Demande owner : « je veux une interface qui log tout, le stdio, le SSE, les
appels cloud, depuis ou vers ou », motivee par le tracage des regressions.

Mesure du 2026-08-12 sur `network_log` (228 000 lignes) :
  - le STDIO est deja trace : STDIO_CLAUDE 10 965 IN / 10 684 OUT ;
  - le SSE n'apparait NULLE PART — aucun canal, aucune ligne ;
  - les appels CLOUD ne sont marques que 30 fois (colonne `provider` renseignee)
    alors que le routeur en emet en continu.

Un traceur qui tait ses angles morts est pire qu'absent : il donne l'illusion de
la couverture. Ce rapport affiche donc TOUJOURS deux sections — ce qui est trace,
et ce qui devrait l'etre et ne l'est pas.

Couvre aussi les quatre sujets que l'owner veut voir traces :
  NSSM/autonomie · backend de configuration · tools offerts vs appeles ·
  MCP Nokido <-> MCP docker.

Usage : trusted_script tools/forge_trace_unifiee.py [--html]
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
SANDBOX = ROOT / "sandbox"

# Canaux ATTENDUS. Un canal attendu et absent est un angle mort, pas un silence.
_ATTENDUS = {
    "HTTP_DIRECT": "appels HTTP du hub",
    "STDIO_CLAUDE": "bridge stdio Claude Desktop",
    "CLINE_MCP": "bridge Cline",
    "CODEX_MCP": "bridge Codex",
    "GEMINI_OAUTH": "canal Gemini",
    "INTERNAL_HUB": "trafic interne",
    "SSE": "flux evenementiel :7401",
    "MCP_DOCKER": "passerelle MCP docker",
}


def _con():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def _trafic(con) -> list:
    return con.execute(
        "SELECT channel, direction, COUNT(*), COUNT(DISTINCT agent), "
        "COUNT(DISTINCT tool), SUM(CASE WHEN provider IS NOT NULL AND provider<>'' "
        "THEN 1 ELSE 0 END), ROUND(AVG(latency_ms),1) "
        "FROM network_log GROUP BY channel, direction ORDER BY COUNT(*) DESC"
    ).fetchall()


# La colonne `tool` N'A PAS LE MEME SENS selon le canal. Mesure 2026-08-12 : sur
# le canal TOKENS elle porte le MODELE ou la STRATEGIE (`gemini-3.1`,
# `mistral-large-latest`, `cascade qualite (use_case auto)`), pas un outil. Les
# compter comme des tools « appeles hors catalogue » etait une erreur de lecture
# de ma part, pas une donnee corrompue : le canal a sa propre convention.
_CANAUX_NON_TOOLS = ("TOKENS",)


def _tools_appeles(con) -> dict:
    marques = ",".join("?" * len(_CANAUX_NON_TOOLS))
    return {t: n for t, n in con.execute(
        "SELECT tool, COUNT(*) FROM network_log WHERE tool IS NOT NULL AND tool<>'' "
        "AND (channel IS NULL OR channel NOT IN (%s)) GROUP BY tool" % marques,
        _CANAUX_NON_TOOLS).fetchall()}


def _cloud(con) -> tuple:
    """Appels vers un modele : `provider` renseigne OU canal TOKENS.

    Le canal TOKENS journalise la consommation PAR MODELE — c'est de la trace
    cloud, meme quand `provider` est vide. La compter comme absente sous-estimait
    la couverture reelle.
    """
    prov = con.execute(
        "SELECT COUNT(*) FROM network_log WHERE provider IS NOT NULL AND provider<>''"
    ).fetchone()[0]
    tok = con.execute(
        "SELECT COUNT(*) FROM network_log WHERE channel='TOKENS'").fetchone()[0]
    return prov, tok


def _tools_offerts() -> set:
    """Les tools DECLARES au catalogue (_TOOL_MIN_RING)."""
    import re
    src = (ROOT / "app" / "forge_mcp_registry.py").read_text(
        encoding="utf-8", errors="replace")
    i = src.find("_TOOL_MIN_RING")
    if i < 0:
        return set()
    bloc = src[i:src.find("\n    }", i)]
    return set(re.findall(r'"([a-z_0-9]+)"\s*:', bloc))


def _sessions(con) -> tuple:
    n, remplis = con.execute(
        "SELECT COUNT(*), COUNT(session_id) FROM network_log").fetchone()
    return n, remplis


def _vivant() -> dict:
    now = time.time()
    hb = {f.stem: round(now - f.stat().st_mtime)
          for f in SANDBOX.glob("*.heartbeat")}
    want = {f.stem: round(now - f.stat().st_mtime)
            for f in SANDBOX.glob("*.wanted")}
    return {"heartbeats_frais": sum(1 for a in hb.values() if a < 300),
            "heartbeats_total": len(hb),
            "intentions": want}


def main() -> int:
    if not DB.exists():
        print("[trace] base introuvable: %s" % DB)
        return 2
    con = _con()
    trafic = _trafic(con)
    appeles = _tools_appeles(con)
    n_log, n_sess = _sessions(con)
    con.close()
    offerts = _tools_offerts()

    vus = {c for c, *_ in trafic}
    muets = {c: d for c, d in _ATTENDUS.items() if c not in vus}
    # Un tool appele mais absent du catalogue = utilise sans etre offert.
    invisibles = {t: n for t, n in appeles.items() if t and t not in offerts}
    jamais = sorted(offerts - set(appeles))

    print("=" * 72)
    print("  TRACE UNIFIEE — ce qui passe, et ce qu'on ne voit pas")
    print("=" * 72)
    print("\n-- TRACE (canal / sens) " + "-" * 44)
    print("  %-16s %-4s %9s %7s %6s %7s %9s"
          % ("CANAL", "SENS", "LIGNES", "AGENTS", "TOOLS", "CLOUD", "LAT.MOY"))
    for c, d, n, na, nt, cl, lat in trafic:
        print("  %-16s %-4s %9d %7d %6d %7d %9s"
              % ((c or "?")[:16], d or "?", n, na, nt, cl or 0, lat if lat else "-"))

    print("\n-- ANGLES MORTS " + "-" * 52)
    if muets:
        for c, d in muets.items():
            print("  ⚠ %-14s AUCUNE ligne — %s" % (c, d))
    else:
        print("  aucun canal attendu n'est muet")
    con2 = _con()
    prov, tok = _cloud(con2)
    con2.close()
    cloud = prov + tok
    print("  ⚠ appels vers un MODELE : %d (provider renseigne : %d · canal "
          "TOKENS : %d) sur %d lignes (%.3f %%)"
          % (cloud, prov, tok, n_log, 100.0 * cloud / max(n_log, 1)))
    print("    `provider` n'est renseignee que par une poignee d'appelants ; le")
    print("    canal TOKENS porte le modele dans `tool`, sans provider.")
    print("  %s session_id : %d/%d renseignes"
          % ("✓" if n_sess else "⚠", n_sess, n_log))

    print("\n-- TOOLS : offerts vs appeles " + "-" * 38)
    print("  catalogue (_TOOL_MIN_RING) : %d" % len(offerts))
    print("  appeles au moins une fois  : %d" % len(appeles))
    if invisibles:
        print("  ⚠ APPELES SANS ETRE AU CATALOGUE (%d) :" % len(invisibles))
        for t, n in sorted(invisibles.items(), key=lambda x: -x[1])[:12]:
            print("      %-28s %6d appels" % (t, n))
    if jamais:
        print("  offerts JAMAIS appeles (%d) : %s"
              % (len(jamais), ", ".join(jamais[:12])))

    v = _vivant()
    print("\n-- AUTONOMIE (NSSM / on-demand) " + "-" * 36)
    print("  heartbeats frais (< 5 min) : %d / %d"
          % (v["heartbeats_frais"], v["heartbeats_total"]))
    for nom, age in sorted(v["intentions"].items()):
        etat = "ACTIVE" if age < 900 else "expiree (%d s)" % age
        print("  intention %-10s %s" % (nom, etat))

    out = SANDBOX / "trace_unifiee.json"
    out.write_text(json.dumps({
        "trafic": [{"canal": c, "sens": d, "lignes": n, "agents": na,
                    "tools": nt, "cloud": cl, "latence_moy": lat}
                   for c, d, n, na, nt, cl, lat in trafic],
        "angles_morts": muets,
        "cloud_identifies": cloud, "lignes_total": n_log,
        "session_id_remplis": n_sess,
        "tools_invisibles": invisibles, "tools_jamais_appeles": jamais,
        "vivant": v,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n  ecrit : %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
