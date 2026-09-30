#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_embed_cloudflare_lot.py - lot BORNE de vectorisation via Cloudflare Workers AI.

__FORGE_COLOR__ = "vegetatif/embedding : lot cloud Cloudflare borne, mesure la capacite journaliere reelle"

Question owner (2026-09-06) : « on a dit qu'il y avait juste un quota journalier » -
COMBIEN de chunks ce quota vaut-il, mesure et non extrapole ? Deux chiffres se
contredisent : 3 631 chunks puis HTTP 429 le 2026-08-03 (chunks longs, appels texte par
texte via embed()) ; 9,3 M tokens/jour au tarif public (1 075 neurones / M tokens), soit
~37 000 chunks de 700 caracteres si le compteur est bien au token. Ce script tranche en
drainant du VRAI backlog (meme bge-m3 1024d, meme espace que la base) jusqu'au refus.

Ce qu'il fait, en UN job detache `online=true` (le compte offline n'a pas d'egress) :
  1. verifie la presence des identifiants (booleens, jamais la valeur) ;
  2. selection INDEXEE des chunks sans vecteur (meme clause que le drain, EXPLAIN
     verifie avant lecture) ;
  3. appelle `forge_embed_router._cloudflare_call` EN LOT (--batch textes/requete),
     capture ses avertissements (le routeur nomme chaque refus) ;
  4. ecrit les vecteurs par `open_writer` + rowcount ; `progress.json` a chaque lot ;
  5. s'arrete sur QUOTA_EPUISE (message « neurons » / 429), sur --max-echecs refus
     consecutifs d'une autre nature (REFUS, message cite), ou en fin de lot (LOT_FINI).

Le rapport (sandbox/embed_cloudflare_lot.json) porte : ecrits, echecs, duree, s/chunk,
chars/chunk moyen, etat final et le dernier message (identifiants masques).

Usage : LAFORGE_PYTHON tools/forge_embed_cloudflare_lot.py [--chunks 20000] [--batch 50]
        [--max-echecs 3] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

OUT = ROOT / "sandbox" / "embed_cloudflare_lot.json"
PROG = ROOT / "sandbox" / "embed_cloudflare_lot.progress.json"
_MASQUE = re.compile(r"[0-9a-fA-F]{24,}")


class _Capte(logging.Handler):
    """Garde le dernier avertissement du routeur (la cause nommee du refus)."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.dernier = ""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.dernier = _MASQUE.sub("<masque>", record.getMessage())[:300]
        except Exception:  # noqa: BLE001
            self.dernier = "<illisible>"  # dit, pas avale


from nokido_agent.tools.forge_embed_lot_commun import (  # noqa: E402  (apres l'amorce sys.path)
    candidats_sans_vecteur, ecrire_rapport, ouvrir_lecture,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", type=int, default=20000)
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--max-echecs", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    from nokido_agent.app import forge_embed_router as er  # type: ignore

    capte = _Capte()
    logging.getLogger().addHandler(capte)
    er.logger.addHandler(capte)

    rapport: dict = {"debut": time.strftime("%Y-%m-%dT%H:%M:%S"), "chunks_demandes": a.chunks,
                     "batch": a.batch, "lots": []}

    def _fin(etat: str, raison: str = "", rc: int = 0) -> int:
        rapport["etat"] = etat
        rapport["dernier_message"] = capte.dernier
        ecrire_rapport(OUT, rapport, etat, raison, sans=("lots",))
        return rc

    creds = bool(er._provider_has_creds("cloudflare"))
    rapport["identifiants_presents"] = creds
    if not creds:
        return _fin("INDETERMINE", "identifiants Cloudflare absents du coffre pour ce compte (non configure != refuse)", 2)

    from nokido_agent.app.forge_db_path import open_writer  # type: ignore
    ro = ouvrir_lecture()
    try:
        rows = candidats_sans_vecteur(ro, a.chunks, dire=lambda m: print(m, flush=True))
    finally:
        ro.close()
    rapport["candidats"] = len(rows)
    rapport["chars_par_chunk_moy"] = round(sum(len(r[1] or "") for r in rows) / max(len(rows), 1))
    if not rows:
        return _fin("LOT_FINI", "aucun chunk candidat (hot, sans vecteur)")
    if a.dry_run:
        return _fin("DRY_RUN", f"{len(rows)} candidats, rien envoye")

    conn = open_writer(timeout=30.0)
    ecrits = echecs_chunks = 0
    echecs_consecutifs = 0
    t0 = time.time()
    etat, raison = "LOT_FINI", ""
    try:
        for i in range(0, len(rows), a.batch):
            lot = rows[i:i + a.batch]
            capte.dernier = ""
            t_lot = time.time()
            try:
                vecs = er._cloudflare_call([r[1] or "" for r in lot], timeout=60.0)
            except Exception as e:  # noqa: BLE001
                vecs = None
                capte.dernier = f"exception {type(e).__name__}: {str(e)[:200]}"
            if not vecs:
                echecs_chunks += len(lot)
                echecs_consecutifs += 1
                msg = capte.dernier.lower()
                if "neuron" in msg or " 429" in msg or "429 " in msg or "quota" in msg:
                    etat, raison = "QUOTA_EPUISE", f"apres {ecrits} chunks ecrits : {capte.dernier}"
                    break
                if echecs_consecutifs >= a.max_echecs:
                    etat, raison = "REFUS", f"{echecs_consecutifs} lots refuses d'affilee : {capte.dernier}"
                    break
                time.sleep(2.0)
                continue
            echecs_consecutifs = 0
            ok_lot = 0
            for (cid, _), v in zip(lot, vecs):
                cur = conn.execute("UPDATE rag_chunks SET embedding=? WHERE id=? AND embedding IS NULL",
                                   (struct.pack("1024f", *v), cid))
                if cur.rowcount == 1:
                    ok_lot += 1
                else:
                    echecs_chunks += 1
            ecrits += ok_lot
            ech = {"lot": i // a.batch, "ecrits": ecrits, "echecs": echecs_chunks,
                   "s_lot": round(time.time() - t_lot, 2), "t_s": round(time.time() - t0, 1)}
            rapport["lots"].append(ech)
            try:
                PROG.write_text(json.dumps(ech), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass  # muet-ok : le progres est aussi sur stdout
            if (i // a.batch) % 10 == 0:
                print(f"[lot] {ech}", flush=True)
    finally:
        conn.close()

    duree = time.time() - t0
    rapport.update({"ecrits": ecrits, "echecs_chunks": echecs_chunks, "duree_s": round(duree, 1),
                    "s_par_chunk": round(duree / max(ecrits, 1), 4),
                    "chunks_par_heure": round(ecrits / max(duree, 1) * 3600)})
    return _fin(etat, raison, 0 if etat in ("LOT_FINI", "QUOTA_EPUISE") else 1)


if __name__ == "__main__":
    raise SystemExit(main())
