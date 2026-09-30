"""forge_metier_kb_ingest.py — KB pass 2 : ingère de VRAIS docs domaine dans la KB d'un métier.

Le seeding initial (`forge_metier_pool`) a posé 10 `connaissances_cles` LLM par métier —
un amorçage, pas un corpus. KB pass 2 = de vrais documents de référence. La DÉCOUVERTE
(veille SearXNG) est bloquée quand Docker tombe ; l'INGESTION d'une URL CURÉE, elle, ne
dépend que du crawl direct (mesuré 2026-08-02 : `crawl` fetch une URL externe sans searxng).

Cet outil : URL curée → texte → chunks → `rag_chunks(domain=metier_<slug>, source=metier/<slug>)`.
L'EMBEDDING est laissé au trigger auto (chunks à embedding NULL repris par le daemon),
comme le seeding. Réutilise `forge_db_path.open_writer` (autocommit + WAL + busy_timeout,
écritures concurrentes sûres — cf. décision archi 2026-06-04), même chemin que `_seed_kb`.

Portée : le routage tâche→persona s'appuie sur les SIGNATURES (name/expertise), pas la KB ;
KB pass 2 enrichit donc le CONTEXTE des réponses (dispatch.kb_context), pas le routage.

CLI : `--slug actuaire_statisticien --url https://... [--max-chunks 40]`.
Passer les 89 métiers = alimenter cet outil en URLs curées (owner, ou veille quand Docker OK).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
import urllib.request
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "digestif/ingestion-kb-metier"

ROOT = Path(__file__).resolve().parent.parent
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")
_BLANK = re.compile(r"\n{3,}")


def _fetch_text(url: str, timeout: int = 30) -> str:
    """Récupère l'URL et rend du texte propre. urllib + strip (zéro dépendance).

    Rend une chaîne VIDE si l'accès échoue — l'appelant DIT « 0 chunk » plutôt que de
    prétendre avoir ingéré (illisible != vide)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 NokidoKB/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        brut = r.read().decode("utf-8", errors="replace")
    # retire script/style AVANT de stripper les balises (sinon leur contenu pollue)
    brut = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", brut, flags=re.DOTALL | re.IGNORECASE)
    txt = html.unescape(_TAG.sub(" ", brut))
    txt = _WS.sub(" ", txt)
    return _BLANK.sub("\n\n", "\n".join(l.strip() for l in txt.splitlines())).strip()


def _chunks(texte: str, taille: int = 700, chevauchement: int = 120) -> list[str]:
    """Découpe en fenêtres, en coupant de préférence sur une frontière de phrase."""
    mots = texte.split()
    if not mots:
        return []
    out, i = [], 0
    # découpe par caractères avec léger backtrack vers une fin de phrase
    n = len(texte)
    pos = 0
    while pos < n:
        fin = min(pos + taille, n)
        fenetre = texte[pos:fin]
        if fin < n:
            coupe = max(fenetre.rfind(". "), fenetre.rfind("\n"))
            if coupe > taille // 2:
                fenetre = fenetre[:coupe + 1]
                fin = pos + coupe + 1
        f = fenetre.strip()
        if len(f) >= 40:
            out.append(f)
        if fin >= n:
            break
        # borne de PROGRESSION : le recul du chevauchement ne doit jamais
        # ramener pos sur place (sinon la boucle append sans fin -> MemoryError)
        suivant = fin - chevauchement
        pos = suivant if suivant > pos else fin
    return out


def ingest(slug: str, url: str, max_chunks: int = 40) -> dict:
    kb_domain = f"metier_{slug}"
    try:
        texte = _fetch_text(url)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "slug": slug, "raison": f"fetch KO: {type(e).__name__}: {str(e)[:80]}"}
    if not texte:
        return {"ok": False, "slug": slug, "raison": "document vide (illisible, PAS 'rien')"}
    morceaux = _chunks(texte)[:max_chunks]
    if not morceaux:
        return {"ok": False, "slug": slug, "raison": "0 chunk apres decoupe"}
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_db_path import open_writer
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "slug": slug, "raison": f"writer indispo: {type(e).__name__}"}
    src = f"metier/{slug}"
    dom_url = hashlib.sha256(url.encode()).hexdigest()[:8]
    inseres = 0
    try:
        with open_writer() as con:
            for i, m in enumerate(morceaux):
                cid = "kbdoc_" + hashlib.sha256((kb_domain + dom_url + str(i)).encode()).hexdigest()[:16]
                con.execute(
                    "INSERT OR REPLACE INTO rag_chunks(id, text, source, domain) VALUES(?,?,?,?)",
                    (cid, f"[DOC {slug}] {m}", src, kb_domain))
                inseres += 1
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "slug": slug, "raison": f"insert KO: {type(e).__name__}: {str(e)[:80]}"}
    return {"ok": True, "slug": slug, "kb_domain": kb_domain, "url": url,
            "chars": len(texte), "chunks_inseres": inseres,
            "note": "embedding async via trigger auto (chunks NULL)"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--slug", required=True, help="slug metier (ex: actuaire_statisticien)")
    ap.add_argument("--url", required=True)
    ap.add_argument("--max-chunks", type=int, default=40)
    args = ap.parse_args()
    import json
    print(json.dumps(ingest(args.slug, args.url, args.max_chunks), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
