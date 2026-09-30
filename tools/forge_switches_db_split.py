# -*- coding: utf-8 -*-
"""tools/forge_switches_db_split.py — sortir `access_switches` de la base du RAG.

CAUSE MESUREE (2026-09-05, trois chutes du hub en une heure). La table
`access_switches` -- consultee a CHAQUE appel de tool, et le gate est FAIL-CLOSED --
vit dans `embeddings.db`, la base de 24,9 Go que le RAG, l'ingestion, le backfill,
l'embed daemon et pytest ecrivent tous (`forge_access_switches.DEFAULT_DB_PATH`).

Chaine OBSERVEE en direct, pas deduite :

    verrou sur embeddings.db
      -> GATE_DENIED sur TOUS les tools   (hub vivant, totalement inutilisable)
      -> Unable to connect                 (hub mort, tue par son healthcheck)

Disproportion : **19 regles** decident de toute l'autorisation, depuis le plus gros
fichier concurrent du systeme. Une contention d'ingestion devient une paralysie de
l'autorisation, puis une mort du hub.

CE CORRECTIF NE DEPEND PAS D'IDENTIFIER QUI VERROUILLE -- et c'est sa qualite
principale : SQLite ne nomme jamais le tenant d'un verrou, donc un remede qui
exigerait de le connaitre ne serait jamais applicable. On coupe la PROPAGATION.

ORDRE SUR (chaque etape est verifiable avant la suivante) :
  1. `--copier`   cree la base dediee et y recopie les regles. NON DESTRUCTIF :
                  l'ancienne table n'est pas touchee, le gate continue de la lire.
  2. `--verifier` relit les regles depuis la base dediee et les compare une a une.
  3. la BASCULE (poser `LAFORGE_SWITCHES_DB_PATH`) reste un geste OWNER : un gate
     mal migre ouvre ou ferme TOUT. Ce script ne bascule jamais de lui-meme.

Dry-run par defaut.
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/db : sortir access_switches de la base du RAG (scission)"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

# Base dediee : petite, locale, sans aucun autre ecrivain. `sandbox/` est deja le
# lieu des etats du corps (wanted, heartbeats, jobs) et reste inscriptible aux
# comptes de service -- contrairement a `tests/nr`, mesure le meme jour.
CIBLE_DEFAUT = ROOT / "sandbox" / "access_switches.db"

COLONNES = ("id", "agent_pattern", "resource_pattern", "action", "allowed",
            "condition_dsl", "expires_at", "granted_by", "grant_reason",
            "created_at", "updated_at", "version")


def _source() -> str:
    from nokido_agent.app.forge_access_switches import DEFAULT_DB_PATH

    return str(DEFAULT_DB_PATH)


def _lire_regles(chemin: str) -> list[tuple]:
    """Lecture SEULE et bornee. `mode=ro` : ce script ne doit jamais pouvoir
    ecrire dans la base du RAG, meme par accident -- c'est elle qu'on fuit."""
    conn = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True, timeout=15.0)
    try:
        conn.execute("PRAGMA query_only=1")
        return list(conn.execute("SELECT %s FROM access_switches" % ", ".join(COLONNES)))
    finally:
        conn.close()


def copier(cible: Path, appliquer: bool, source: str | None = None) -> dict:
    """`source` explicite : sans lui, cette fonction depend de l'etat GLOBAL du
    module `forge_access_switches` (son `DEFAULT_DB_PATH`), donc de l'ordre des
    appels. Mesure du 2026-09-05 : trois tests ont echoue parce qu'un `reload`
    anterieur laissait ce global sur un chemin detruit. Un outil qui ne peut pas
    etre appele deux fois de suite avec le meme resultat n'est pas verifiable."""
    src = source or _source()
    regles = _lire_regles(src)
    out = {"source": src, "cible": str(cible), "regles_lues": len(regles),
           "applique": bool(appliquer)}
    if not appliquer:
        out["note"] = "dry-run : rien ecrit"
        return out
    from nokido_agent.app.forge_access_switches import DDL

    cible.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(cible), timeout=15.0, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(DDL)
        # INSERT OR REPLACE : le script est IDEMPOTENT, on peut le rejouer apres
        # une modification de regle sans dupliquer ni perdre.
        conn.executemany(
            "INSERT OR REPLACE INTO access_switches (%s) VALUES (%s)"
            % (", ".join(COLONNES), ", ".join("?" * len(COLONNES))), regles)
        out["regles_ecrites"] = conn.total_changes
    finally:
        conn.close()
    return out


def verifier(cible: Path, source: str | None = None) -> dict:
    """Compare regle a regle. Un COUNT identique ne prouve rien : deux tables
    peuvent avoir le meme nombre de lignes et des contenus differents."""
    src = source or _source()
    if not cible.exists():
        return {"ok": False, "raison": "base dediee ABSENTE (%s)" % cible,
                "note": "ABSENT n'est pas VIDE : la copie n'a pas ete faite"}
    a = sorted(_lire_regles(src))
    b = sorted(_lire_regles(str(cible)))
    manquantes = [r for r in a if r not in b]
    en_trop = [r for r in b if r not in a]
    return {"ok": not manquantes and not en_trop, "source_n": len(a), "cible_n": len(b),
            "manquantes": [r[0] for r in manquantes], "en_trop": [r[0] for r in en_trop]}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - muet-ok : sortie non reconfigurable
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--copier", action="store_true", help="recopier les regles (avec --apply)")
    ap.add_argument("--verifier", action="store_true", help="comparer regle a regle")
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut : dry-run)")
    ap.add_argument("--cible", default=str(CIBLE_DEFAUT))
    a = ap.parse_args()
    cible = Path(a.cible)
    import json

    if a.copier:
        print(json.dumps(copier(cible, a.apply), ensure_ascii=False, indent=1))
    if a.verifier:
        r = verifier(cible)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        if not r.get("ok"):
            return 1
    if not (a.copier or a.verifier):
        print("rien demande : --copier [--apply] et/ou --verifier")
        print("BASCULE (geste OWNER, jamais fait ici) :")
        print("  poser LAFORGE_SWITCHES_DB_PATH=%s puis relancer le hub" % cible)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
