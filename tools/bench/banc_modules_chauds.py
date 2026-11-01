"""S1 migration bas niveau (item roadmap_p2_rust_wasm_cible_20261016) : MESURER les modules candidats au WASM/Rust
avant toute migration. Entrees SYNTHETIQUES, aucune base reelle, aucun reseau.

Signatures lues le 30/10 :
  app/forge_secret_guard.py  def scan_outbound(prompt, provider, local_only)   (leve SecretLeakBlocked si secret)
  app/forge_trust_score.py   class TrustScoreRegistry : record_success(provider, ttft_ms), best_provider(candidates)
  app/forge_rag_janitor.py   ABSENT : aucune deduplication cosinus (seulement clean_orphans, purge_old_logs,
                             purge_old_snapshots, get_noise_report) -- le « dedup cosine 0.97 » de docs/WASM_PLAN.md
                             n'est pas implemente : rien a migrer.
Sortie : « fonction | taille | mediane ms | pic Mo » par mesure, derniere ligne « BILAN banc_modules_chauds ».
Lecture : une migration n'a de sens que si la mediane pese face au cout de l'appel qui l'entoure (un appel LLM =
des centaines de ms).
"""
from __future__ import annotations

import random
import statistics
import string
import sys
import time
import tracemalloc
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REPETITIONS = 30


def mesurer(nom: str, taille: str, fn) -> None:
    tracemalloc.start()
    temps = []
    for _ in range(REPETITIONS):
        t0 = time.perf_counter()
        fn()
        temps.append((time.perf_counter() - t0) * 1000)
    pic = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
    tracemalloc.stop()
    print("%s | %s | %.3f ms | %.2f Mo" % (nom, taille, statistics.median(temps), pic), flush=True)


def texte_sans_secret(n: int, rng: random.Random) -> str:
    mots = ["".join(rng.choices(string.ascii_lowercase, k=rng.randint(2, 9))) for _ in range(n // 6)]
    return " ".join(mots)[:n]


def banc_secret_guard(rng: random.Random) -> None:
    try:
        from forge_secret_guard import scan_outbound
    except Exception as e:  # noqa: BLE001 - module illisible : DIT, pas de mesure inventee
        print("scan_outbound | ILLISIBLE | %s: %s" % (type(e).__name__, e))
        return
    for n in (2_000, 20_000, 200_000):
        texte = texte_sans_secret(n, rng)
        mesurer("scan_outbound", "%d o" % n, lambda t=texte: scan_outbound(t, "groq", False))


def banc_trust_score() -> None:
    try:
        from forge_trust_score import TrustScoreRegistry
    except Exception as e:  # noqa: BLE001
        print("TrustScoreRegistry | ILLISIBLE | %s: %s" % (type(e).__name__, e))
        return
    reg = TrustScoreRegistry()
    candidats = ["prov_%d" % i for i in range(30)]
    for i in range(1000):
        reg.record_success(candidats[i % 30], 50.0 + i % 400)
    mesurer("best_provider", "30 candidats", lambda: reg.best_provider(candidats))
    mesurer("record_success", "1 appel", lambda: reg.record_success("prov_1", 120.0))


if __name__ == "__main__":
    graine = random.Random(30)
    banc_secret_guard(graine)
    banc_trust_score()
    print("rag_janitor dedup cosinus | ABSENT | non implemente dans app/forge_rag_janitor.py (docs/WASM_PLAN.md)")
    print("BILAN banc_modules_chauds")
