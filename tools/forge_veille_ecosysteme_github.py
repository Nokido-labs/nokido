"""tools/forge_veille_ecosysteme_github.py — elargissement ECOSYSTEME sans SearXNG.

Suite de la veille dirigee sur sigoden/aichat et GreyDGL/PentestGPT. L'etape
« decouvrir ce qui gravite autour » passe normalement par SearXNG, aujourd'hui a
terre avec Docker (blocker engine sous charge). L'API GitHub rend le meme service
pour ce cas precis : elle CONNAIT le voisinage d'un depot (memes topics, meme
domaine) et repond en JSON, sans conteneur ni moteur de recherche tiers.

QUALIFICATION (mandat owner : « qualifiees et tres pertinentes ; le reste PARQUE ») :
  - on ne prend que des depots au-dessus d'un plancher d'etoiles ET pousses depuis
    moins de 18 mois — un projet mort n'apprend rien sur un ecosysteme vivant ;
  - on ingere la DESCRIPTION et les TOPICS, pas le README entier de chaque voisin :
    a ce stade on cartographie un paysage, on ne lit pas chaque maison ;
  - les depots ecartes sont COMPTES et la raison est dite — sans quoi la couverture
    serait surestimee en silence.

Reseau : `run_job online=true`.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Requetes ciblees sur les DEUX domaines nommes par l'owner.
REQUETES = [
    ("cli_llm", "topic:llm topic:cli", "CLI LLM (voisinage aichat)"),
    ("cli_llm2", "llm chat cli terminal in:name,description", "assistants LLM terminal"),
    ("pentest_llm", "llm pentest OR pentesting in:name,description", "LLM x pentest"),
    ("sec_agent", "topic:security topic:llm-agent", "agents securite"),
]
MIN_ETOILES = 120
FRAICHEUR_MOIS = 18
PAR_REQUETE = 12


def _api(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Nokido-Veille/1.0", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        print(f"  [api] {type(e).__name__}: {str(e)[:110]}", flush=True)
        return None


def main() -> int:
    from nokido_agent.app.forge_db_path import write_retry

    limite = datetime.now(timezone.utc) - timedelta(days=30 * FRAICHEUR_MOIS)
    now = datetime.now(timezone.utc).isoformat()
    retenus, ecartes, motifs = {}, 0, {"peu_etoile": 0, "dormant": 0, "sans_description": 0}

    for cle, q, libelle in REQUETES:
        url = ("https://api.github.com/search/repositories?q="
               + urllib.parse.quote(q) + "&sort=stars&order=desc&per_page=" + str(PAR_REQUETE))
        print(f"[eco] {libelle} — {q}", flush=True)
        d = _api(url)
        if not d or "items" not in d:
            print("  (aucune reponse exploitable)", flush=True)
            continue
        for it in d["items"]:
            nom = it.get("full_name") or ""
            etoiles = int(it.get("stargazers_count") or 0)
            desc = (it.get("description") or "").strip()
            push = (it.get("pushed_at") or "")[:10]
            if etoiles < MIN_ETOILES:
                ecartes += 1; motifs["peu_etoile"] += 1; continue
            if not desc:
                ecartes += 1; motifs["sans_description"] += 1; continue
            try:
                if datetime.fromisoformat(push).replace(tzinfo=timezone.utc) < limite:
                    ecartes += 1; motifs["dormant"] += 1; continue
            except Exception:  # noqa: BLE001
                pass
            if nom not in retenus:
                retenus[nom] = {
                    "nom": nom, "etoiles": etoiles, "desc": desc, "push": push,
                    "topics": it.get("topics") or [], "url": it.get("html_url") or "",
                    "langue": it.get("language") or "?", "axe": libelle}

    print(f"\n[eco] {len(retenus)} depots retenus, {ecartes} ecartes {motifs}", flush=True)

    n = 0
    for nom, r in retenus.items():
        texte = (f"[ecosysteme GitHub — {r['axe']}] {r['nom']} ({r['etoiles']} etoiles, "
                 f"{r['langue']}, dernier push {r['push']})\n{r['desc']}\n"
                 f"topics: {', '.join(r['topics'][:12])}\n{r['url']}")
        cid = "ghe_" + nom.replace("/", "_")
        meta = json.dumps({"repo": nom, "etoiles": r["etoiles"], "topics": r["topics"],
                           "axe": r["axe"], "veille": "ecosysteme_github"}, ensure_ascii=False)
        try:
            write_retry(lambda c, _c=cid, _t=texte, _u=r["url"], _m=meta: c.execute(
                "INSERT OR REPLACE INTO rag_chunks"
                "(id,text,source,domain,role_hint,author,ingested_at,created_at,meta)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (_c, _t, _u, "watch_veille", "veille:ecosysteme",
                 "CLAUDE_VEILLE_ECOSYSTEME", now, now, _m)))
            for tbl in ("rag_chunks_fts", "rag_fts"):
                try:
                    write_retry(lambda c, _tb=tbl, _c=cid, _t=texte, _u=r["url"]: (
                        c.execute(f"DELETE FROM {_tb} WHERE chunk_id=?", (_c,)),
                        c.execute(f"INSERT INTO {_tb}(chunk_id,text,source,domain) "
                                  f"VALUES(?,?,?,?)", (_c, _t, _u, "watch_veille"))))
                except Exception as e:  # noqa: BLE001
                    # rag_chunks_fts est une table CONTENT-BACKED (content='rag_chunks') :
                    # elle n'a pas de colonne chunk_id et se met a jour par trigger.
                    # On le DIT plutot que d'avaler : un lexical muet est un cache perime.
                    # `_tb if False else tbl` : la branche morte n'est jamais
                    # evaluee, donc rien ne levait -- mais elle nomme une variable
                    # qui n'existe pas dans cette portee (`_tb` est le parametre par
                    # defaut du lambda ci-dessus). Residu sans effet, retire.
                    print(f"  [fts:{tbl}] {type(e).__name__}: {str(e)[:70]}", flush=True)
            n += 1
        except Exception as e:  # noqa: BLE001
            print(f"  [db] {nom} refuse ({type(e).__name__}: {str(e)[:70]})", flush=True)

    print(f"\n=== ECOSYSTEME INGERE : {n} depots ===")
    for nom, r in sorted(retenus.items(), key=lambda x: -x[1]["etoiles"])[:20]:
        print(f"  {r['etoiles']:6d} *  {nom:42s} {r['desc'][:64]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
