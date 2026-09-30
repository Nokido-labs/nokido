#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Valide les artefacts d'audit contre le validateur du skill Cloudflare.

__FORGE_COLOR__ = 'immunitaire/validation'

POURQUOI CET OUTIL EXISTE
=========================
La campagne d'audit de sécurité porte le skill `cloudflare/security-audit`. Ce skill
n'est pas un paquet de prompts : c'est un cahier des charges d'orchestrateur, et son
contrat machine est `report-schema.json`, interprété par `validate-findings.cjs`.

Mesure du 2026-09-22 : **aucun** run n'était conforme.

    run-1  9 findings   100 erreurs
    run-2  2 findings    34 erreurs      (« 0 erreur » le 2026-09-18 — voir plus bas)
    run-3  structure     1 erreur        ($ : expected array, got object)
    run-4  absent        pas d'artefact
    run-5  absent        pas d'artefact

Le cas de run-2 est le plus instructif : il ÉTAIT valide le 2026-09-18, en
`needs_validation`. Son verdict a ensuite été promu à `confirmed` sans migrer les
champs — `claimed_root_cause`, `blockers` et `validation_plan` appartiennent à
`needs_validation`, tandis que `confirmed` exige `root_cause`, `intended_behavior`,
`conditions`, `execution`, `remediation`, `severity` et `confidence` — et un champ
`validation_result` y a été ajouté, qui n'existe nulle part au schéma.

    UN ARTEFACT VALIDÉ UNE FOIS N'EST PAS UN ARTEFACT VALIDE.

Personne ne s'en est aperçu pendant quatre jours, parce que la validation se lançait
à la main. Un réflexe qui ne vit que dans la session d'un agent disparaît avec elle.
D'où cet outil, et le NR qui l'appelle.

CE QU'IL NE PEUT PAS FAIRE, ET IL LE DIT
========================================
`sandbox/audit/` n'est suivi par AUCUN commit (mesuré le 2026-09-22). En CI, qui
tourne dans un worktree détaché, les runs n'existent donc pas et il n'y a rien à
valider. Le résultat porte alors `runs_trouves: 0`, ce qui est un ÉTAT et non un
succès : l'appelant doit distinguer « tout est conforme » de « je n'ai rien vu ».
Tracker ces artefacts est une décision de l'owner — ce sont des livrables de
sécurité, et un livrable hors revue est exactement ce que la ligne R5 du registre
reproche à un autre script.

Le CLI du validateur est fail-closed sous Windows (les protections POSIX
anti-symlink et anti-FIFO n'y existent pas, 7 de ses 29 tests échouent pour cette
seule raison). On l'appelle donc EN MODULE, jamais par sa ligne de commande.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
AUDIT = RACINE / "sandbox" / "audit"
SKILL = Path("C:/tmp/security-audit-skill/skills/security-audit")

_PONT_JS = """
const fs = require("fs");
const V = require(process.argv[2] + "/validate-findings.cjs");
const schema = JSON.parse(fs.readFileSync(process.argv[2] + "/report-schema.json", "utf8"));
const doc = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const errs = V.validateDocument(doc, schema) || [];
console.log(JSON.stringify({
  n: Array.isArray(doc) ? doc.length : null,
  erreurs: errs.map((e) => (typeof e === "string" ? e : JSON.stringify(e))),
}));
"""

# Le skill a DEUX artefacts, pas un. Ne valider que `findings.json` couvrait la
# moitie du contrat : le ledger de couverture dit ce qui a ete REGARDE, et c'est
# lui qui empeche de confondre « rien trouve » avec « rien cherche ».
# Son validateur n'attend PAS de schema en second argument (contrairement a celui
# des findings) — mesure faite sur sa signature reelle, pas deduite.
_PONT_LEDGER_JS = """
const fs = require("fs");
const V = require(process.argv[2] + "/validate-coverage-ledger.cjs");
const doc = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const errs = V.validateDocument(doc) || [];
console.log(JSON.stringify({
  n: Array.isArray(doc) ? doc.length : null,
  erreurs: errs.map((e) => (typeof e === "string" ? e : JSON.stringify(e))),
}));
"""


def outillage_disponible() -> tuple[bool, str]:
    """Trois états, jamais deux : utilisable, ou la RAISON précise de ne pas l'être."""
    if shutil.which("node") is None:
        return False, "node absent du PATH"
    if not SKILL.is_dir():
        return False, f"clone du skill absent : {SKILL}"
    for f in ("validate-findings.cjs", "report-schema.json", "validate-coverage-ledger.cjs"):
        if not (SKILL / f).is_file():
            return False, f"{f} absent du clone du skill"
    return True, "ok"


