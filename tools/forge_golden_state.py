#!/usr/bin/env python3
"""forge_golden_state.py — l'etat de REFERENCE, et de quoi mesurer sa derive.

Tout ce qui a ete repare le 2026-08-14 ne vaut que si l'on peut, demain, dire
en une commande si le systeme s'en est ecarte. Sans reference, chaque enquete
recommence a zero — c'est ainsi qu'un revert a pu emporter cinq mecanismes sans
que rien ne le signale pendant six semaines.

Trois etats, JAMAIS deux :
    PASS      mesure prise, conforme a la reference
    FAIL      mesure prise, ecart constate
    UNKNOWN   mesure IMPOSSIBLE (base verrouillee, service absent, droit refuse)

`UNKNOWN` n'est pas `PASS`. C'est la regle qui a manque toute la journee : une
sonde qui echoue et qu'on compte saine transforme une panne en bulletin vert —
`/health` repondant `ok` avec V: non monte, `rc=0` sur un gate saute, 35 orphelins
qui etaient des packages. Ici l'absence de mesure se DECLARE et empeche le vert
global.

La reference n'est PAS un ideal : c'est une photo datee d'un etat OBSERVE, prise
un jour ou la CI etait verte. La regenerer efface la memoire de la derive — ne
le faire que deliberement.

Usage :
    forge_golden_state.py --capturer     fige la reference (sandbox/golden_state.json)
    forge_golden_state.py --verifier     compare l'etat courant a la reference
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/quality : etat de reference et mesure de sa derive"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import ast
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))
GOLDEN = ROOT / "sandbox" / "golden_state.json"
RAG_DB = ROOT / "RAG" / "embeddings.db"
IGNORES = {"_attic", "node_modules", "backups", "archive"}

# Tolerances : un compte de chunks bouge en permanence (ingestion continue), un
# nombre de modules non. Comparer sans tolerance rendrait le rapport rouge en
# permanence, donc illisible — le defaut qu'on combat.
TOLERANCE_PCT = {"rag_chunks": 25.0, "rag_fts": 25.0, "rag_chunks_fts": 25.0}


def _mesure(nom: str, fn) -> dict:
    """Prend une mesure en declarant son echec plutot qu'en le taisant."""
    try:
        return {"nom": nom, "valeur": fn(), "etat": "mesure"}
    except Exception as e:  # noqa: BLE001
        return {"nom": nom, "valeur": None, "etat": "UNKNOWN",
                "pourquoi": f"{type(e).__name__}: {str(e)[:120]}"}


def _modules() -> int:
    n = 0
    for zone in ("app", "tools", "forge_desktop", "recon_silo"):
        d = ROOT / zone
        if d.is_dir():
            n += sum(1 for p in d.glob("**/*.py") if not (IGNORES & set(p.parts)))
    return n


def _modules_qui_parsent() -> int:
    n = 0
    for zone in ("app", "tools", "forge_desktop", "recon_silo"):
        d = ROOT / zone
        if not d.is_dir():
            continue
        for p in d.glob("**/*.py"):
            if IGNORES & set(p.parts):
                continue
            try:
                ast.parse(p.read_text(encoding="utf-8", errors="replace"))
                n += 1
            except (SyntaxError, OSError):
                pass
    return n


def _compte_sql(table: str) -> int:
    # Lecture SEULE, timeout court : ne jamais bloquer sur la base de memoire.
    conn = sqlite3.connect(f"file:{RAG_DB}?mode=ro", uri=True, timeout=5.0)
    try:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _boucles_sans_code() -> int:
    from nokido_agent.tools.forge_regulation_loops import verifier_implementations

    return len(verifier_implementations())


def _pouls_stale() -> int:
    from nokido_agent.tools.forge_stale_guard import scanner

    return sum(1 for f in scanner() if f["verdict"] == "STALE")


def _services_declares() -> int:
    import tomllib

    t = (ROOT / "proxy_deno" / "core" / "services.toml").read_text(
        encoding="utf-8", errors="replace")
    return len(tomllib.loads(t).get("service") or [])


