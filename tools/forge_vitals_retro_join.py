"""Retro-join : reconstitue les canaux EVENEMENTIELS sur l'historique DEJA ecrit.

POURQUOI CE MODULE EXISTE
=========================
Le 2026-08-23, onze canaux evenementiels ont ete cables dans
`forge_vitals_channels` (process du hub, latence et volume par requete). Ils ne
remplissent la serie qu'A PARTIR DE LEUR CABLAGE : trancher la question
neuromorphique demanderait donc d'attendre des jours d'accumulation.

Or les producteurs, eux, ecrivent depuis longtemps :
  - `sandbox/hub_blackbox.jsonl` porte 212 h avec un `ts` NUMERIQUE et un bloc
    `hub` complet (threads, handles, fds, rss_gb, cpu_pct) — soit PLUS que les
    146 h de `vitals_history.jsonl` ;
  - `promcp_tool_metrics` porte 43 h de latences et d'octets PAR APPEL.

Ce module les rejoint a posteriori sur les timestamps de la serie vitals. Aucun
capteur n'est ajoute, aucune valeur n'est inventee : on lit ce qui a ete ecrit.

CE QU'IL NE FAIT PAS, ET POURQUOI
=================================
Il ne remplace pas le cablage : un retro-join depend de flux tiers qui peuvent
etre purges, et il ne survivra pas a une rotation de `hub_blackbox`. Le cablage
reste la source de verite ; ceci est un ECHAFAUDAGE pour repondre ce soir.

TROIS ETATS, JAMAIS DEUX
========================
Un echantillon vitals sans correspondance dans la fenetre de tolerance recoit
None, jamais une valeur voisine recopiee ni un zero. La COUVERTURE de la
jointure est publiee canal par canal : une jointure qui remplit 30 % des lignes
et se tait la-dessus ferait croire a une mesure complete.
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/retro-jointure"

import io
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Le convertisseur « numerique ou None » vient du module de CANAUX, en un seul
# exemplaire. J'en avais recopie le corps ici sous le nom `_num` : le cliquet de
# clones l'a vu (il teste explicitement qu'un renommage ne cache pas un clone).
# Deux copies de cette regle divergeraient sur le point qui compte — un bool n'est
# PAS un canal continu, et NaN n'est PAS une mesure.
from nokido_agent.app.forge_vitals_channels import _f as _num  # noqa: E402

# Le reste (banc, verite terrain, serie) n'est charge QUE dans main() : ces modules
# tirent torch, et torch est inimportable sous le sandbox python (WORKSPACE_GUARD
# bloque `open(os.devnull)` que dill execute a l'import). Garder ces imports en tete
# rendrait la JOINTURE elle-meme intestable hors de la pile ML, alors qu'elle ne
# depend que de la stdlib.

TOLERANCE_S = 30.0      # au-dela, l'echantillon blackbox ne decrit plus le meme instant
FENETRE_REQ_S = 60.0    # meme fenetre que le canal vivant grp_hub_requetes

CANAUX_PROCESS = {"hth": "threads", "hhd": "handles", "hfd": "fds",
                  "hrs": "rss_gb", "hcp": "cpu_pct"}
CANAUX_REQ = ("ln", "lp95", "lmax", "lerr", "lbi", "lbo")


def charger_blackbox(chemin: Path) -> list[tuple[float, dict]]:
    """(ts, bloc hub) tries. Les lignes sans `ts` numerique ou sans bloc `hub`
    sont ECARTEES et comptees — on ne les assimile pas a des lignes vides."""
    out: list[tuple[float, dict]] = []
    sautees = 0
    if not chemin.exists():
        return out
    with io.open(chemin, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001  # muet-ok : ligne tronquee par une
                # ecriture concurrente ; elle est COMPTEE juste en dessous.
                sautees += 1
                continue
            ts = _num(d.get("ts"))
            hub = d.get("hub")
            if ts is None or not isinstance(hub, dict) or not hub:
                sautees += 1
                continue
            out.append((ts, hub))
    out.sort(key=lambda r: r[0])
    charger_blackbox.sautees = sautees  # type: ignore[attr-defined]
    return out


def charger_metriques(db: Path) -> list[tuple[float, float, int, float, float]]:
    """(ts, duration_ms, ok, payload, result) tries. Lecture seule, timeout court."""
    if not db.exists():
        return []
    con = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True, timeout=2.0)
    try:
        rows = con.execute(
            "SELECT ts, duration_ms, ok, payload_bytes, result_bytes "
            "FROM promcp_tool_metrics ORDER BY ts").fetchall()
    finally:
        con.close()
    out = []
    for ts, dur, ok, pb, rb in rows:
        t = _num(ts)
        if t is None:
            continue
        out.append((t, _num(dur) or 0.0, 0 if ok in (0, False, "0") else 1,
                    _num(pb) or 0.0, _num(rb) or 0.0))
    return out


def enrichir(hist: list[dict], tolerance: float = TOLERANCE_S,
             chemin_blackbox: Path | None = None,
             chemin_db: Path | None = None) -> tuple[list[dict], dict]:
    """Ajoute les canaux evenementiels a chaque echantillon vitals, par plus proche
    voisin temporel borne. Rend (historique enrichi, rapport de COUVERTURE).

    Les chemins sont INJECTABLES : c'est le cliquet de couverture qui a exige un
    test, et un test qui devrait ecrire dans `sandbox/` pour s'executer ne serait
    pas un test pur."""
    bb = charger_blackbox(chemin_blackbox or (ROOT / "sandbox" / "hub_blackbox.jsonl"))
    mt = charger_metriques(chemin_db or (ROOT / "RAG" / "embeddings.db"))

    rempli = {k: 0 for k in list(CANAUX_PROCESS) + list(CANAUX_REQ)}
    hors_tolerance = 0
    i = 0                      # curseur blackbox
    d = f = 0                  # fenetre glissante sur les metriques
    enrichi: list[dict] = []

    for r in hist:
        t = _num(r.get("ts"))
        row = dict(r)
        if t is None:
            enrichi.append(row)
            continue

        # --- plus proche voisin dans la boite noire ---
        while i + 1 < len(bb) and bb[i + 1][0] <= t:
            i += 1
        cand = []
        if i < len(bb):
            cand.append(bb[i])
        if i + 1 < len(bb):
            cand.append(bb[i + 1])
        meilleur = min(cand, key=lambda c: abs(c[0] - t)) if cand else None
        if meilleur and abs(meilleur[0] - t) <= tolerance:
            hub = meilleur[1]
            for court, long in CANAUX_PROCESS.items():
                v = _num(hub.get(long))
                if v is not None:
                    row[court] = v
                    rempli[court] += 1
        else:
            hors_tolerance += 1

        # --- fenetre [t-60, t] sur les metriques ---
        while f < len(mt) and mt[f][0] <= t:
            f += 1
        while d < f and mt[d][0] < t - FENETRE_REQ_S:
            d += 1
        lot = mt[d:f]
        if lot:
            durees = sorted(x[1] for x in lot)
            n = len(lot)
            row["ln"] = float(n)
            row["lp95"] = round(durees[min(n - 1, int(n * 0.95))], 1)
            row["lmax"] = round(durees[-1], 1)
            row["lerr"] = round(100.0 * sum(1 for x in lot if x[2] == 0) / n, 1)
            row["lbi"] = round(sum(x[3] for x in lot) / 1024.0, 2)
            row["lbo"] = round(sum(x[4] for x in lot) / 1024.0, 2)
            for k in CANAUX_REQ:
                rempli[k] += 1
        enrichi.append(row)

    n = max(1, len(hist))
    rapport = {
        "echantillons_vitals": len(hist),
        "lignes_blackbox": len(bb),
        "lignes_blackbox_ecartees": getattr(charger_blackbox, "sautees", 0),
        "lignes_metriques": len(mt),
        "sans_voisin_blackbox": hors_tolerance,
        "tolerance_s": tolerance,
        "couverture_pct": {k: round(100.0 * v / n, 1) for k, v in rempli.items()},
    }
    return enrichi, rapport


def main() -> int:
    from nokido_agent.app.forge_resource_manager import read_vitals_history
    from nokido_agent.tools.forge_snn_vitals_baseline import episodes_detresse
    from nokido_agent.tools.forge_tenns_multicanal_bench import (
        CANAUX_TEMOIN, DERNIERE_SELECTION, REFRACTAIRE_S, choisir_seuil, cibles,
        entrainer, evaluer, proba, selectionner_canaux, stats_robustes,
        tirs_depuis_scores, tirs_temoin, traits,
    )

    t0 = time.time()
    hist = read_vitals_history(0.0, 10 ** 9)
    hist, couverture = enrichir(hist)
    rapport: dict = {"retro_join": couverture,
                     "jointure_s": round(time.time() - t0, 1)}

    eps = episodes_detresse(hist)
    retenus, ecartes = selectionner_canaux(hist)
    stats = stats_robustes(hist, retenus)
    ts, X = traits(hist, 10, canaux=retenus, stats=stats)
    rapport.update({"canaux_retenus": list(retenus), "canaux_ecartes": ecartes,
                    "canaux_temoin": list(CANAUX_TEMOIN),
                    "fenetres_sautees": DERNIERE_SELECTION.get("fenetres_sautees"),
                    "echantillons_traits": len(X),
                    "traits_par_echantillon": len(X[0]) if X else 0,
                    "episodes_total": len(eps)})
    if len(X) < 500 or not eps:
        rapport["verdict"] = "PAS ASSEZ DE DONNEES"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0

    y = cibles(ts, eps, 1800.0)
    coupe = ts[int(len(ts) * 0.6)]
    tr = [i for i, t in enumerate(ts) if t <= coupe]
    te = [i for i, t in enumerate(ts) if t > coupe]
    rapport["positifs_train_pct"] = round(100.0 * sum(y[i] for i in tr) / max(1, len(tr)), 1)
    if sum(y[i] for i in tr) < 10:
        rapport["verdict"] = "PAS ASSEZ D'EPISODES DANS LE TRAIN"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0

    w, b = entrainer([X[i] for i in tr], [y[i] for i in tr])
    rapport["poids_appris"] = {
        "%s_%s" % (c, k): round(v, 3)
        for (c, k), v in zip([(c, k) for c in retenus for k in ("niveau", "pente")], w)}

    # Le choix de seuil vit dans le banc, en UN seul exemplaire : le cliquet de
    # clones a signale cette sequence recopiee ici le 2026-08-23, et il avait raison.
    seuil_ret, note = choisir_seuil([ts[i] for i in tr],
                                    [proba(w, b, X[i]) for i in tr], eps, 3600.0)
    if note:
        rapport["note_seuil"] = note
    rapport["seuil_choisi_sur_train"] = seuil_ret

    s_te = [proba(w, b, X[i]) for i in te]
    t_te = [ts[i] for i in te]
    rapport["periode_test_jours"] = round((t_te[-1] - t_te[0]) / 86400.0, 2)
    rapport["modele_evenementiel"] = evaluer(
        tirs_depuis_scores(t_te, s_te, seuil_ret, REFRACTAIRE_S),
        eps, t_te[0], t_te[-1], 3600.0)
    rapport["temoin_seuil_par_canal"] = evaluer(
        tirs_temoin(hist, REFRACTAIRE_S), eps, t_te[0], t_te[-1], 3600.0)
    rapport["lecture"] = (
        "Meme periode de test, meme refractaire, temoin inchange sur ses 4 canaux. "
        "Le modele ne gagne que s'il voit autant d'episodes AVEC MOINS de faux "
        "positifs. Lire d'abord la COUVERTURE du retro-join : un canal rempli a "
        "30 % n'a pas ete teste, il a ete dilue.")
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
