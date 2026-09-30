"""nokido_cutover_migrate.py — migration RUNTIME-STATE du cutover Nokido.

À lancer APRÈS l'application du renommage code sur le live (nokido_deep_rename.py
--apply --root <LIVE>), pendant la fenêtre de cutover. Fait les parties DÉTERMINISTES :

  1. RAG DB : domaines laforge_* -> nokido_* (rag_chunks + rag_fts si présent).
  2. Fixup chemins durs : 'Script python IA[\\/]Nokido' -> LaForge (le dossier
     submodule reste LaForge/ ; rattrape les 2 résiduels non protégés).
  3. Rename .env : LaForge.env(.secrets) -> Nokido.env(.secrets) (le hub renommé lit
     Nokido.env).

Idempotent. --apply pour écrire (dry par défaut). NE touche PAS NSSM/schtasks/clients
(coordination manuelle = runbook). RBAC wrk_nokido déjà seedé (forge_seed_nokido_entity).
"""
import argparse
import os
import re
import sqlite3

DIRFIX = re.compile(r"(Script python IA[\\/]+)Nokido")


def migrate_db(root, apply, reverse=False):
    src, dst = ("nokido", "laforge") if reverse else ("laforge", "nokido")
    Src, Dst = ("Nokido", "LaForge") if reverse else ("LaForge", "Nokido")
    db = os.path.join(root, "RAG", "embeddings.db")
    if not os.path.isfile(db):
        return "DB absente: " + db
    c = sqlite3.connect(db)
    try:
        rows = c.execute(
            "SELECT domain, COUNT(*) FROM rag_chunks WHERE domain LIKE ? GROUP BY domain", ("%" + src + "%",)
        ).fetchall()
        total = sum(n for _, n in rows)
        if apply:
            c.execute(
                "UPDATE rag_chunks SET domain = REPLACE(REPLACE(domain,?,?),?,?) WHERE domain LIKE ?",
                (src, dst, Src, Dst, "%" + src + "%"),
            )
            c.commit()
        return "DB domaines %s->%s: %d lignes sur %d domaines (%s)" % (src, dst, total, len(rows), "APPLIED" if apply else "DRY")
    finally:
        c.close()


def migrate_paths(root, apply):
    n = 0
    for dp, dn, fn in os.walk(root):
        if ".git" in dp.replace("\\", "/").split("/"):
            continue
        for f in fn:
            if not f.endswith((".py", ".md", ".json", ".toml", ".ts", ".bat", ".ps1", ".cmd", ".txt", ".yml", ".yaml", ".xml")):
                continue
            p = os.path.join(dp, f)
            try:
                t = open(p, encoding="utf-8", errors="surrogateescape").read()
            except Exception:
                continue
            if not DIRFIX.search(t):
                continue
            n += 1
            if apply:
                open(p, "w", encoding="utf-8", errors="surrogateescape", newline="").write(DIRFIX.sub(r"\1LaForge", t))
    return "Fixup chemins durs -> LaForge: %d fichiers (%s)" % (n, "APPLIED" if apply else "DRY")


def migrate_env(root, apply):
    done = []
    for old, new in (("LaForge.env", "Nokido.env"), ("LaForge.env.secrets", "Nokido.env.secrets")):
        op = os.path.join(root, old)
        np = os.path.join(root, new)
        if os.path.isfile(op) and not os.path.exists(np):
            done.append(old + " -> " + new)
            if apply:
                os.rename(op, np)
    return "Rename .env: " + (", ".join(done) if done else "rien") + (" (APPLIED)" if apply else " (DRY)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--skip-db", action="store_true", help="ne pas toucher la DB (UPDATE = fenetre hub-stoppe)")
    ap.add_argument("--reverse", action="store_true", help="rollback DB: nokido_*->laforge_*")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.skip_db:
        print("DB: SKIP (--skip-db)")
    else:
        print(migrate_db(root, a.apply, a.reverse))
    print(migrate_paths(root, a.apply))
    print(migrate_env(root, a.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
