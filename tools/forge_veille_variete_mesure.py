"""tools/forge_veille_variete_mesure.py — MESURER le seuil hors-variete, pas l'inventer.

Mandat owner 31-07 : « des donnees qualifiees et tres pertinentes pour le RAG et le
code de Nokido ; ce qui ne sert pas l'intelligence doit etre parque de cote ».

POURQUOI CE SCRIPT AVANT TOUT CABLAGE. Un garde hors-sujet LEXICAL a deja ete ecrit
puis RETIRE (trace blackboard, veilles du 25-07) : « calibrage faux dans les deux
sens ; voie correcte = cosinus semantique a seuil mesure ». On ne repose donc pas un
seuil au jugé — on le MESURE sur des cas dont on connait deja la reponse.

CE QU'IL MESURE. Pour chaque texte, la similarite cosinus a un CENTROIDE de reference
construit depuis le corpus qui sert REELLEMENT Nokido (doctrine, code, autoregulation).
On la calcule sur deux populations dont le verdict est connu d'avance :
  - TEMOINS UTILES   : chunks du corpus Nokido lui-meme (doivent scorer HAUT) ;
  - TEMOIN HORS-SUJET: la veille `crawlforge` qui a ramene du Minecraft Forge — derive
    semantique averee, documentee, et le seul cas ou l'on SAIT que la reponse est non.

Sans ces deux populations, un seuil n'est qu'une opinion. Avec elles, on voit s'il
existe une separation, et OU elle se trouve.

CE QU'IL NE FAIT PAS : il n'ecrit rien, ne parque rien, ne modifie aucun chunk. Il
imprime une distribution et une recommandation. Le cablage est une decision SEPAREE,
prise en lisant ces chiffres.

Piege a eviter, deja paye ailleurs : la NOUVEAUTE ne doit pas etre confondue avec le
hors-sujet. Un sujet neuf mais pertinent est LOIN du centroide lui aussi. C'est
pourquoi on regarde la separation entre les deux populations, et non un seuil absolu :
si elles se recouvrent, le centroide seul NE SUFFIT PAS et il faut le dire.

Usage : run action=run_job script=tools/forge_veille_variete_mesure.py
"""
from __future__ import annotations

__FORGE_COLOR__ = "digestif/veille : mesurer le seuil hors-variete"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Domaines qui portent ce que Nokido EST et FAIT : sa doctrine, son code, sa
# regulation. C'est la definition operatoire de « sert l'intelligence ».
DOMAINES_REFERENCE = ("laforge_code", "doctrine", "autoregulation", "laforge", "ia")
N_REF = 400          # taille du centroide : assez pour etre stable, assez peu pour tenir
N_TEMOIN = 120       # temoins utiles tires du meme corpus, HORS echantillon du centroide


def _cos(a, b) -> float:
    import math

    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return num / (na * nb) if na and nb else 0.0


def _vec(blob):
    """Un embedding vit en BLOB float32 OU en JSON selon son origine (les deux
    formats coexistent dans rag_chunks). On rend None si illisible — jamais un
    vecteur nul, qui se ferait passer pour une mesure."""
    if blob is None:
        return None
    try:
        if isinstance(blob, (bytes, bytearray)):
            import struct

            n = len(blob) // 4
            return list(struct.unpack(f"{n}f", blob[: n * 4]))
        return json.loads(blob)
    except Exception:
        return None


