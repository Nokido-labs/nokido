"""forge_suite_pure_triage.py - qui, parmi les tests exclus, pourrait rentrer ?

POURQUOI. 82 fichiers de tests NR sont hors de `PURE_TESTS` (tools/ci_local.py),
donc hors CI. Le cliquet `test_suite_pure_ratchet_nr` a GELE cette dette pour
qu'elle n'enfle plus ; il ne la solde pas. Ce module la trie.

METHODE : ANALYSE STATIQUE, AUCUNE EXECUTION. Lancer 82 fichiers pour voir
lesquels passent reveillerait des services, ouvrirait des ports et lirait la
vraie base RAG -- c'est-a-dire exactement ce que la regle « zero service
externe » interdit, et un moyen sur de tuer le hub. On lit donc le SOURCE et on
cherche les marqueurs d'impurete. Le verdict est une PRESOMPTION, pas une
preuve : `CANDIDAT` veut dire « aucune raison visible de l'exclure », et cette
nuance est ecrite dans la sortie plutot que gommee.

    LAFORGE_PYTHON tools/forge_suite_pure_triage.py
    LAFORGE_PYTHON tools/forge_suite_pure_triage.py --json
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/tests : qui parmi les tests exclus pourrait rentrer dans PURE_TEST"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NR = ROOT / "tests" / "nr"
SOCLE = NR / "_socle_suite_pure.json"

# Marqueurs d'IMPURETE. Chacun nomme ce qu'il attrape : un tri dont on ne peut
# pas relire le motif se conteste, et se contourne.
_MARQUEURS = (
    (r"\brequests\b|\bhttpx\b|urllib\.request\.urlopen|aiohttp",
     "sort sur le reseau"),
    (r"\bsocket\.(socket|create_connection)\b", "ouvre une socket"),
    # Les ports NUS comptent aussi : `PORT = 11434` vise Ollama aussi surement
    # que `:11434`. Ces numeros sont assez specifiques pour ne pas ramasser
    # n'importe quel entier (mesure 2026-08-20, le test l'a montre).
    (r"localhost:\d|127\.0\.0\.1:\d|"
     r"(?::|\b)(?:8765|8766|8767|11434|8099|8100|7400|7401|1234|6333|5557|7779)\b",
     "vise un service local par son port"),
    (r"\bdb_path\s*\(|embeddings\.db|rag_chunks", "lit la vraie base RAG"),
    (r"subprocess\.(run|Popen|check_output)", "lance un sous-processus"),
    (r"\bdocker\b|\bnssm\b", "pilote docker ou un service Windows"),
    (r"\bollama\b|\bLM ?Studio\b|llama_?cpp", "sollicite un backend LLM"),
    (r"@pytest\.mark\.(integration|slow|network)", "marque integration/slow/network"),
)


def _marqueurs(src: str) -> list[str]:
    trouves = []
    for motif, motif_nom in _MARQUEURS:
        if re.search(motif, src, re.I):
            trouves.append(motif_nom)
    return trouves


def _compte_tests(src: str) -> int:
    """Nombre de fonctions de test, pour chiffrer ce que la dette coute."""
    try:
        arbre = ast.parse(src)
    except SyntaxError:
        return 0
    return sum(1 for n in ast.walk(arbre)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name.startswith("test_"))


def trier() -> dict:
    if not SOCLE.exists():
        return {"ARRET": "socle absent : %s" % SOCLE}
    socle = json.loads(SOCLE.read_text(encoding="utf-8"))["fichiers"]
    candidats, exclus, illisibles = [], [], []
    for nom in sorted(socle):
        p = NR / nom
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - absent/illisible -> DIT, pas devine
            illisibles.append({"fichier": nom, "motif": type(exc).__name__})
            continue
        m = _marqueurs(src)
        fiche = {"fichier": nom, "tests": _compte_tests(src)}
        if m:
            fiche["motifs"] = m
            exclus.append(fiche)
        else:
            candidats.append(fiche)
    return {
        "_verdict": "PRESOMPTION, pas preuve : CANDIDAT = aucune raison VISIBLE "
                    "de l'exclure. A confirmer par une execution ciblee, en petit "
                    "lot, avant tout ajout a PURE_TESTS.",
        "candidats": candidats,
        "tests_recuperables": sum(c["tests"] for c in candidats),
        "exclus_a_juste_titre": exclus,
        "tests_hors_portee": sum(e["tests"] for e in exclus),
        "illisibles": illisibles,
    }


def valider(candidats: list[dict], timeout_s: int = 120) -> dict:
    """Execute CHAQUE candidat isolement. Seul le vert integral est rapatriable.

    Mesure 2026-08-20 : lances ensemble, les 39 candidats du tri statique ont
    rendu « 45 failed, 410 passed, 31 errors ». La presomption statique ne suffit
    donc PAS -- plusieurs fichiers exigent un contexte d'authentification, et un
    autre charge un `.pyc` d'un ancien depot (« source code not available »).
    Un fichier n'entre dans la suite pure que s'il passe SEUL, sans rien monter.
    """
    import subprocess

    verts, rouges = [], []
    for c in candidats:
        chemin = "tests/nr/" + c["fichier"]
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", chemin, "-q", "--no-header",
                 "-p", "no:cacheprovider", "--timeout=30"],
                cwd=str(ROOT), capture_output=True, text=True,
                errors="replace", timeout=timeout_s)
            rc = r.returncode
        except Exception as exc:  # noqa: BLE001 - un fichier qui bloque est ROUGE, pas vert
            rc, r = -1, None
            rouges.append({**c, "motif": "execution KO : %s" % type(exc).__name__})
            continue
        if rc == 0:
            verts.append(c)
        else:
            derniere = ""
            if r is not None:
                lignes = [ligne for ligne in (r.stdout or "").splitlines() if ligne.strip()]
                derniere = lignes[-1][:110] if lignes else ""
            rouges.append({**c, "motif": "rc=%d %s" % (rc, derniere)})
    return {"verts": verts, "rouges": rouges,
            "tests_rapatriables": sum(v["tests"] for v in verts)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Trie la dette des tests hors suite pure")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--valider", action="store_true",
                    help="execute chaque candidat SEUL ; seul le vert est rapatriable")
    a = ap.parse_args()
    r = trier()
    if "ARRET" in r:
        print("ARRET :", r["ARRET"])
        return 2
    if a.valider:
        v = valider(r["candidats"])
        if a.json:
            print(json.dumps(v, ensure_ascii=False, indent=1))
            return 0
        print("VERTS SEULS (%d fichiers, %d tests) — rapatriables :"
              % (len(v["verts"]), v["tests_rapatriables"]))
        for c in v["verts"]:
            print("   %-52s %3d tests" % (c["fichier"], c["tests"]))
        print("\nROUGES SEULS (%d) — la presomption statique ne suffisait pas :"
              % len(v["rouges"]))
        for c in v["rouges"]:
            print("   %-52s %s" % (c["fichier"], c["motif"]))
        return 0
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    print("CANDIDATS (%d fichiers, %d tests) — aucun marqueur d'impurete :"
          % (len(r["candidats"]), r["tests_recuperables"]))
    for c in r["candidats"]:
        print("   %-52s %3d tests" % (c["fichier"], c["tests"]))
    print("\nEXCLUS A JUSTE TITRE (%d fichiers, %d tests) :"
          % (len(r["exclus_a_juste_titre"]), r["tests_hors_portee"]))
    for e in r["exclus_a_juste_titre"]:
        print("   %-52s %3d tests  <- %s"
              % (e["fichier"], e["tests"], ", ".join(e["motifs"])))
    if r["illisibles"]:
        print("\nILLISIBLES (ni candidat ni exclu — la mesure a echoue) :")
        for i in r["illisibles"]:
            print("   %-52s %s" % (i["fichier"], i["motif"]))
    print("\n%s" % r["_verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
