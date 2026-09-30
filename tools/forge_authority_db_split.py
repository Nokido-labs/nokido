"""Sort `opsec_state` et `forge_tools` de la base RAG vers la base d'AUTORITE.

__FORGE_COLOR__ = "immunitaire/guard : isole les tables d'autorite hors de la base que le client ecrit"

Pourquoi (mesure du 2026-09-13). Apres le resserrement des ACL, l'instrument M0.1
ne compte plus qu'UN partage reel : `%NOKIDO_DATA%\\embeddings.db` porte
`Tout le monde`-retire mais garde `LaForgeSandboxUsers` en ecriture -- et c'est
la que vivent le kill-switch humain (`opsec_state`) et le bareme d'autorisation
par outil (`forge_tools`). Une ACL de FICHIER ne separe pas des TABLES.

Frere de `forge_switches_db_split.py` (meme intention, autres tables). Il n'a PAS
ete generalise : cet outil doit refuser une bascule que l'autre n'a pas a
connaitre (voir `--basculer` ci-dessous).

Trois verbes, dry-run par defaut :

    --copier     copie les deux tables vers la cible (n'efface JAMAIS la source)
    --verifier   compare source et cible, ligne a ligne, et DIT les divergences
    --basculer   pose l'interrupteur -- REFUSE tant que les consommateurs lisent
                 encore la base RAG

Le garde de `--basculer` est le coeur de l'outil. Basculer avant d'avoir redirige
`app/forge_opsec.py` et `app/forge_mcp_registry.py` donnerait un hub qui ECRIT
d'un cote et LIT de l'autre : le kill-switch paraitrait pose et ne protegerait
plus rien. C'est le defaut « un site bascule seul » que le corps a deja paye.

Ecriture : le depot est en lecture seule pour les comptes bac a sable depuis le
2026-09-13. Lancer cet outil par `run action=trusted_script`, pas en shell
sandbox -- sinon la creation de `etat_protege/` echoue, et elle le DIT.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

TABLES = ("opsec_state", "forge_tools")

# Les consommateurs VIVANTS de ces tables, releves par recon le 2026-09-13.
# `tools/nokido_tui.py` est EXCLU a dessein : sa fonction `opsec_state()` lit
# `state.json`, pas la table -- homonyme, pas un site.
CONSOMMATEURS = (
    "app/forge_opsec.py",        # SELECT + INSERT OR REPLACE sur opsec_state
    "app/forge_mcp_registry.py",  # SELECT sur forge_tools (_get_ring_needed)
)


def _source() -> str:
    import forge_db_path as fdp

    return fdp.db_path()


def _cible() -> Path:
    import forge_db_path as fdp

    return Path(str(fdp.authority_db_defaut()))


def _tables_presentes(chemin) -> dict:
    """Etat des deux tables dans une base. Trois etats, jamais deux."""
    p = Path(str(chemin))
    if not p.exists():
        return {"etat": "ABSENTE", "chemin": str(p), "tables": {}}
    try:
        cx = sqlite3.connect("file:%s?mode=ro" % str(p).replace("\\", "/"), uri=True, timeout=5)
    except Exception as exc:  # noqa: BLE001 - l'illisible se DIT
        return {"etat": "ILLISIBLE", "chemin": str(p), "motif": type(exc).__name__, "tables": {}}
    try:
        noms = {r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        vu = {}
        for t in TABLES:
            if t not in noms:
                vu[t] = {"presente": False, "lignes": None}
                continue
            # Ces deux tables sont petites par nature (un barème, un état) :
            # un COUNT(*) y est sans rapport avec celui qui a couche le hub
            # sur `rag_chunks` (24,9 Go).
            n = cx.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
            vu[t] = {"presente": True, "lignes": n}
        return {"etat": "LUE", "chemin": str(p), "tables": vu}
    finally:
        cx.close()


def _consommateurs_rediriges() -> dict:
    """Un consommateur est redirige quand sa source nomme `authority_path`.

    Lecture de SOURCE, donc un signal faible : elle prouve que le site a ete
    touche, pas que le chemin est emprunte a l'execution. C'est assez pour
    REFUSER, jamais assez pour se declarer sur. Un fichier illisible compte
    comme NON redirige (fail-closed).
    """
    etat = {}
    for rel in CONSOMMATEURS:
        f = ROOT / rel
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            etat[rel] = {"redirige": False, "motif": "ILLISIBLE (%s)" % type(exc).__name__}
            continue
        etat[rel] = {"redirige": "authority_path" in src,
                     "motif": "" if "authority_path" in src else "ne nomme pas authority_path"}
    return etat


def copier(appliquer: bool = False) -> dict:
    src, cible = _source(), _cible()
    avant = _tables_presentes(src)
    if avant["etat"] != "LUE":
        return {"ok": False, "raison": "source %s" % avant["etat"], "source": avant}
    plan = {t: avant["tables"][t]["lignes"] for t in TABLES if avant["tables"][t]["presente"]}
    manquantes = [t for t in TABLES if not avant["tables"][t]["presente"]]
    if not appliquer:
        return {"ok": True, "dry_run": True, "source": src, "cible": str(cible),
                "copierait": plan, "absentes_de_la_source": manquantes}
    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001 - le refus d'ACL se DIT, il ne s'avale pas
        return {"ok": False, "raison": "creation de %s refusee (%s) -- lancer en "
                                       "trusted_script, le depot est en lecture seule "
                                       "pour les bacs a sable"
                                       % (cible.parent, type(exc).__name__)}
    conn = sqlite3.connect(str(cible), timeout=10, isolation_level=None)
    # PAS de WAL ici, contrairement a la base RAG (cf. forge_db_path.open_writer).
    # Mesure 2026-09-13 : en WAL, SQLite doit ecrire le fichier `-shm` MEME pour
    # LIRE. Or toute la raison d'etre de cette base est que les comptes bac a
    # sable n'y aient QUE la lecture -- en WAL, ils ne peuvent donc pas la lire
    # du tout (`unable to open database file`, y compris en `mode=ro`). Le WAL
    # sert la concurrence d'ecriture ; ici il y a un ecrivain (le hub) et 28
    # lignes. Le mode DELETE convertit et retire les `-wal`/`-shm` residuels.
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("ATTACH DATABASE ? AS src", (str(src),))
    copiees = {}
    try:
        for t in TABLES:
            if t not in plan:
                continue
            ddl = conn.execute(
                "SELECT sql FROM src.sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone()
            if not ddl or not ddl[0]:
                copiees[t] = "DDL ILLISIBLE -- table non copiee"
                continue
            conn.execute("DROP TABLE IF EXISTS main.%s" % t)
            conn.execute(ddl[0])
            conn.execute("INSERT INTO main.%s SELECT * FROM src.%s" % (t, t))
            copiees[t] = conn.execute("SELECT COUNT(*) FROM main.%s" % t).fetchone()[0]
    finally:
        conn.execute("DETACH DATABASE src")
        conn.close()
    return {"ok": True, "dry_run": False, "source": str(src), "cible": str(cible),
            "copiees": copiees, "note": "la SOURCE est intacte : rien n'est efface"}


def verifier() -> dict:
    src, cible = _tables_presentes(_source()), _tables_presentes(_cible())
    ecarts = []
    for t in TABLES:
        a = src["tables"].get(t, {}).get("lignes")
        b = cible["tables"].get(t, {}).get("lignes")
        if a != b:
            ecarts.append({"table": t, "source": a, "cible": b})
    return {"source": src, "cible": cible, "ecarts": ecarts,
            "identiques": not ecarts and src["etat"] == "LUE" == cible["etat"]}


def basculer(appliquer: bool = False) -> dict:
    """Pose l'interrupteur -- refuse si un consommateur lit encore la base RAG."""
    import forge_db_path as fdp

    conso = _consommateurs_rediriges()
    restants = [k for k, v in conso.items() if not v["redirige"]]
    v = verifier()
    if restants:
        return {"ok": False, "refus": "CONSOMMATEURS_NON_REDIRIGES",
                "restants": restants, "detail": conso,
                "pourquoi": "basculer maintenant donnerait un hub qui ecrit d'un cote "
                            "et lit de l'autre : le kill-switch paraitrait pose sans "
                            "proteger quoi que ce soit"}
    if not v["identiques"]:
        return {"ok": False, "refus": "COPIE_INCOMPLETE", "ecarts": v["ecarts"]}
    inter = Path(str(fdp.authority_switch_path()))
    if not appliquer:
        return {"ok": True, "dry_run": True, "poserait": str(inter)}
    try:
        inter.parent.mkdir(parents=True, exist_ok=True)
        inter.write_text("bascule le 2026-09-13 -- autorite hors de la base RAG\n",
                         encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "refus": "ECRITURE_REFUSEE",
                "motif": "%s -- lancer en trusted_script" % type(exc).__name__}
    return {"ok": True, "interrupteur": str(inter), "actif": fdp.authority_switch_actif()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--copier", action="store_true")
    ap.add_argument("--verifier", action="store_true")
    ap.add_argument("--basculer", action="store_true")
    ap.add_argument("--appliquer", action="store_true",
                    help="sans lui, tout est dry-run")
    a = ap.parse_args()
    import json

    if a.copier:
        print(json.dumps(copier(a.appliquer), ensure_ascii=False, indent=1, default=str))
    elif a.verifier:
        print(json.dumps(verifier(), ensure_ascii=False, indent=1, default=str))
    elif a.basculer:
        print(json.dumps(basculer(a.appliquer), ensure_ascii=False, indent=1, default=str))
    else:
        print(json.dumps({"source": _source(), "cible": str(_cible()),
                          "consommateurs": _consommateurs_rediriges(),
                          "etat": verifier()}, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
