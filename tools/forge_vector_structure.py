"""tools/forge_vector_structure.py - ce que le 1024d apporte que le lexical ne voit pas.

Question owner du 2026-08-30 : « la vectorisation 1024d ne te permet pas d'organiser
au mieux la cognition que juste du syntaxique ? ». Elle ne se tranche pas par
raisonnement : on MESURE combien de paires de chunks sont proches en vectoriel
tout en partageant peu de vocabulaire -- c'est exactement ce que le lexical
(BM25/FTS) ne peut pas rapprocher, donc l'apport propre de l'embedding.

Deux mesures, deux verdicts separes :

1. COUVERTURE -- un vecteur qui n'existe pas n'organise rien. Mesure du
   2026-08-30 : `domain=sdk_gitingest` (toute la veille par clone) porte
   **116 620 chunks et ZERO vecteur**. Le meilleur espace semantique du monde
   reste sans effet sur un corpus non vectorise.

2. DISCRIMINATION -- sur l'echantillon vectorise, pour chaque seuil de cosinus :
   combien de paires, et quelle fraction d'entre elles a un recouvrement lexical
   FAIBLE (indice de Jaccard sur les tokens). Une paire a cosinus eleve et
   Jaccard faible est une redondance semantique INVISIBLE au syntaxique : c'est
   la valeur ajoutee de l'embedding, chiffree. A l'inverse, si toutes les paires
   proches partagent deja leur vocabulaire, l'embedding ne fait que confirmer ce
   que BM25 trouvait -- et son cout n'est pas justifie pour ce role.

## Pourquoi ce fichier existe au lieu d'un `run action=python`

PIEGE MESURE le 2026-08-30 : sous `action=python`, **le premier produit matriciel
numpy TUE le process en silence** -- teste jusqu'a une matrice 4x3, donc sans
rapport avec la taille. BLAS instancie son pool de threads a la premiere
utilisation, et le guard du bac a sable le refuse. Il n'y a **ni exception, ni
message** : la sortie s'arrete net apres le dernier `print`, ce qui se lit comme
un timeout ou un resultat vide. C'est la meme famille que `import torch` bloque
sur `nul`, en plus sournois puisque torch, lui, leve une erreur lisible.
Remede : passer par `trusted_script` ou `run_job`, hors du guard.

Usage :
  run action=trusted_script path=tools/forge_vector_structure.py
  ... script_args="--echantillon 3000"
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/organisation-semantique"

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_MOT = re.compile(r"[A-Za-z0-9_]{3,}")

# Sous ce recouvrement de vocabulaire, deux textes ne peuvent pas etre rapproches
# par BM25 : le lexical n'a pas de terme commun sur quoi s'appuyer.
SEUIL_JACCARD_INVISIBLE = 0.35
SEUILS_COS = (0.98, 0.95, 0.90, 0.85)


def jaccard(a: str, b: str) -> float:
    """Recouvrement de vocabulaire. Proxy honnete de ce que BM25 peut rapprocher."""
    A = {m.lower() for m in _MOT.findall(a or "")}
    B = {m.lower() for m in _MOT.findall(b or "")}
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def couverture(conn) -> list[tuple]:
    """Part de chunks vectorises par domaine. Un domaine a 0 % est hors de portee
    de toute organisation semantique, quelle que soit la dimension choisie."""
    return conn.execute(
        "SELECT domain, COUNT(*), SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM rag_chunks GROUP BY domain ORDER BY 2 DESC LIMIT 12"
    ).fetchall()


def discrimination(vecteurs, textes, seuils=SEUILS_COS) -> list[dict]:
    """Pour chaque seuil : paires proches, et combien sont invisibles au lexical.

    Rend une liste de dicts plutot que d'imprimer : testable, et le denominateur
    (`examinees`) accompagne toujours le compte.
    """
    import numpy as np

    M = np.vstack(vecteurs).astype(np.float32)
    M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9
    S = np.triu(M @ M.T, 1)

    out = []
    for s in seuils:
        i, j = np.where(S >= s)
        if len(i) == 0:
            out.append({"seuil": s, "paires": 0, "examinees": 0,
                        "invisibles": 0, "jaccard_median": None})
            continue
        k = min(len(i), 1500)
        js = [jaccard(textes[a], textes[b]) for a, b in zip(i[:k], j[:k])]
        out.append({
            "seuil": s,
            "paires": int(len(i)),
            "examinees": k,
            "invisibles": int(sum(1 for x in js if x < SEUIL_JACCARD_INVISIBLE)),
            "jaccard_median": float(sorted(js)[len(js) // 2]),
        })
    return out


def charger(conn, n: int, dim: int = 1024):
    """Echantillon systematique sur 3 fenetres de rowid (debut / milieu / fin).

    Pas de `ORDER BY RANDOM()` : il scanne la table entiere. Trois fenetres
    valent mieux qu'une, un bloc unique n'etant representatif que de lui-meme.
    """
    from tools.forge_knowledge_overlap import blob_vers_vecteur

    lo, hi = conn.execute("SELECT MIN(rowid), MAX(rowid) FROM rag_chunks").fetchone()
    par_fenetre = max(1, n // 3)
    V, T, vus, rejetes = [], [], 0, 0
    for frac in (0.15, 0.55, 0.92):
        d = int(lo + (hi - lo) * frac)
        for txt, blob in conn.execute(
            "SELECT text, embedding FROM rag_chunks WHERE rowid BETWEEN ? AND ? "
            "AND embedding IS NOT NULL LIMIT ?", (d, d + par_fenetre * 4, par_fenetre)
        ):
            vus += 1
            v = blob_vers_vecteur(blob, dim_attendue=dim)
            if v is None or not (txt or "").strip():
                rejetes += 1
                continue
            V.append(v)
            T.append(txt)
    return V, T, vus, rejetes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--echantillon", type=int, default=2400)
    a = ap.parse_args(argv)

    from tools.forge_knowledge_overlap import ouvrir_lecture

    conn = ouvrir_lecture()
    try:
        print("=== COUVERTURE VECTORIELLE (un vecteur absent n'organise rien) ===")
        for dom, tot, vec in couverture(conn):
            vec = vec or 0
            print(f"   {str(dom)[:26]:28} {tot:>8} chunks | vecteur {vec:>8} "
                  f"({vec * 100.0 / tot:5.1f}%)")
        V, T, vus, rejetes = charger(conn, a.echantillon)
    finally:
        conn.close()

    print(f"\n=== DISCRIMINATION (echantillon {len(V)} vectorises ; "
          f"vus {vus}, rejetes {rejetes}) ===")
    if len(V) < 100:
        print("   echantillon trop faible : AUCUN verdict (ne pas conclure)")
        return 1
    for r in discrimination(V, T):
        if r["paires"] == 0:
            print(f"   cos>={r['seuil']}: aucune paire")
            continue
        part = r["invisibles"] * 100.0 / max(1, r["examinees"])
        print(f"   cos>={r['seuil']}: {r['paires']:>6} paires | jaccard median "
              f"{r['jaccard_median']:.2f} | INVISIBLES au lexical "
              f"{r['invisibles']}/{r['examinees']} ({part:.0f} %)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
