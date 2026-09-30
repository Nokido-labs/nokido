#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_test_coverage_matrix.py - la matrice qui RATTRAPE : couche x classe d'entree.

POURQUOI. Le wiki 07 declare 10 couches defensives. La suite de tests en couvre
deja une partie (17 fichiers de garde, 85 pytest.raises au 2026-08-27), mais
personne ne sait QUELLE couche resiste a QUELLE classe d'entree hostile. Une
checklist tenue a la main devient fausse au premier service ajoute ; celle-ci se
REGENERE et rougit la CI tant qu'une case reste a decouvert. Ce n'est plus une
liste qu'on suit, c'est une liste qui nous rattrape (methode owner 2026-08-27).

CE QU'ELLE FAIT. Pour chaque (couche, classe d'entree), elle cherche dans tests/
un test qui EXERCE cette classe sur cette couche -- par les modules qu'il importe
et par les marqueurs de la classe dans son corps. Elle ne JUGE pas la qualite du
test (c'est pytest qui l'execute) : elle mesure la COUVERTURE, le trou avant le bug.

CE QU'ELLE N'EST PAS. Elle ne contient AUCUN payload : elle detecte des MARQUEURS
de classe dans le code de test (un nom de variable, un import, un motif), jamais un
vecteur d'attaque. Le contenu hostile vit dans les fixtures des tests, hashe, hors
de cet outil et hors de tout prompt.

TROIS ETATS par case, jamais deux :
  COUVERT     un test importe la couche ET porte les marqueurs de la classe.
  DECOUVERT   la couche est testee, mais aucune trace de cette classe. Le trou.
  SANS_TEST   aucun test n'importe cette couche du tout. Trou plus grave.

CLI :
    LAFORGE_PYTHON tools/forge_test_coverage_matrix.py            # matrice lisible
    LAFORGE_PYTHON tools/forge_test_coverage_matrix.py --json
    LAFORGE_PYTHON tools/forge_test_coverage_matrix.py --gate     # rc=1 si un trou
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/couverture-defensive"

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

COUVERT, DECOUVERT, SANS_TEST = "COUVERT", "DECOUVERT", "SANS_TEST"

# Les 10 couches du wiki 07 -> les modules qui les portent. Un test « couvre » une
# couche s'il importe l'un de ces modules (nom present dans le fichier). Les noms
# sont ceux du code reel, pas de la prose.
COUCHES = [
    ("1. Semantic Firewall", ["forge_semantic_firewall"]),
    ("2. Sovereign Membrane", ["forge_sovereign_membrane"]),
    ("3. 6-ring RBAC", ["forge_integrity", "forge_videur", "intention_gate"]),
    ("4. Vault", ["forge_machine_vault", "forge_secrets", "forge_env_crypt"]),
    ("5. Pre-commit secret scan", ["forge_secret_guard"]),
    ("6. Bash guard", ["bash_guard", "run_guard"]),
    ("6b. Commit gate", ["forge_git_gate"]),
    ("7. Ephemeral sandboxing", ["forge_sandbox_exec", "forge_exec_tier"]),
    ("8. Local-first / egress ring", ["forge_tool_gate", "exec_tier"]),
    ("9. Log DLP at rest", ["forge_conv_sanitizer", "forge_log_retention", "conv_dlp"]),
    ("10. Web egress firewall", ["forge_web_egress", "egress"]),
]

# Les 4 classes d'entree hostile (methode owner). Chaque classe = un jeu de MARQUEURS
# qu'un test qui l'exerce laisse forcement dans son code. Aucun vecteur ici, juste la
# signature d'un test qui s'en occupe.
CLASSES = [
    ("injection", re.compile(
        r"inject|prompt.?guard|canary|traversal|\.\./|sanitiz|redact|detect_injection|"
        r"jailbreak|ssrf|beacon", re.I)),
    ("types_json", re.compile(
        r"isinstance|type\s*error|typeerror|malformed|not\s+a\s+(dict|int|str)|"
        r"wrong.?type|coerc|schema.*valid|pydantic|validationerror|\bNone\b.*expect", re.I)),
    ("limite", re.compile(
        r"oversize|too.?(long|large|big)|max.?len|boundary|truncat|\*\s*\d{3,}|"
        r"len\([^)]{0,30}\)\s*[<>]=?\s*\d{3,}|10000|huge|overflow", re.I)),
    ("concurrence", re.compile(
        r"gather|threadpool|concurrent|asyncio|\brace\b|parallel|simultan|"
        r"lock|contention|busy_timeout|database is locked", re.I)),
]


