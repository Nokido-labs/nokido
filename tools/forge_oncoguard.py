"""forge_oncoguard — skill_promotion_review (p53 / suppresseur de tumeur).

Garde anti-scheming sur l'auto-promotion de skills (forge_skill_curator.consolidate).
Le success_rate BRUT est un proxy GAMEABLE : un skill 2/2 sur du trivial = 100% mais
non significatif (le biais p_success de l'audit Goodhart). p53 : un skill ne se promeut
que si son succes est STATISTIQUEMENT SIGNIFICATIF (Wilson lower bound, pas le raw rate)
+ un minimum d'echantillons. Invariant P0 : skill_promotion_review. 0 dependance.

Selftest : LAFORGE_PYTHON tools/forge_oncoguard.py
"""
from __future__ import annotations
import math

MIN_USES = 5
WILSON_FLOOR = 0.6  # borne basse de confiance requise pour promouvoir
_Z = 1.96           # 95%


def wilson_lower(successes: int, n: int, z: float = _Z) -> float:
    """Borne basse de l'intervalle de Wilson : penalise les petits echantillons
    (2/2 -> ~0.34, pas 1.0). Anti-gaming du raw success_rate."""
    if n <= 0:
        return 0.0
    phat = successes / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def review_skill(uses: int, successes: int, min_uses: int = MIN_USES,
                 floor: float = WILSON_FLOOR) -> dict:
    """p53 : promouvoir un skill SEULEMENT si succes statistiquement significatif.
    Retourne {promote, wilson, reason}."""
    if uses < min_uses:
        return {"promote": False, "wilson": 0.0,
                "reason": f"echantillon insuffisant ({uses} < {min_uses})"}
    wl = wilson_lower(successes, uses)
    if wl < floor:
        return {"promote": False, "wilson": round(wl, 3),
                "reason": f"Wilson lower {wl:.2f} < floor {floor} (succes non significatif / proxy gameable)"}
    return {"promote": True, "wilson": round(wl, 3), "reason": "ok (significatif)"}


def selftest() -> bool:
    cases = [
        (2, 2, False),     # 100% mais 2 essais -> rejete (trivial gameable)
        (3, 3, False),     # 100% mais < min_uses
        (22, 20, True),    # 91% sur 22 -> Wilson ~0.72 -> promu
        (50, 30, False),   # 60% sur 50 -> Wilson ~0.46 -> rejete
        (100, 95, True),   # 95% sur 100 -> promu
    ]
    allok = True
    for uses, succ, expect in cases:
        r = review_skill(uses, succ)
        v = "OK " if r["promote"] == expect else "FAIL"
        if r["promote"] != expect:
            allok = False
        print(f"  [{v}] {succ}/{uses} (raw {succ/uses:.0%}) -> promote={r['promote']!s:5} "
              f"wilson={r['wilson']} ({r['reason'][:38]})")
    print("SKILL_PROMOTION_REVIEW (p53):", "PASS" if allok else "FAIL")
    return allok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
