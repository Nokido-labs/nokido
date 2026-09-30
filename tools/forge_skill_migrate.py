#!/usr/bin/env python3
"""forge_skill_migrate.py — migration skills vers la taxonomie souveraine HYBRIDE (24 -> 14).

Taxonomie A (validée user 2026-06-16) : préfixe unifié `forge-*`, fusion des vrais subsets.
  RENAME (dir survivante) : claude-* -> forge-* , nokido -> forge-core , nokido-{models,rescue,
                            skills} -> forge-{…} , forge-veille-approfondie -> forge-veille.
  MERGE  (absorbée -> parent, contenu appendé en section, dir supprimée) :
     nokido-{autonomie,env,hub,route,cognitive-sync,ops} -> forge-core ;
     laforge-quota -> forge-models ; laforge-pipeline + forge-veille-rapide -> forge-veille.
  KEEP   : forge-skill-seekers, forge-anatomy, forge-systematic-debugging, forge-tdd,
           forge-security-scan, forge-android, netcfg-agent.

dry-run par défaut (montre le diff des 7 sites, ne touche rien). --apply (OWNER) exécute le repo-side
(rename dirs + fusion SKILL.md + patch code) et ÉMET les commandes owner (symlinks) + RAG reindex.
Introspecte les vrais emplacements + compte les occurrences code (pas de numéros de ligne).
Réversible : git (repo) + backup .bak (code). Anti-perte : ne supprime une dir absorbée qu'APRÈS
avoir appendé son contenu au parent.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.path.expanduser("~"))

RENAME = {
    "claude-connectors": "forge-connectors",
    "claude-skills-marketplace": "forge-marketplace",
    "laforge": "forge-core",
    "laforge-models": "forge-models",
    "laforge-rescue": "forge-rescue",
    "laforge-skills": "forge-skills",
    "forge-veille-approfondie": "forge-veille",
}
MERGE = {
    "laforge-autonomie": "forge-core", "laforge-env": "forge-core", "laforge-hub": "forge-core",
    "laforge-route": "forge-core", "laforge-cognitive-sync": "forge-core", "laforge-ops": "forge-core",
    "laforge-quota": "forge-models", "laforge-pipeline": "forge-veille",
    "forge-veille-rapide": "forge-veille",
}
NAME_MAP = {**RENAME, **MERGE}                      # old -> final (pour le patch code)
KEEP = {"forge-skill-seekers", "forge-anatomy", "forge-systematic-debugging", "forge-tdd",
        "forge-security-scan", "forge-android", "netcfg-agent"}
CODE_FILES = ["app/forge_skill_policy.py", "app/forge_skill_enricher.py", "tools/forge_skill_sync.py"]
SKILL_ROOTS = [ROOT / "docs" / "skills", HOME / ".claude" / "skills"]


def _find_dir(name: str) -> Path | None:
    for r in SKILL_ROOTS:
        try:
            p = r / name
            if p.exists():
                return p
        except Exception:
            continue
    return None


def _code_occurrences(name: str) -> dict:
    out = {}
    for cf in CODE_FILES:
        p = ROOT / cf
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        n = txt.count(f'"{name}"') + txt.count(f"'{name}'")
        if n:
            out[cf] = n
    return out


def _patch_code(apply: bool) -> list[str]:
    """Remplace les tokens QUOTÉS (longest-first, anti-substring 'nokido' c 'laforge-x')."""
    log = []
    for cf in CODE_FILES:
        p = ROOT / cf
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            log.append(f"  ! {cf}: illisible ({e})")
            continue
        orig = txt
        for old in sorted(NAME_MAP, key=len, reverse=True):
            new = NAME_MAP[old]
            txt = txt.replace(f'"{old}"', f'"{new}"').replace(f"'{old}'", f"'{new}'")
        if txt != orig:
            changed = sum(1 for old in NAME_MAP if (f'"{old}"' in orig or f"'{old}'" in orig))
            log.append(f"  ~ {cf}: {changed} nom(s) remappé(s)")
            if apply:
                p.with_suffix(p.suffix + ".bak").write_text(orig, encoding="utf-8")
                p.write_text(txt, encoding="utf-8")
    return log or ["  (aucune occurrence code)"]


def _fix_frontmatter(skill_dir: Path, new_name: str) -> None:
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return
    txt = md.read_text(encoding="utf-8", errors="replace")
    txt2 = re.sub(r"(?m)^(name:\s*).+$", rf"\g<1>{new_name}", txt, count=1)
    if txt2 != txt:
        md.write_text(txt2, encoding="utf-8")


def _merge_into(parent_dir: Path, absorbed_dir: Path, absorbed_name: str, apply: bool) -> str:
    pmd, amd = parent_dir / "SKILL.md", absorbed_dir / "SKILL.md"
    if not amd.exists():
        return f"  ! {absorbed_name}: SKILL.md absent"
    if apply:
        body = amd.read_text(encoding="utf-8", errors="replace")
        section = f"\n\n## [fusionné depuis {absorbed_name}]\n\n{body}\n"
        with pmd.open("a", encoding="utf-8") as f:
            f.write(section)
    return f"  + {absorbed_name} -> section de {parent_dir.name}/SKILL.md, puis dir supprimée"


def run(apply: bool) -> int:
    print("=" * 70)
    print(f"MIGRATION SKILLS — taxonomie A hybride — {'APPLY' if apply else 'DRY-RUN'}")
    print("=" * 70)

    print("\n[1] RENAME (dir survivante + frontmatter name:)")
    for old, new in RENAME.items():
        d = _find_dir(old)
        loc = str(d.parent) if d else "INTROUVABLE (run en owner pour ~/.claude/skills)"
        print(f"  {old:28} -> {new:18} @ {loc}")
        if apply and d:
            nd = d.parent / new
            if not nd.exists():
                os.rename(d, nd)
                _fix_frontmatter(nd, new)

    print("\n[2] MERGE (absorbée -> parent, contenu appendé, dir supprimée)")
    for old, parent in MERGE.items():
        d = _find_dir(old)
        if not d:
            print(f"  {old:28} -> {parent:18} : dir INTROUVABLE (run en owner)")
            continue
        pdir = d.parent / parent          # parent renommé en [1] (ex nokido->forge-core)
        if not apply:
            print(f"  {old:28} -> section de {parent}/SKILL.md (puis dir supprimée)")
            continue
        if not pdir.exists():
            print(f"  ! {old}: parent {parent} absent (rename [1] d'abord) — SKIP")
            continue
        print(_merge_into(pdir, d, old, apply))
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    print("\n[3] PATCH CODE (tokens quotés, backup .bak)")
    for old in NAME_MAP:
        occ = _code_occurrences(old)
        if occ:
            print(f"  {old:28} -> {NAME_MAP[old]:18} : {occ}")
    for line in _patch_code(apply):
        print(line)

    print("\n[4] OWNER (manuel / `!`) — symlinks + config")
    print("  ~/.claude/skills/<new> -> docs/skills/<new>  (recréer les symlinks renommés)")
    print("  ~/.claude/settings.local.json : MAJ chemins ln -s")
    print("  ~/.gemini/skills (+codex) : re-sync via forge_skill_sync après rename")

    print("\n[5] RAG reindex (chemins source périmés)")
    print('  hub skill action=ingest   (ou rebuild_fts_index) — re-indexe docs/skills renommés')

    print("\n" + ("APPLIQUÉ. Vérifie `git status`, recrée les symlinks owner, reindexe le RAG."
                  if apply else "DRY-RUN. Rien touché. Relance avec --apply (en OWNER) pour exécuter."))
    return 0


if __name__ == "__main__":
    raise SystemExit(run("--apply" in sys.argv[1:]))
