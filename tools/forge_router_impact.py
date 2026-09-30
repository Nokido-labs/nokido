__FORGE_COLOR__ = "cognition/routage-de-recuperation"

import json
import sys
import argparse

def rejouabilite(ligne):
    resultats = ligne.get("resultats", [])
    if not resultats:
        return False, "observation sans resultat"
    
    for r in resultats:
        v = r.get("vector_score")
        if v == "NOT_OBSERVABLE":
            return False, "vector_score NOT_OBSERVABLE"
        l = r.get("lexical_score")
        if l == "NOT_OBSERVABLE":
            return False, "lexical_score NOT_OBSERVABLE"
            
    return True, ""

def couverture(lignes, illisibles=0):
    total = len(lignes) + illisibles
    rejouables = 0
    non_rejouables = 0
    motifs = {}
    
    for ligne in lignes:
        ok, motif = rejouabilite(ligne)
        if ok:
            rejouables += 1
        else:
            non_rejouables += 1
            motifs[motif] = motifs.get(motif, 0) + 1
            
    taux = (rejouables / total) if total > 0 else None
    
    return {
        "total": total,
        "rejouables": rejouables,
        "non_rejouables": non_rejouables,
        "illisibles": illisibles,
        "motifs": motifs,
        "taux": taux
    }

def charger(chemin):
    lignes = []
    n_illisibles = 0
    with open(chemin, "r", encoding="utf-8") as f:
        for text_line in f:
            text_line = text_line.strip()
            if not text_line:
                continue
            try:
                lignes.append(json.loads(text_line))
            except json.JSONDecodeError:
                n_illisibles += 1
    return lignes, n_illisibles

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", required=True, help="Chemin vers le journal JSONL")
    args = parser.parse_args()
    
    lignes, illisibles = charger(args.journal)
    c = couverture(lignes, illisibles)
    print(json.dumps(c))
    return 0

if __name__ == "__main__":
    sys.exit(main())
