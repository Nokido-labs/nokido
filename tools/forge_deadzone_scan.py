"""forge_deadzone_scan — audit des ZONES MORTES du joignable (skills/hooks).

Politique owner : « plus de zones mortes dans les outils joignables, skills, hooks, tools,
agents ». Ce scanner statique trouve les candidats : skills avec une SECTION backlog réelle
(header "## ... à créer / next-step / to build"), références `forge_*.py` manquantes NON
citées comme leçon, hooks pointant un script absent.

Heuristique affinée (anti faux-positif) :
- DEAD  = présence d'un HEADER markdown de backlog (section dédiée "modules à créer") = vraie
  dette de câblage. Les simples mentions prose (POC/TODO/stub) ne suffisent PAS (→ SUSPECT).
- BROKEN_REF = module `forge_x.py` référencé mais absent ET pas dans un contexte « leçon »
  (supprimé/exemple/cité/jamais) — ex: `forge_pii_detector` est cité comme leçon anti-dup, pas
  une dépendance cassée.
- SUSPECT = signaux prose faibles seulement (à vérifier à la main).

Usage : LAFORGE_PYTHON tools/forge_deadzone_scan.py [--json out.json]
Importable : from forge_deadzone_scan import scan
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/audit : zones mortes du joignable (skills, hooks)"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
TOOLS = ROOT / "tools"

HEADER_BACKLOG = re.compile(
    r"^#{1,5}\s+.*(à\s+cr[ée]er|a\s+creer|à\s+coder|à\s+écrire|next[- ]step|to\s+(?:create|build|wire))",
    re.IGNORECASE | re.MULTILINE,
)
WEAK_SIG = re.compile(r"\b(POC|TODO|STUB|pas\s+câbl|not\s+wired|jamais\s+câbl)\b", re.IGNORECASE)
MODREF = re.compile(r"\b(forge_[a-z0-9_]+)\.py\b")
CAUTION = re.compile(r"(supprim|delet|exemple|perdu|cit[ée]|jamais|référence|reference|leçon|lesson)",
                     re.IGNORECASE)


def _exists_module(name: str) -> bool:
    return (APP / f"{name}.py").exists() or (TOOLS / f"{name}.py").exists()


def _is_cautionary(txt: str, mod: str) -> bool:
    """Le module manquant est-il cité comme LEÇON/exemple (pas une vraie dépendance) ?"""
    for m in re.finditer(re.escape(mod), txt):
        a, b = max(0, m.start() - 130), m.end() + 130
        if not CAUTION.search(txt[a:b]):
            return False  # au moins une mention HORS contexte leçon = vraie réf
    return True  # toutes les mentions sont en contexte leçon


def scan_skills() -> list:
    out = []
    for md in sorted((ROOT / "docs" / "skills").glob("*/SKILL.md")):
        try:
            txt = md.read_text(encoding="utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            out.append({"skill": md.parent.name, "error": repr(e)})
            continue
        backlog = sorted({h.group(0).strip()[:80] for h in HEADER_BACKLOG.finditer(txt)})
        refs = sorted({m.group(1) for m in MODREF.finditer(txt)})
        missing = [r for r in refs if not _exists_module(r)]
        real_missing = [r for r in missing if not _is_cautionary(txt, r)]
        cautionary = [r for r in missing if r not in real_missing]
        weak = sorted({m.group(1).lower() for m in WEAK_SIG.finditer(txt)})
        if backlog:
            verdict = "DEAD"          # section backlog dédiée = vraie dette
        elif real_missing:
            verdict = "BROKEN_REF"    # dépendance absente non-leçon
        elif weak:
            verdict = "SUSPECT"       # signaux prose faibles -> vérifier
        else:
            verdict = "live"
        out.append({
            "skill": md.parent.name, "verdict": verdict,
            "backlog_headers": backlog, "real_missing": real_missing,
            "cautionary_refs": cautionary, "weak_signals": weak,
        })
    return out


def scan_hooks() -> list:
    out = []
    for cfg in (Path.home() / ".gemini" / "settings.json", Path.home() / ".claude" / "settings.json"):
        try:
            if not cfg.exists():
                continue
            data = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:  # noqa: BLE001  (sandbox = WinError5 sur home)
            out.append({"config": str(cfg), "error": repr(e)})
            continue
        for ev, blocks in (data.get("hooks") or {}).items():
            for blk in blocks if isinstance(blocks, list) else []:
                for h in (blk.get("hooks") or []):
                    script = next((a for a in (h.get("args") or []) if str(a).endswith(".py")), None)
                    if script:
                        out.append({"config": cfg.name, "event": ev, "script": script,
                                    "exists": Path(script).exists()})
    return out


def scan() -> dict:
    sk = scan_skills()
    return {
        "skills": sk,
        "hooks": scan_hooks(),
        "summary": {
            "skills_total": len(sk),
            "DEAD": [s["skill"] for s in sk if s.get("verdict") == "DEAD"],
            "BROKEN_REF": [s["skill"] for s in sk if s.get("verdict") == "BROKEN_REF"],
            "SUSPECT": [s["skill"] for s in sk if s.get("verdict") == "SUSPECT"],
            "live": sum(1 for s in sk if s.get("verdict") == "live"),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    rep = scan()
    if args.json:
        Path(args.json).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