def _sha_head() -> str:
    # `errors="replace"` n'est pas cosmetique : un subprocess en mode texte sans
    # lui fait crasher `_readerthread` des qu'un octet non decodable passe —
    # motif de l'incident 47 Go, signale par le gate firehose.
    r = subprocess.run(["git", "-C", str(ROOT), "-c", "safe.directory=*",
                        "rev-parse", "HEAD"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30)
    return (r.stdout or "").strip()[:8]


SONDES = [
    ("modules_total", _modules),
    ("modules_qui_parsent", _modules_qui_parsent),
    ("boucles_regulation_sans_code", _boucles_sans_code),
    ("pouls_stale", _pouls_stale),
    ("services_declares", _services_declares),
    ("rag_chunks", lambda: _compte_sql("rag_chunks")),
    ("rag_fts", lambda: _compte_sql("rag_fts_docsize")),
    ("rag_chunks_fts", lambda: _compte_sql("rag_chunks_fts_docsize")),
    ("sha_head", _sha_head),
]


def relever() -> dict:
    return {m["nom"]: m for m in (_mesure(n, f) for n, f in SONDES)}


def capturer(date: str) -> int:
    etat = relever()
    inconnues = [m["nom"] for m in etat.values() if m["etat"] == "UNKNOWN"]
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(
        {"date": date, "mesures": etat,
         "avertissement": "Photo d'un etat OBSERVE, pas d'un ideal. La "
                          "regenerer efface la memoire de la derive."},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[golden] reference figee ({date}) -> {GOLDEN}")
    for nom, m in etat.items():
        marque = "?" if m["etat"] == "UNKNOWN" else " "
        print(f"  {marque} {nom:32s} {m['valeur']}"
              + (f"   ({m.get('pourquoi')})" if m["etat"] == "UNKNOWN" else ""))
    if inconnues:
        # Une reference qui contient des trous les porte a vie : le dire fort.
        print(f"\n[golden] ATTENTION {len(inconnues)} sonde(s) NON MESUREE(S) : "
              f"{', '.join(inconnues)} — figees en UNKNOWN, elles ne pourront "
              "rien attester tant qu'elles ne sont pas reparees.")
    return 0


def verifier() -> int:
    if not GOLDEN.exists():
        print(f"[golden] aucune reference : lancer --capturer d'abord ({GOLDEN})")
        return 2
    ref = json.loads(GOLDEN.read_text(encoding="utf-8"))
    courant = relever()
    verdicts, pire = [], "PASS"
    for nom, attendu in ref["mesures"].items():
        obs = courant.get(nom, {"valeur": None, "etat": "UNKNOWN",
                                "pourquoi": "sonde disparue"})
        if obs["etat"] == "UNKNOWN" or attendu["etat"] == "UNKNOWN":
            v, detail = "UNKNOWN", obs.get("pourquoi", "reference non mesuree")
        elif isinstance(attendu["valeur"], (int, float)) and attendu["valeur"]:
            ecart = abs(obs["valeur"] - attendu["valeur"]) / attendu["valeur"] * 100
            tol = TOLERANCE_PCT.get(nom, 0.0)
            v = "PASS" if ecart <= tol else "FAIL"
            detail = (f"{attendu['valeur']} -> {obs['valeur']} "
                      f"({ecart:+.1f} %, tolerance {tol:.0f} %)")
        else:
            v = "PASS" if obs["valeur"] == attendu["valeur"] else "FAIL"
            detail = f"{attendu['valeur']} -> {obs['valeur']}"
        verdicts.append((v, nom, detail))
        if v == "FAIL" or (v == "UNKNOWN" and pire != "FAIL"):
            pire = v

    print(f"[golden] reference du {ref.get('date')} — verdict global : {pire}\n")
    for v, nom, detail in sorted(verdicts, key=lambda x: {"FAIL": 0, "UNKNOWN": 1,
                                                          "PASS": 2}[x[0]]):
        print(f"  {v:8s} {nom:32s} {detail}")
    # `sha_head` bouge a chaque commit : son FAIL est attendu et informatif.
    print("\n[golden] rappel : UNKNOWN n'est pas PASS. Une sonde qui ne peut pas "
          "mesurer ne prouve rien.")
    return 0 if pire == "PASS" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capturer", action="store_true")
    ap.add_argument("--verifier", action="store_true")
    ap.add_argument("--date", default="2026-08-14")
    a = ap.parse_args()
    if a.capturer:
        return capturer(a.date)
    if a.verifier:
        return verifier()
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
