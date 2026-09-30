#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Mesure du chemin d'embedding ONNX LOCAL — identite de l'espace, puis debit.

__FORGE_COLOR__ = "vegetatif/embedding : mesure du chemin ONNX local, identite d'espace puis debit"

POURQUOI CET OUTIL EXISTE (2026-09-06)
--------------------------------------
`app/forge_bge_m3_shared.py` porte DEJA une session ONNX BGE-M3 avec la preference
`DmlExecutionProvider > CPUExecutionProvider`, le modele est sur disque depuis le
2026-05-03 (`models/bge_m3_onnx/model.onnx`) — et **zero fichier ne l'importe**. Un module
ecrit et non branche n'est pas une capacite : c'est une dette de cablage. Cet outil le
BRANCHE le temps d'une mesure, sans rien installer et sans rien ecrire en base.

CE QU'IL REFUSE DE CONFONDRE
---------------------------
1. `DmlExecutionProvider` **demande** n'est pas `DmlExecutionProvider` **obtenu**. Le build
   `onnxruntime` installe peut etre CPU-seul ; la cascade retombe alors sur CPU EN SILENCE.
   On imprime donc les providers DISPONIBLES, ceux RETENUS, et l'etat reel de la session.
2. Un debit sans **gate d'identite** ne vaut rien : un export qui ne rend pas le meme espace
   que `rag_chunks.embedding` produirait des recherches silencieusement fausses.
3. Un vecteur ABSENT n'est pas un vecteur DIFFERENT. Trois etats, jamais deux.
4. Un gate non franchi est un FAIT ; la CAUSE ne se deduit pas du cosinus (cf.
   `verdict_identite`).

Lecture BORNEE par `rowid` (jamais `LENGTH(text) BETWEEN`, non indexable) et lecture SEULE.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.tools.forge_embed_lot_commun import (  # noqa: E402  (apres l'amorce sys.path)
    cos as _cos,
    echantillon_vectorise,
    ecrire_rapport,
)

OUT = ROOT / "sandbox" / "embed_onnx_mesure.json"
COS_MINIMUM = 0.99
LU_MAX = 600
DEBIT_REFERENCE_8099 = 15.6  # chunks/s mesures sur llama.cpp :8099 le 2026-09-06

# Le chemin en process est ETEINT par defaut (`LAFORGE_BGE_M3_INPROCESS=0`) : sans ce
# drapeau, `embed_parallel` delegue au brain_worker ZMQ et rend des vecteurs VIDES quand
# aucun backend distant ne repond -- ce qui se lit a tort comme « autre espace vectoriel ».
# Paye le 2026-09-06 : cos 0,0 rapporte ECHEC alors que la session n'existait pas.
# Un outil de MESURE allume explicitement le chemin qu'il mesure, et le DIT.
os.environ.setdefault("LAFORGE_BGE_M3_INPROCESS", "1")


def verdict_identite(produits, references, info) -> tuple[str, str, dict]:
    """Tranche l'identite de l'espace. TROIS etats, et la cause n'est JAMAIS deduite.

    - session non chargee, ou aucun vecteur non nul -> INDETERMINE (la mesure n'a pas eu lieu)
    - cos moyen >= COS_MINIMUM                      -> OK
    - sinon                                         -> ECHEC du gate, cause INDETERMINEE

    Sur le dernier cas : un cosinus proche de 0 designerait un espace etranger, mais une
    valeur ELEVEE et UNIFORME (mesure du 2026-09-06 : 0,687-0,694 sur huit textes sans
    rapport entre eux) designe une transformation SYSTEMATIQUE -- pooling different,
    normalisation L2 absente, ou tete d'export autre -- et surement pas un autre modele.
    On refuse le chemin ; on n'invente pas son defaut.
    """
    info = info if isinstance(info, dict) else {}
    extras: dict = {}
    servis = sum(1 for v in produits if v and any(abs(x) > 0 for x in v))
    extras["vecteurs_servis"] = servis
    extras["vecteurs_attendus"] = len(references)

    if info.get("session_loaded") is False or servis == 0:
        extras["chemin_reel"] = "delegation brain_worker / backends distants"
        return ("INDETERMINE",
                ("la session ONNX en process n'a pas ete chargee "
                 f"(inprocess_enabled={info.get('inprocess_enabled')}, "
                 f"session_loaded={info.get('session_loaded')}) ; "
                 f"{servis}/{len(references)} vecteur(s) non nul(s) servis"),
                extras)

    cos = [round(_cos(produits[i], references[i]), 4)
           for i in range(min(len(produits), len(references)))]
    extras["cos_identite"] = cos
    moyen = round(sum(cos) / len(cos), 4) if cos else None
    extras["cos_moyen"] = moyen
    if moyen is not None and moyen >= COS_MINIMUM:
        return ("OK", f"identite confirmee (cos {moyen})", extras)

    etendue = round(max(cos) - min(cos), 4) if cos else None
    extras["cos_etendue"] = etendue
    uniforme = (moyen or 0) > 0.3 and (etendue if etendue is not None else 1.0) < 0.05
    cause = ("transformation systematique probable (pooling / normalisation / tete "
             "d'export) -- cause INDETERMINEE" if uniforme else "cause INDETERMINEE")
    extras["cause"] = cause
    return ("ECHEC",
            f"gate d'identite NON franchi (cos {moyen}, etendue {etendue}) ; {cause}",
            extras)


