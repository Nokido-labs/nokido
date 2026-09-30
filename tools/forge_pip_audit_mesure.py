# -*- coding: utf-8 -*-
"""Produit un rapport pip-audit DATE, la ou le reseau existe.

__FORGE_COLOR__ = "qualite/build : mesure deportee de la chaine d approvisionnement"

POURQUOI CE MODULE (2026-09-07). Le gate `pip-audit` de `ci_local` tourne sous le
compte de la CI, qui n'a PAS d'egress : `pypi.org` rend `WinError 10013`, l'audit meurt
en 1,3 s sans lire un paquet, et le gate etant `warn` son rc non nul s'affichait ✅.
Un domaine declare CRITIQUE n'avait donc AUCUN verdict depuis toujours.

⚠️ Et il n'existe AUCUN suppleant : `.github/workflows/ci-selfhosted.yml` INSTALLE
pip-audit (`pip install ... pip-audit`, ligne 93) et ne le LANCE jamais. La chaine
d'approvisionnement n'etait auditee nulle part.

La separation est donc : **ce script MESURE** (lance via `run_job online=true`, le seul
compte avec egress) et **le gate JUGE** la fraicheur de ce qu'il trouve. Le producteur
ecrit la ou `forge_deps_reconcilier.rapport_courant()` cherche deja -- on reutilise sa
selection du plus recent, corrigee le 2026-09-07, au lieu d'en ecrire une seconde.

🔑 **REGLE ABSOLUE : ne JAMAIS ecrire de rapport quand la mesure a echoue.** Un fichier
frais et vide se relirait comme « aucune vulnerabilite », et fabriquerait exactement le
faux calme que ce chantier supprime. Un echec sort en rc non nul, sans fichier.

    LAFORGE_PYTHON tools/forge_pip_audit_mesure.py        (via run_job online=true)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / "sandbox"
CACHE = SANDBOX / "pip_audit_cache"

# Marqueurs de NON-MESURE, identiques a ceux que `ci_local` lit dans la sortie du
# gate : une seule definition du symptome, deux lecteurs.
MOTIFS_NON_MESURE = (
    "NewConnectionError",
    "Max retries exceeded",
    "Failed to establish a new connection",
    "requests.exceptions.ConnectionError",
    "Failed to read from cache directory",
)


def enveloppe_meta(deps) -> dict:
    """Ce rapport est la propriete de QUEL environnement — et de combien.

    ⚠️ `OBSERVED(X) != PROPERTY_OF(X)`. Un rapport anonyme se lit comme « les
    dependances », alors qu'il ne decrit que CELLES D'UN interpreteur. Mesure du
    2026-09-20 : les `run_job` s'executent sous `miniforge3/envs/laforge_py314`
    (preuve dans le wrapper genere du job), donc cette mesure decrit la CI :

        laforge_py314 (CI)   226 paquets audites,  1 a 5 touches
        miniforge3    (hub)  835 paquets audites, 66 touches

    609 paquets de l'environnement qui fait tourner le corps n'etaient audites
    par personne, et le gate acceptait ce rapport en suppleant en jugeant sa
    FRAICHEUR et jamais sa PORTEE.

    Nommer ne corrige pas la portee. Mais une portee anonyme ne peut meme pas
    etre jugee : c'est le prealable.
    """
    deps = list(deps or [])
    touches = [d for d in deps if isinstance(d, dict) and d.get("vulns")]
    return {
        "interpreteur": sys.executable,
        "n_paquets_audites": len(deps),
        "n_paquets_touches": len(touches),
        "n_avis": sum(len(d.get("vulns") or []) for d in touches),
        # Un perimetre vide n'est pas « rien a signaler » : c'est un instrument
        # aveugle, et il doit se NOMMER tel plutot que de rendre un zero
        # rassurant que le gate lirait comme un succes.
        "portee": "AUCUNE" if not deps else "ENVIRONNEMENT_DE_CET_INTERPRETEUR",
    }


def _sortie(cible: Path) -> list:
    """Lance pip-audit en JSON. Rend (rc, texte_brut)."""
    cmd = [sys.executable, "-m", "pip_audit", "--progress-spinner=off",
           "--cache-dir", str(CACHE), "--format", "json", "--output", str(cible)]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       errors="replace", timeout=1800)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sortie", default=None,
                    help="chemin du rapport (defaut : sandbox/pip_audit_<date>.json)")
    a = ap.parse_args(argv)

    try:
        CACHE.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print("[audit] cache non creable (%s) : pip-audit le dira lui-meme"
              % type(e).__name__)

    jour = _dt.date.today().isoformat()
    cible = Path(a.sortie) if a.sortie else SANDBOX / ("pip_audit_%s.json" % jour)
    # pip-audit tourne avec cwd=ROOT : un chemin relatif DOIT se resoudre contre le depot, sinon
    # `provisoire.exists()` le cherche dans le cwd de l'appelant (le circadien), rend « aucun
    # fichier » sur une mesure reussie et laisse un .partiel parasite (mesure du 2026-09-26).
    if not cible.is_absolute():
        cible = ROOT / cible
    # On ecrit d'abord a cote, et on ne PUBLIE le nom definitif qu'apres avoir
    # verifie que la mesure a eu lieu : un rapport partiel portant le nom attendu
    # serait lu comme une mesure valide par tout consommateur.
    provisoire = cible.with_suffix(".partiel")

    rc, texte = _sortie(provisoire)
    motif = next((m for m in MOTIFS_NON_MESURE if m in texte), None)

    if motif:
        print("[audit] NON MESURE : %s" % motif)
        print("        aucun rapport ecrit -- un fichier frais et vide se relirait "
              "comme « aucune vulnerabilite »")
        print("        ce compte a-t-il l'egress ? relancer en `run_job online=true`")
        provisoire.unlink(missing_ok=True)
        return 2

    if not provisoire.exists():
        print("[audit] NON MESURE : pip-audit n'a produit aucun fichier (rc=%s)" % rc)
        print("        derniere sortie : %s" % texte.strip()[-300:])
        return 2

    try:
        donnees = json.loads(provisoire.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print("[audit] NON MESURE : rapport illisible (%s)" % type(e).__name__)
        provisoire.unlink(missing_ok=True)
        return 2

    deps = donnees.get("dependencies") if isinstance(donnees, dict) else donnees
    n_paquets = len(deps or [])
    if n_paquets == 0:
        # Zero paquet n'est pas « rien a signaler » : c'est un audit qui n'a rien lu.
        print("[audit] NON MESURE : 0 paquet audite -- ce n'est pas un depot sain, "
              "c'est un instrument aveugle")
        provisoire.unlink(missing_ok=True)
        return 2

    n_vulns = sum(len(d.get("vulns") or []) for d in deps if isinstance(d, dict))

    # L'enveloppe voyage AVEC les donnees : un rapport separe de sa portee se
    # retrouve tot ou tard lu sans elle. La cle est prefixee pour ne pas entrer
    # en collision avec le schema de pip-audit, et les consommateurs existants
    # lisent `dependencies` : ils ne voient pas la difference.
    meta = enveloppe_meta(deps)
    if isinstance(donnees, dict):
        donnees["_nokido_meta"] = meta
        try:
            provisoire.write_text(
                json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            print("[audit] enveloppe NON ecrite (%s) — le rapport reste "
                  "anonyme, sa portee devra etre deduite" % type(e).__name__)

    provisoire.replace(cible)
    print("[audit] MESURE : %d paquet(s) audite(s), %d vulnerabilite(s)"
          % (n_paquets, n_vulns))
    print("        interpreteur : %s" % meta["interpreteur"])
    print("        ⚠ cette mesure decrit CET environnement et aucun autre ; "
          "le hub peut tourner sous un interpreteur different")
    print("        rapport : %s" % cible)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