def _tests_par_couche() -> dict[str, list[Path]]:
    """Pour chaque couche, la liste des fichiers de test qui l'importent/la nomment."""
    fichiers = sorted(TESTS.rglob("test_*.py")) if TESTS.exists() else []
    corpus = [(p, p.read_text(encoding="utf-8", errors="replace")) for p in fichiers]
    res: dict[str, list[Path]] = {}
    for nom, mods in COUCHES:
        hits = [p for p, txt in corpus if any(m.lower() in txt.lower() for m in mods)]
        res[nom] = hits
    return res


def calculer() -> dict:
    """La matrice : pour chaque couche x classe, un des trois etats."""
    par_couche = _tests_par_couche()
    lignes = []
    for nom, _mods in COUCHES:
        tests = par_couche[nom]
        if not tests:
            cells = {cl: SANS_TEST for cl, _ in CLASSES}
            lignes.append({"couche": nom, "n_tests": 0, "cells": cells})
            continue
        blob = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in tests)
        cells = {}
        for cl, motif in CLASSES:
            cells[cl] = COUVERT if motif.search(blob) else DECOUVERT
        lignes.append({"couche": nom, "n_tests": len(tests),
                       "fichiers": [p.name for p in tests], "cells": cells})
    trous = sum(1 for l in lignes for v in l["cells"].values() if v != COUVERT)
    return {"classes": [c for c, _ in CLASSES], "lignes": lignes,
            "trous": trous, "cases": len(COUCHES) * len(CLASSES)}


_SIGLE = {COUVERT: "OK ", DECOUVERT: " . ", SANS_TEST: " - "}


def _markdown(m: dict) -> str:
    classes = m["classes"]
    out = ["# Matrice de couverture defensive - couche x classe d'entree", "",
           f"**{m['cases'] - m['trous']}/{m['cases']} cases couvertes** "
           f"- {m['trous']} trous. `OK`=couvert, `.`=decouvert (couche testee, classe non), "
           f"`-`=sans test.", ""]
    entete = "| Couche | " + " | ".join(classes) + " | tests |"
    sep = "|" + "---|" * (len(classes) + 2)
    out += [entete, sep]
    for l in m["lignes"]:
        cells = " | ".join(_SIGLE[l["cells"][c]].strip() for c in classes)
        out.append(f"| {l['couche']} | {cells} | {l['n_tests']} |")
    out += ["", "## Trous a combler (ordre : SANS_TEST d'abord)", ""]
    ranked = sorted(
        ((l["couche"], c) for l in m["lignes"] for c in classes if l["cells"][c] != COUVERT),
        key=lambda x: 0 if next(li for li in m["lignes"] if li["couche"] == x[0])["cells"][x[1]] == SANS_TEST else 1,
    )
    for couche, c in ranked:
        etat = next(li for li in m["lignes"] if li["couche"] == couche)["cells"][c]
        out.append(f"- [{etat}] **{couche}** x `{c}`")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Matrice de couverture couche x classe d'entree hostile")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate", action="store_true", help="rc=1 s'il reste un trou")
    ap.add_argument("--out", default=str(ROOT / "sandbox" / "workspace"))
    args = ap.parse_args()

    m = calculer()
    dst = Path(args.out)
    try:
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "test_coverage_matrix.md").write_text(_markdown(m), encoding="utf-8")
    except Exception:  # noqa: BLE001  # muet-ok : l'ecriture d'artefact ne doit pas casser le gate
        pass
    print(json.dumps(m, ensure_ascii=False) if args.json else _markdown(m))
    return 1 if (args.gate and m["trous"]) else 0


if __name__ == "__main__":
    sys.exit(main())
