import hashlib
import os
import sqlite3
import time
from pathlib import Path

# Configuration
# On cible le gitingest de litellm pour l'exemple
SRC_DIR = Path(
    __import__("os").path.expanduser(r"~\AppData\Local\Temp\gitingest\f7f420a0-ae7c-4f87-9667-fccca2e95a95\berriai-litellm")
)
DB_PATH = Path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db"))
DOMAIN = "gitingest_litellm"
CHUNK_SIZE = 2500
OVERLAP = 300


def sha256_id(source, text):
    return hashlib.sha256((source + text).encode()).hexdigest()[:16]


def chunk_text(text, size=CHUNK_SIZE, overlap=OVERLAP):
    # Split simple par caractères pour le batching massif
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return chunks


def main():
    if not SRC_DIR.exists():
        print(f"[batch-ingest] ERREUR : dossier source introuvable : {SRC_DIR}")
        return

    print(f"[batch-ingest] Scan de {SRC_DIR}...")
    files = []
    # On prend les fichiers .py, .md, .json, .txt, .prisma
    extensions = {".py", ".md", ".json", ".txt", ".prisma", ".toml", ".yaml", ".yml"}
    for root, dirs, f_names in os.walk(SRC_DIR):
        if ".git" in root or "__pycache__" in root:
            continue
        for fn in f_names:
            p = Path(root) / fn
            if p.suffix in extensions:
                files.append(p)

    print(f"[batch-ingest] {len(files)} fichiers trouvés.")

    # Batch de 50 fichiers
    batch_size = 50
    con = sqlite3.connect(str(DB_PATH))
    total_inserted = 0
    t0 = time.time()

    for i in range(0, len(files), batch_size):
        batch = files[i : i + batch_size]
        print(f"[batch-ingest] Traitement batch {i // batch_size + 1} ({len(batch)} fichiers)...")

        batch_inserted = 0
        for fpath in batch:
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
                if not text.strip():
                    continue

                # Source relative
                rel_path = fpath.relative_to(SRC_DIR)
                src = f"gitingest/litellm/{rel_path.as_posix()}"

                chunks = chunk_text(text)
                for chunk in chunks:
                    if len(chunk.strip()) < 50:
                        continue
                    cid = sha256_id(src, chunk)
                    con.execute(
                        "INSERT OR IGNORE INTO rag_chunks(id,text,source,domain,role_hint,ingested_at) VALUES(?,?,?,?,?,?)",
                        (cid, chunk, src, DOMAIN, "code", time.time()),
                    )
                    if con.execute("SELECT changes()").fetchone()[0]:
                        batch_inserted += 1
            except Exception as e:
                print(f"  [ERR] {fpath.name}: {e}")

        con.commit()
        total_inserted += batch_inserted
        print(f"  [OK] Batch terminé : {batch_inserted} nouveaux chunks. Total: {total_inserted}")

    con.close()
    print(f"[batch-ingest] TERMINE : {total_inserted} chunks ingérés en {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
