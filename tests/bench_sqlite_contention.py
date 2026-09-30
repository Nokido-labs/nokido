# -*- coding: utf-8 -*-
"""
bench_sqlite_contention.py — Mesure de la contention SQLite en mode WAL
Cible : Ryzen 8700G (8 cœurs / 16 threads)
"""

import sqlite3
import threading
import time
import os
from pathlib import Path

DB_PATH = Path("bench_contention.db")
NUM_THREADS = 16
WRITES_PER_THREAD = 200

def setup_db():
    if DB_PATH.exists():
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS bench (id INTEGER PRIMARY KEY, val TEXT, thread_id INTEGER, ts REAL)")
    conn.commit()
    conn.close()

def worker(thread_id, results):
    errors = 0
    start = time.time()
    conn = sqlite3.connect(DB_PATH, timeout=0.01) # 5s timeout pour limiter les BUSY immédiats
    conn.execute("PRAGMA journal_mode=WAL")
    
    for i in range(WRITES_PER_THREAD):
        try:
            conn.execute("INSERT INTO bench (val, thread_id, ts) VALUES (?, ?, ?)", 
                         (f"data_{i}", thread_id, time.time()))
            conn.commit()
        except sqlite3.OperationalError as e:
            if "locked" in str(e):
                errors += 1
        except Exception:
            errors += 1
            
    conn.close()
    results[thread_id] = {
        "time": time.time() - start,
        "errors": errors
    }

def run_bench():
    print(f"--- Benchmark SQLite Contention ({NUM_THREADS} threads) ---")
    setup_db()
    
    threads = []
    results = {}
    
    global_start = time.time()
    for i in range(NUM_THREADS):
        t = threading.Thread(target=worker, args=(i, results))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
    
    duration = time.time() - global_start
    total_errors = sum(r["errors"] for r in results.values())
    avg_thread_time = sum(r["time"] for r in results.values()) / NUM_THREADS
    
    print(f"Durée totale : {duration:.4f}s")
    print(f"Erreurs 'database is locked' : {total_errors}")
    print(f"Temps moyen par thread : {avg_thread_time:.4f}s")
    print(f"Débit : { (NUM_THREADS * WRITES_PER_THREAD) / duration:.2f} writes/s")
    
    if DB_PATH.exists():
        os.remove(DB_PATH)
        for suffix in ["-wal", "-shm"]:
            p = Path(str(DB_PATH) + suffix)
            if p.exists(): os.remove(p)

if __name__ == "__main__":
    run_bench()