def _rss_go() -> float | None:
    try:
        import psutil

        return round(psutil.Process(os.getpid()).memory_info().rss / (1024 ** 3), 3)
    except Exception:
        return None


def _providers() -> dict:
    """Trois etats : disponibles / retenus / illisible. Aucun n'est deduit de l'autre."""
    info = {"disponibles": None, "retenus": None, "illisible": None}
    try:
        import onnxruntime as ort

        info["disponibles"] = list(ort.get_available_providers())
    except Exception as e:
        info["illisible"] = f"{type(e).__name__}: {e}"
        return info
    try:
        from nokido_agent.app import forge_bge_m3_shared as bge

        info["retenus"] = [p for p in bge.PROVIDERS_PREFERENCE
                           if p in (info["disponibles"] or [])] or ["CPUExecutionProvider"]
    except Exception as e:
        info["illisible"] = f"preference illisible: {type(e).__name__}: {e}"
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description="Mesure du chemin ONNX local BGE-M3.")
    ap.add_argument("--identite", type=int, default=8,
                    help="nombre de chunks deja vectorises servant au gate d'identite")
    ap.add_argument("--debit", type=int, default=64,
                    help="nombre de textes pour la mesure de debit (0 = pas de mesure)")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--env", default="",
                    help="nom d'un environnement conda (miniforge3/envs/<nom>) dans lequel "
                         "REJOUER cette mesure ; les providers exposes dependent du build "
                         "d'onnxruntime, pas du materiel")
    a = ap.parse_args()

    # PLUSIEURS ENVIRONNEMENTS RYZEN COEXISTENT sur ce poste, et ils n'exposent PAS les
    # memes providers : mesure du 2026-09-06 -- laforge_py314 et ryzen-ai-1.7.1 portent
    # onnxruntime 1.25.1 et ne rendent que [Azure, CPU] alors que les DLL VitisAI/DirectML
    # sont sur le disque, tandis que ryzen-ai-final porte 1.23.2 et rend
    # [VitisAI, Dml, CPU]. Conclure « DirectML absent » depuis UN SEUL environnement est un
    # faux negatif : on nomme donc toujours l'interpreteur qui a produit la mesure.
    if a.env:
        # `Path.home()` MENT sous le compte des jobs (HOME=C:\Users\Default) : le dossier
        # des environnements se deduit de l'interpreteur COURANT, qui vit deja dedans.
        # Mesure du 2026-09-06 : le premier essai a cherche dans C:\Users\Default et a
        # rendu « interpreteur ABSENT » pour un environnement bien present.
        cible = Path(a.env) if os.path.sep in a.env else (
            Path(sys.executable).resolve().parent.parent / a.env / "python.exe")
        if not cible.exists():
            print(f"[env] interpreteur ABSENT : {cible} "
                  f"(cherche depuis {Path(sys.executable).resolve().parent.parent})")
            return 2
        if Path(sys.executable).resolve() != cible.resolve():
            import subprocess

            argv = [str(cible), str(Path(__file__).resolve()),
                    "--identite", str(a.identite), "--debit", str(a.debit),
                    "--workers", str(a.workers)]
            print(f"[env] rejeu dans {a.env} -> {cible}")
            return subprocess.call(argv)

    rapport: dict = {"ts": time.time(), "cos_minimum": COS_MINIMUM,
                     "interpreteur": sys.executable}
    prov = _providers()
    rapport["providers"] = prov
    print(f"[providers] disponibles = {prov['disponibles']}")
    print(f"[providers] retenus     = {prov['retenus']}")
    if prov["illisible"]:
        print(f"[providers] ILLISIBLE   = {prov['illisible']}")
        ecrire_rapport(OUT, rapport, "INDETERMINE", "onnxruntime illisible")
        return 2
    if "DmlExecutionProvider" not in (prov["disponibles"] or []):
        print("[providers] DirectML ABSENT de ce build -> le chemin mesure est CPU. "
              "Ce n'est pas un echec : c'est la baseline, et elle doit etre dite.")

    ech = echantillon_vectorise(a.identite, lu_max=LU_MAX)
    if not ech:
        ecrire_rapport(OUT, rapport, "INDETERMINE", "aucun chunk vectorise exploitable")
        return 2

    try:
        from nokido_agent.app import forge_bge_m3_shared as bge
    except Exception as e:
        rapport["import"] = f"{type(e).__name__}: {e}"
        ecrire_rapport(OUT, rapport, "INDETERMINE", "module ONNX partage non importable")
        return 2

    textes_ech = [t for _, t, _ in ech]
    refs = [v for _, _, v in ech]
    rss0 = _rss_go()
    t0 = time.monotonic()

    # UNE SEULE session chargee : la tete de pooling ne touche que la reduction des sorties,
    # donc comparer deux espaces ne coute pas deux chargements de 2,5 Go. On MESURE la cause
    # au lieu de la deduire du cosinus -- c'est tout l'objet de ce passage.
    par_pooling: dict[str, dict] = {}
    vecteurs: dict[str, list] = {}
    for tete in ("mean", "cls"):
        bge.POOLING = tete
        try:
            v = bge.embed_parallel(textes_ech, max_workers=a.workers)
        except Exception as e:
            par_pooling[tete] = {"erreur": f"{type(e).__name__}: {e}"}
            continue
        if "chargement_plus_premiere_passe_s" not in rapport:
            rapport["chargement_plus_premiere_passe_s"] = round(time.monotonic() - t0, 2)
        vecteurs[tete] = v
        cos_t = [round(_cos(v[i], refs[i]), 4) for i in range(min(len(v), len(refs)))]
        par_pooling[tete] = {
            "cos_moyen": round(sum(cos_t) / len(cos_t), 4) if cos_t else None,
            "cos_etendue": round(max(cos_t) - min(cos_t), 4) if cos_t else None,
        }
        print(f"[pooling {tete}] cos moyen = {par_pooling[tete]['cos_moyen']} "
              f"(etendue {par_pooling[tete]['cos_etendue']})")
    rapport["par_pooling"] = par_pooling

    if not vecteurs:
        rapport["inference"] = par_pooling
        ecrire_rapport(OUT, rapport, "INDETERMINE", "inference ONNX en echec sur toute tete")
        return 2

    # On retient la tete la plus proche de l'espace en base, et le rapport GARDE les deux :
    # un lecteur doit voir l'ecart, pas le croire sur parole.
    meilleure = max(vecteurs, key=lambda k: par_pooling[k].get("cos_moyen") or -1.0)
    rapport["pooling_retenu"] = meilleure
    bge.POOLING = meilleure
    produits = vecteurs[meilleure]
    rapport["rss_avant_go"], rapport["rss_apres_go"] = rss0, _rss_go()
    try:
        rapport["runtime_info"] = bge.runtime_info()
    except Exception as e:
        rapport["runtime_info"] = f"illisible: {type(e).__name__}"
    try:
        rapport["modele_octets_disque"] = bge.MODEL_PATH.stat().st_size
        rapport["modele_go_declare"] = bge.MODEL_SIZE_GB
    except Exception as e:
        rapport["modele_octets_disque"] = f"illisible: {type(e).__name__}"

    verdict, raison, extras = verdict_identite(
        produits, [v for _, _, v in ech], rapport.get("runtime_info"))
    rapport.update(extras)
    print(f"[identite] cos = {extras.get('cos_identite')}")
    print(f"[identite] moyenne = {extras.get('cos_moyen')} (minimum exige {COS_MINIMUM})")

    if verdict != "OK":
        ecrire_rapport(OUT, rapport, verdict, raison)
        print(f"[verdict] {verdict} — {raison}")
        if verdict == "ECHEC":
            print("[verdict] un debit mesure ici n'aurait aucune valeur.")
        return 1 if verdict == "ECHEC" else 2

    if a.debit > 0:
        textes = [t for _, t, _ in ech]
        while len(textes) < a.debit:
            textes += textes
        textes = textes[:a.debit]
        t1 = time.monotonic()
        bge.embed_parallel(textes, max_workers=a.workers)
        dt = time.monotonic() - t1
        rapport["debit_n"] = a.debit
        rapport["debit_s"] = round(dt, 2)
        rapport["debit_chunks_s"] = round(a.debit / dt, 2) if dt > 0 else None
        rapport["rss_fin_go"] = _rss_go()
        print(f"[debit] {a.debit} textes en {dt:.2f} s = "
              f"{rapport['debit_chunks_s']} chunks/s "
              f"(barre a battre : {DEBIT_REFERENCE_8099} sur :8099)")

    ecrire_rapport(OUT, rapport, "OK", raison)
    print(json.dumps(rapport, ensure_ascii=False)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
