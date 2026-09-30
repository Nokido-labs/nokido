"""tools/forge_veille_variete_organe.py — qualification par ORGANE, pas par moyenne globale.

Decision owner 31-07, apres la refutation du centroide GLOBAL mesuree le meme soir :
moyenner 400 vecteurs de quinze organes heterogenes produit un vecteur quasi nul,
orthogonal a tout (cosinus dans +/-0.055 pour TOUTES les populations, recouvrement
franc entre le corpus utile et un hors-sujet avere). Un seuil pose la-dessus aurait
parque 80 % des veilles au hasard.

L'HYPOTHESE TESTEE ICI : un centroide PAR ORGANE est coherent (les modules d'un meme
organe se ressemblent), donc non degenere. Un document se qualifie alors non pas en
ressemblant a la moyenne de Nokido — qui ne ressemble a rien — mais en servant UN
organe identifie du corps. On retient le MEILLEUR organe (max de similarite) et son
nom : la reponse utile n'est pas « c'est pertinent », c'est « c'est pertinent POUR
l'organe X ».

PROTOCOLE, identique au precedent pour que les resultats soient comparables :
  - TEMOINS UTILES    : chunks du corpus Nokido (doivent trouver leur organe) ;
  - TEMOIN HORS-SUJET : la veille crawlforge -> Minecraft Forge, derive averee ;
  - VEILLES           : population a qualifier, verdict inconnu.
On ne conclut QUE si les deux temoins se separent. S'ils se recouvrent encore, on le
dit et on ne cable rien — comme la derniere fois.

CE SCRIPT N'ECRIT RIEN. Il mesure et recommande. Le cablage est une decision separee.

Usage : run action=trusted_script path=tools/forge_veille_variete_organe.py
"""
from __future__ import annotations

__FORGE_COLOR__ = "digestif/veille : qualification de la veille par organe"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CARTE = ROOT / "sandbox" / "workspace" / "organ_map_full.json"
MIN_CHUNKS_ORGANE = 25    # sous ce seuil un centroide d'organe n'est pas stable
MAX_PAR_ORGANE = 150      # borne le cout memoire/temps


def _cos(a, b) -> float:
    import math

    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return num / (na * nb) if na and nb else 0.0


def _vec(blob):
    """Decodage DELEGUE au decodeur officiel du moteur RAG.

    Ma premiere version faisait `len(blob)//4` sur les octets, en supposant du
    float32. Resultat MESURE : des « dimensions » de 5677, 5684, 5689… toutes
    differentes — c'etaient des embeddings stockes en JSON TEXTE, dont je lisais
    la longueur de chaine. Sur 2039 vecteurs, 41 seulement etaient reellement en
    1024D ; le reste etait du bruit que j'aurais moyenne sans le voir.
    `forge_rag_engine._decode_embedding_blob` gere les DEUX formats et existait
    depuis le debut : le reecrire etait la faute, pas un detail.
    """
    if blob is None:
        return None
    try:
        from nokido_agent.app.forge_rag_engine import _decode_embedding_blob as _dec

        v = _dec(blob)
        return list(v) if v is not None and len(v) else None
    except Exception:
        # Repli STRICT : uniquement le JSON explicite. On ne devine JAMAIS une
        # dimension depuis une longueur d'octets — c'est ce qui a produit le bruit.
        try:
            v = json.loads(blob) if isinstance(blob, (str, bytes, bytearray)) else None
            return list(v) if isinstance(v, list) and v else None
        except Exception:
            return None


def _mapping_module_organe() -> dict:
    """Extrait le mapping fichier.py -> organe, quelle que soit la forme du JSON.

    La carte porte plusieurs blocs (mapping, comptes par organe, stats de methode) ;
    ma premiere lecture avait pris le tout pour le mapping et rendu un verdict FAUX
    (« 52/57 suggestions orphelines »). On identifie donc le bloc par son CONTENU :
    celui dont les valeurs sont des chaines et les clefs des noms de fichiers .py.
    """
    d = json.loads(CARTE.read_text(encoding="utf-8"))
    if not isinstance(d, dict):
        return {}
    candidats = [d] + [v for v in d.values() if isinstance(v, dict)]
    for bloc in candidats:
        cles_py = [k for k in bloc if str(k).endswith(".py")]
        if len(cles_py) > 50 and all(isinstance(bloc[k], str) for k in cles_py[:20]):
            return {str(k).lower(): str(bloc[k]).lower() for k in cles_py}
    return {}


