#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_espace_vectoriel_preuve.py - PROUVER que deux modeles 1024d ne partagent pas d'espace.

__FORGE_COLOR__ = "qualite/preuve : demontre par la mesure qu'une meme dimension ne fait pas un meme espace vectoriel"

Question owner (2026-09-06) : « Qwen3-Embedding-0.6B rend 1024 dimensions, ca permet
peut-etre de faire ? ». La reponse ne doit pas etre un principe recite mais une MESURE.

Le protocole, sur des chunks DEJA vectorises en base (bge-m3) :

  1. lire N chunks avec leur vecteur bge-m3 (1024d) et leur texte ;
  2. demander a l'autre modele le vecteur du MEME texte ;
  3. comparer :
       a) cos(bge[i], autre[i])            -- le meme texte, vu par deux modeles
       b) cos(bge[i], bge[j]) vs cos(autre[i], autre[j])  -- la STRUCTURE des distances

Ce qu'il faut lire :
  - si (a) est proche de 0, les deux espaces ne sont pas alignes : ecrire un vecteur de
    l'un a cote des vecteurs de l'autre rend les distances incomparables, en silence ;
  - (b) peut rester correle : deux bons modeles classent les memes textes comme proches.
    C'est ce qui rend le piege VICIEUX -- le modele de remplacement est peut-etre
    excellent, il reste inutilisable DANS le meme index sans tout reindexer.

    LAFORGE_PYTHON tools/forge_espace_vectoriel_preuve.py [--modele Qwen/Qwen3-Embedding-0.6B]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)


# Le cosinus et l'echantillonneur borne vivent dans la brique commune depuis le
# 2026-09-06 : deux outils de mesure en portaient une copie, le cliquet de duplication
# les a attrapes, et une primitive partagee par deux mesures appartient au commun.
from nokido_agent.tools.forge_embed_lot_commun import cos as _cos  # noqa: E402
from nokido_agent.tools.forge_embed_lot_commun import echantillon_vectorise  # noqa: E402


# _echantillon a ete DEPLACE dans forge_embed_lot_commun.echantillon_vectorise le
# 2026-09-06 (cliquet de duplication). Le comportement est identique, cap par defaut 400.


def _vecteurs_siliconflow(textes: list[str], modele: str) -> list[list[float]] | None:
    from nokido_agent.app.forge_secrets import get_secret  # type: ignore

    cle = get_secret("SILICONFLOW") or ""
    if not cle:
        print("clef SILICONFLOW absente -- INDETERMINE")
        return None
    body = json.dumps({"model": modele, "input": textes, "dimensions": 1024}).encode()
    req = urllib.request.Request(
        "https://api.siliconflow.com/v1/embeddings", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + cle.strip()})
    try:
        with urllib.request.urlopen(req, timeout=60.0) as r:
            d = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        corps = ""
        lire = getattr(e, "read", None)
        if callable(lire):
            try:
                corps = lire().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001
                corps = ""
        print(f"appel KO ({type(e).__name__}) {corps}")
        return None
    items = sorted(d.get("data") or [], key=lambda x: x.get("index", 0))
    return [x.get("embedding") for x in items]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modele", default="Qwen/Qwen3-Embedding-0.6B")
    ap.add_argument("--n", type=int, default=6)
    a = ap.parse_args()

    ech = echantillon_vectorise(a.n)
    if len(ech) < 3:
        print(f"seulement {len(ech)} chunk(s) exploitables -- INDETERMINE")
        return 2
    textes = [t for _, t, _ in ech]
    autres = _vecteurs_siliconflow(textes, a.modele)
    if not autres or len(autres) != len(ech):
        print("pas de vecteurs comparables -- INDETERMINE")
        return 2

    print(f"\n=== MEME TEXTE, DEUX MODELES : bge-m3 (en base) vs {a.modele} ===")
    print("    (proche de 0 = espaces NON alignes : melanger les deux casse les distances)")
    mm = []
    for i, (cid, _, v) in enumerate(ech):
        c = _cos(v, autres[i])
        mm.append(c)
        print(f"  chunk {cid[:26]:28s} cos = {c:+.4f}")
    print(f"  moyenne = {sum(mm)/len(mm):+.4f}  (dim bge={len(ech[0][2])}, dim autre={len(autres[0])})")

    print("\n=== STRUCTURE DES DISTANCES (paires de textes) ===")
    print("    un bon modele classe les memes textes comme proches : la correlation peut")
    print("    rester elevee, et c'est ce qui rend le piege vicieux -- bon modele,")
    print("    espace incompatible.")
    pa, pb = [], []
    for i in range(len(ech)):
        for j in range(i + 1, len(ech)):
            pa.append(_cos(ech[i][2], ech[j][2]))
            pb.append(_cos(autres[i], autres[j]))
    if len(pa) >= 2:
        ma, mb = sum(pa) / len(pa), sum(pb) / len(pb)
        cov = sum((x - ma) * (y - mb) for x, y in zip(pa, pb))
        va = math.sqrt(sum((x - ma) ** 2 for x in pa)) or 1e-9
        vb = math.sqrt(sum((y - mb) ** 2 for y in pb)) or 1e-9
        print(f"  paires={len(pa)}  cos moyen bge={ma:+.3f}  autre={mb:+.3f}  "
              f"correlation des distances={cov / (va * vb):+.3f}")

    print("\n=== VERDICT ===")
    moy = sum(mm) / len(mm)
    if abs(moy) < 0.30:
        print(f"  ESPACES DISTINCTS (cos moyen {moy:+.3f}) : ce modele ne peut PAS completer")
        print("  la colonne `embedding` existante. L'adopter = reindexer TOUTE la base.")
    else:
        print(f"  cos moyen {moy:+.3f} -- inattendu, a instruire avant toute conclusion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