def main() -> int:
    from nokido_agent.app.forge_db_path import db_path
    import sqlite3

    conn = sqlite3.connect(db_path(), timeout=60)
    ph = ",".join("?" * len(DOMAINES_REFERENCE))

    print("[variete] construction du centroide de reference…", flush=True)
    vecs = []
    for (b,) in conn.execute(
        f"SELECT embedding FROM rag_chunks WHERE embedding IS NOT NULL "
        f"AND domain IN ({ph}) LIMIT ?", (*DOMAINES_REFERENCE, N_REF)
    ):
        v = _vec(b)
        if v:
            vecs.append(v)
    if len(vecs) < 30:
        print(f"ARRET : seulement {len(vecs)} vecteurs de reference lisibles — "
              "un centroide sur si peu ne mesure rien.")
        return 2
    dim = len(vecs[0])
    centro = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
    print(f"[variete] centroide sur {len(vecs)} chunks, dim={dim}", flush=True)

    def _dist(rows) -> list:
        out = []
        for src, b in rows:
            v = _vec(b)
            if v and len(v) == dim:
                out.append((_cos(v, centro), src))
        return sorted(out)

    # TEMOINS UTILES : autres chunks du corpus de reference (offset pour ne pas
    # reprendre ceux du centroide — sinon on mesure un texte contre lui-meme).
    utiles = _dist(conn.execute(
        f"SELECT source, embedding FROM rag_chunks WHERE embedding IS NOT NULL "
        f"AND domain IN ({ph}) LIMIT ? OFFSET ?", (*DOMAINES_REFERENCE, N_TEMOIN, N_REF)))

    # TEMOIN HORS-SUJET AVERE : la veille crawlforge -> Minecraft Forge.
    hors = _dist(conn.execute(
        "SELECT source, embedding FROM rag_chunks WHERE embedding IS NOT NULL "
        "AND (lower(source) LIKE '%crawlforge%' OR lower(text) LIKE '%minecraft%') LIMIT 60"))

    # VEILLES RECENTES : population a trier, verdict INCONNU — c'est elle qu'on
    # cherche a qualifier. Elle sert a voir de quel cote elle tombe.
    veille = _dist(conn.execute(
        "SELECT source, embedding FROM rag_chunks WHERE embedding IS NOT NULL "
        "AND domain='watch_veille' ORDER BY rowid DESC LIMIT 200"))

    def _stat(nom, d):
        if not d:
            print(f"  {nom}: AUCUN vecteur — population absente, pas 'zero resultat'")
            return None
        vals = [x[0] for x in d]
        n = len(vals)
        p = lambda q: vals[min(n - 1, int(q * n))]  # noqa: E731
        print(f"  {nom}: n={n} min={vals[0]:.3f} p10={p(.10):.3f} "
              f"median={p(.50):.3f} p90={p(.90):.3f} max={vals[-1]:.3f}")
        return vals

    print("\n=== DISTRIBUTION DE LA SIMILARITE AU CENTROIDE NOKIDO ===")
    v_utiles = _stat("TEMOINS UTILES (corpus Nokido) ", utiles)
    v_hors = _stat("TEMOIN HORS-SUJET (minecraft)  ", hors)
    v_veille = _stat("VEILLES (a qualifier)          ", veille)

    print("\n=== SEPARATION ===")
    if v_utiles and v_hors:
        p10_utiles = v_utiles[max(0, int(.10 * len(v_utiles)))]
        p90_hors = v_hors[min(len(v_hors) - 1, int(.90 * len(v_hors)))]
        print(f"  p10 des UTILES  = {p10_utiles:.3f}")
        print(f"  p90 du HORS-SUJET = {p90_hors:.3f}")
        if p90_hors < p10_utiles:
            seuil = round((p90_hors + p10_utiles) / 2, 3)
            print(f"  SEPARATION NETTE -> seuil recommande {seuil} "
                  f"(entre les deux populations)")
        else:
            print("  RECOUVREMENT : les deux populations se chevauchent. Le centroide")
            print("  SEUL ne discrimine pas — parquer sur ce critere ferait des degats.")
            print("  Ne PAS cabler de seuil ici ; il faut un critere par AXES (PCA) ou")
            print("  une reference par organe, pas une moyenne globale.")
    else:
        print("  mesure impossible : une population temoin manque (voir ci-dessus).")

    if v_veille and v_utiles:
        p10_utiles = v_utiles[max(0, int(.10 * len(v_utiles)))]
        sous = sum(1 for x in v_veille if x < p10_utiles)
        print(f"\n  veilles sous le p10 des utiles : {sous}/{len(v_veille)} "
              f"({100 * sous / len(v_veille):.0f}%) — candidats au parquage")
    print("\n5 veilles les PLUS LOIN du centroide (candidates au parquage) :")
    for s, src in veille[:5]:
        print(f"  {s:.3f}  {src[:88]}")
    print("\n5 veilles les PLUS PROCHES (a garder a coup sur) :")
    for s, src in veille[-5:]:
        print(f"  {s:.3f}  {src[:88]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