def valider_fichier(chemin: Path, pont_js: str = _PONT_JS) -> dict:
    """Rend {'n': nb_entrees|None, 'erreurs': [...]} ou {'illisible': raison}."""
    ok, raison = outillage_disponible()
    if not ok:
        return {"illisible": raison}
    with tempfile.TemporaryDirectory() as tmp:
        pont = Path(tmp) / "pont.cjs"
        pont.write_text(pont_js, encoding="utf-8")
        try:
            r = subprocess.run(
                ["node", str(pont), str(SKILL), str(chemin)],
                capture_output=True, text=True, errors="replace", timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as e:
            return {"illisible": f"node injoignable : {e}"}
    if r.returncode != 0:
        return {"illisible": f"node rc={r.returncode} : {(r.stderr or '').strip()[:300]}"}
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as e:
        return {"illisible": f"sortie du pont non lisible : {e}"}


def recenser(audit: Path | None = None) -> dict:
    """Valide chaque run-*/findings.json. Un run SANS artefact est compté à part :
    absent n'est pas conforme, et le silence n'est pas un succès."""
    audit = Path(audit or AUDIT)
    res = {"runs": {}, "sans_artefact": [], "illisibles": {}, "total_erreurs": 0,
           "ledgers": {}, "sans_ledger": [], "total_erreurs_ledger": 0}
    if not audit.is_dir():
        res["racine_absente"] = str(audit)
        return res
    for d in sorted(p for p in audit.iterdir() if p.is_dir() and p.name.startswith("run-")):
        led = d / "coverage-ledger.json"
        if led.is_file():
            vl = valider_fichier(led, _PONT_LEDGER_JS)
            if "illisible" in vl:
                res["illisibles"][f"{d.name}/ledger"] = vl["illisible"]
            else:
                res["ledgers"][d.name] = {"unites": vl.get("n"), "erreurs": vl.get("erreurs", [])}
                res["total_erreurs_ledger"] += len(vl.get("erreurs", []))
        else:
            # Un run sans ledger a peut-etre tout trouve, ou n'a rien cherche.
            # Les deux se lisent pareil sans lui : c'est pour cela qu'on le compte.
            res["sans_ledger"].append(d.name)
        f = d / "findings.json"
        if not f.is_file():
            res["sans_artefact"].append(d.name)
            continue
        v = valider_fichier(f)
        if "illisible" in v:
            res["illisibles"][d.name] = v["illisible"]
            continue
        res["runs"][d.name] = {"findings": v.get("n"), "erreurs": v.get("erreurs", [])}
        res["total_erreurs"] += len(v.get("erreurs", []))
    return res


def main() -> int:
    res = recenser()
    if res.get("racine_absente"):
        print(f"AUCUN repertoire d'audit : {res['racine_absente']} — rien valide, pas conforme")
        return 0
    for nom, v in res["runs"].items():
        print(f"{nom} : {v['findings']} finding(s), {len(v['erreurs'])} erreur(s)")
        for e in v["erreurs"][:6]:
            print(f"    - {e}")
        if len(v["erreurs"]) > 6:
            print(f"    ... {len(v['erreurs']) - 6} ecartees par la borne (presentes)")
    for nom in res["sans_artefact"]:
        print(f"{nom} : PAS DE findings.json — non couvert, pas conforme")
    for nom, v in res.get("ledgers", {}).items():
        print(f"{nom} : ledger {v['unites']} unite(s), {len(v['erreurs'])} erreur(s)")
        for e in v["erreurs"][:4]:
            print(f"    - {e}")
        if len(v["erreurs"]) > 4:
            print(f"    ... {len(v['erreurs']) - 4} ecartees par la borne (presentes)")
    for nom in res.get("sans_ledger", []):
        print(f"{nom} : PAS DE coverage-ledger.json — on ne sait pas ce qui a ete REGARDE")
    for nom, r in res["illisibles"].items():
        print(f"{nom} : ILLISIBLE — {r}")
    print(
        f"\nTOTAL findings : {res['total_erreurs']} erreur(s) sur {len(res['runs'])} run(s) "
        f"valide(s), {len(res['sans_artefact'])} sans artefact, {len(res['illisibles'])} illisible(s)"
    )
    print(
        f"TOTAL ledgers  : {res['total_erreurs_ledger']} erreur(s) sur "
        f"{len(res.get('ledgers', {}))} ledger(s), {len(res.get('sans_ledger', []))} run(s) sans ledger"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