def main() -> int:
    from nokido_agent.app.forge_db_path import db_path
    import sqlite3
    from collections import defaultdict

    mapping = _mapping_module_organe()
    if not mapping:
        print("ARRET : mapping module->organe illisible dans organ_map_full.json")
        return 2
    organes = sorted(set(mapping.values()))
    print(f"[organe] {len(mapping)} modules classes en {len(organes)} organes", flush=True)

    conn = sqlite3.connect(db_path(), timeout=60)

    # Centroide PAR ORGANE : on regroupe les chunks du corpus par organe via le
    # nom de fichier present dans `source`.
    print("[organe] construction des centroides…", flush=True)
    acc = defaultdict(list)
    for src, blob in conn.execute(
        "SELECT source, embedding FROM rag_chunks WHERE embedding IS NOT NULL "
        "AND (source LIKE 'app/%' OR source LIKE 'tools/%') LIMIT 20000"
    ):
        base = str(src).split("#")[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        org = mapping.get(base)
        if not org or len(acc[org]) >= MAX_PAR_ORGANE:
            continue
        v = _vec(blob)
        if v:
            acc[org].append(v)

    # DIMENSIONS HETEROGENES : le corpus porte des embeddings de plusieurs
    # generations (1024D BGE-M3 et des vecteurs plus anciens). Moyenner sans trier
    # leve IndexError — et, pire, un melange silencieux produirait un centroide qui
    # n'est celui d'aucun modele. On retient la dimension DOMINANTE et on DIT
    # combien de vecteurs sont ecartes : une couverture surestimee en silence est
    # exactement ce que ces mesures cherchent a eviter.
    from collections import Counter as _Cnt

    dims = _Cnt(len(v) for vs in acc.values() for v in vs)
    if not dims:
        print("ARRET : aucun vecteur exploitable")
        return 2
    DIM, _n_dim = dims.most_common(1)[0]
    _total = sum(dims.values())
    print(f"[organe] dimension dominante {DIM} ({_n_dim}/{_total} vecteurs) ; "
          f"ecartes {_total - _n_dim} d'autres dimensions {dict(dims)}")

    centro = {}
    for org, vs in acc.items():
        vs = [v for v in vs if len(v) == DIM]
        if len(vs) >= MIN_CHUNKS_ORGANE:
            centro[org] = [sum(v[i] for v in vs) / len(vs) for i in range(DIM)]
            acc[org] = vs
    print(f"[organe] {len(centro)} centroides stables (>= {MIN_CHUNKS_ORGANE} chunks) :")
    for org in sorted(centro):
        print(f"    {org} ({len(acc[org])} chunks)")
    if len(centro) < 3:
        print("ARRET : trop peu d'organes couverts pour conclure quoi que ce soit.")
        return 2

    def _meilleur(v):
        """(similarite max, organe le plus proche). La reponse utile n'est pas
        « pertinent » mais « pertinent POUR tel organe »."""
        best, arg = -2.0, None
        for org, c in centro.items():
            s = _cos(v, c)
            if s > best:
                best, arg = s, org
        return best, arg

    def _pop(rows):
        out = []
        for src, blob in rows:
            v = _vec(blob)
            if v and len(v) == DIM:
                s, org = _meilleur(v)
                out.append((s, org, src))
        return sorted(out)

    utiles = _pop(conn.execute(
        "SELECT source, embedding FROM rag_chunks WHERE embedding IS NOT NULL "
        "AND (source LIKE 'app/%' OR source LIKE 'tools/%') "
        "ORDER BY rowid DESC LIMIT 120"))
    hors = _pop(conn.execute(
        "SELECT source, embedding FROM rag_chunks WHERE embedding IS NOT NULL "
        "AND (lower(source) LIKE '%crawlforge%' OR lower(text) LIKE '%minecraft%') LIMIT 60"))
    veille = _pop(conn.execute(
        "SELECT source, embedding FROM rag_chunks WHERE embedding IS NOT NULL "
        "AND domain='watch_veille' ORDER BY rowid DESC LIMIT 250"))

    def _stat(nom, d):
        if not d:
            print(f"  {nom}: population ABSENTE (pas 'zero resultat')")
            return None
        vals = [x[0] for x in d]
        n = len(vals)
        p = lambda q: vals[min(n - 1, int(q * n))]  # noqa: E731
        print(f"  {nom}: n={n} min={vals[0]:.3f} p10={p(.10):.3f} "
              f"median={p(.50):.3f} p90={p(.90):.3f} max={vals[-1]:.3f}")
        return vals

    print("\n=== SIMILARITE AU MEILLEUR ORGANE ===")
    v_ut = _stat("TEMOINS UTILES (code Nokido)", utiles)
    v_ho = _stat("TEMOIN HORS-SUJET (minecraft)", hors)
    v_ve = _stat("VEILLES (a qualifier)       ", veille)

    print("\n=== SEPARATION ===")
    seuil = None
    if v_ut and v_ho:
        p10_ut = v_ut[max(0, int(.10 * len(v_ut)))]
        p90_ho = v_ho[min(len(v_ho) - 1, int(.90 * len(v_ho)))]
        print(f"  p10 des UTILES    = {p10_ut:.3f}")
        print(f"  p90 du HORS-SUJET = {p90_ho:.3f}")
        if p90_ho < p10_ut:
            seuil = round((p90_ho + p10_ut) / 2, 3)
            print(f"  SEPARATION NETTE -> seuil mesure = {seuil}")
            print("  Un document sous ce seuil ne sert AUCUN organe : candidat au parquage.")
        else:
            print("  RECOUVREMENT ENCORE : par organe non plus, la similarite ne separe")
            print("  pas. NE RIEN CABLER. Piste suivante : le critere n'est pas la")
            print("  ressemblance au CODE mais au MANDAT (roadmap/gaps) — autre reference.")
    if v_ve and seuil is not None:
        sous = sum(1 for x in v_ve if x < seuil)
        print(f"\n  veilles sous le seuil : {sous}/{len(v_ve)} "
              f"({100 * sous / len(v_ve):.0f}%) — a PARQUER, pas a supprimer")
        from collections import Counter
        rep = Counter(o for s, o, _ in veille if s >= seuil)
        print("  organes servis par les veilles retenues :")
        for org, n in rep.most_common(8):
            print(f"    {n:4d}  {org}")
    print("\n5 veilles les MIEUX ancrees (organe + score) :")
    for s, org, src in veille[-5:]:
        print(f"  {s:.3f}  [{org}]  {str(src)[:70]}")
    print("\n5 veilles les PLUS hors-variete :")
    for s, org, src in veille[:5]:
        print(f"  {s:.3f}  [{org}]  {str(src)[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
