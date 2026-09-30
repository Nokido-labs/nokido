#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_veille_gap_recover.py — le trou entre biblio et contenu RAG.

DIAGNOSTIC (2026-08-16). Le dedup de veille (`forge_biblio_core._compute_payload_hash`,
MD5 de type/title/url/doi) rejette une entree si son hash BIBLIO existe deja.
Mais une URL peut vivre dans `biblio_raw` (metadonnee) SANS que son contenu soit
dans `rag_chunks` (jamais crawle/vectorise, ou purge). La veille la refuse alors
en `duplicate_hash` — le contenu utile n'entre jamais. Mesure : 15 URLs de
veilles « vides » etaient en biblio mais absentes du RAG.

Cet outil trouve TOUTES les URLs connues (biblio_raw + candidats de watch_jobs)
dont AUCUN chunk n'existe dans rag_chunks : le patrimoine de veille reference
mais sans contenu. Avec --crawl, il les re-crawle (le crawl indexe direct,
bypass du dedup biblio). LECTURE SEULE sans --crawl.
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "digestif/veille : comble le trou entre biblio et contenu RAG"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import re
import sqlite3
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "RAG", "embeddings.db")
HUB = os.environ.get("OLLAMA_HOST", "").strip()  # placeholder, hub sur 8766


def _urls_connues(cur) -> set:
    urls = set()
    # biblio_raw
    try:
        for (u,) in cur.execute("SELECT url FROM biblio_raw WHERE url IS NOT NULL AND url<>''"):
            urls.add(u)
    except sqlite3.Error:
        pass
    # candidats des watch_jobs (meme rejetes)
    try:
        for (rj,) in cur.execute("SELECT refined_json FROM watch_jobs WHERE refined_json IS NOT NULL"):
            try:
                d = json.loads(rj)
            except Exception:
                continue
            cands = d.get("candidats", []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
            for c in cands:
                if isinstance(c, dict) and c.get("u"):
                    urls.add(c["u"])
    except sqlite3.Error:
        pass
    return urls


def _norm(u: str) -> str:
    return str(u).strip().lower().rstrip("/")


def _sources_rag(cur) -> set:
    """Ensemble des URLs dont le contenu est en RAG — charge en UNE requete."""
    out = set()
    # GLOB : verifie 2026-09-04, 3427 sources des deux cotes, aucune perte.
    for (src,) in cur.execute("SELECT DISTINCT source FROM rag_chunks WHERE source GLOB 'http*'"):
        if src:
            out.add(_norm(src))
    return out


def _hub_token() -> str:
    try:
        import sys as _s
        _s.path.insert(0, os.path.join(ROOT, "app"))
        from nokido_agent.app.forge_secrets import get_secret
        return get_secret("FORGE_MCP_TOKEN") or ""
    except Exception:
        return get_secret("FORGE_MCP_TOKEN") or ""


_PAUSE_S = float(os.environ.get("NOKIDO_GAP_PAUSE_S", "1.0"))


def _ingerer(url: str) -> str:
    """Ingestion DIRECTE (`forge_web_fetch.fetch_and_ingest`), sans passer par le hub.

    Mesure 2026-08-16, passe 8 : 120 URLs `[vide]` d'affilee, arret rc=3. Ce
    n'etait ni un refus ni une panne — `handle_crawl` n'ingere QUE si la page
    depasse 10 000 caracteres ; en dessous il RETOURNE le markdown a l'appelant
    et n'ecrit rien. Les pages courtes (GitHub, HuggingFace docs) ne pouvaient
    donc structurellement jamais etre rattrapees : le lot revenait identique a
    chaque passe. Meme signature que le GATE_DENIED du matin — un lot qui ne
    bouge pas d'une passe a l'autre est le symptome.

    `fetch_and_ingest` ingere TOUJOURS, quelle que soit la taille. Et comme ce
    job est DETACHE, il l'importe en direct : pas de HTTP vers le hub, pas de
    gate a franchir, aucune charge sur l'event-loop (cf. RCA hub mort du jour).
    """
    try:
        import sys as _s

        _app = os.path.join(ROOT, "app")
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_web_fetch import fetch_and_ingest
    except Exception as exc:  # noqa: BLE001 - module absent : on le DIT
        return "indisponible: %s" % type(exc).__name__
    try:
        res = fetch_and_ingest(url)
    except Exception as exc:  # noqa: BLE001
        return "echec: %s" % str(exc)[:70]
    if not res.get("ok"):
        err = str(res.get("error"))
        # 404/410 = le serveur affirme que la ressource N'EXISTE PAS. Ce n'est pas
        # une panne passagere : la reessayer indefiniment est pur gaspillage, et
        # cela condamne les URLs VALIDES du meme domaine via la quarantaine.
        m = re.search(r"HTTP Error (\d{3})", err)
        if m and m.group(1) in ("404", "410"):
            return "mort:%s" % m.group(1)
        if m and m.group(1) == "429":
            # « Too Many Requests » est un ORDRE du serveur, pas un incident a
            # retenter : mesure du 2026-08-17, HuggingFace sert ~26 pages puis
            # coupe. Insister 5 fois brule les creneaux ET aggrave la limite.
            return "limite:429"
        return "echec: %s" % err[:70]
    return "ok" if int(res.get("chunks") or 0) > 0 else "vide"


def _crawl(url: str, timeout: int = 40) -> str:
    """Crawl via le verbe MCP du hub (tools/call name=crawl) : indexe direct.

    Deux corrections mesurees le 2026-08-16, apres 240 crawls annonces « ok » qui
    n'avaient ecrit AUCUN chunk :

    - Identite : `VEILLE_GAP` est ring 4 alors que `crawl` exige ring 3 ; toutes
      les requetes revenaient `GATE_DENIED`. `DAEMON` porte le ring necessaire et
      reste l'identite juste pour un job detache (ne pas usurper `CLAUDE`).
    - Verdict : un `GATE_DENIED` voyage dans un `result` JSON-RPC parfaitement
      valide. Tester la presence de `"result"` revenait donc a appeler succes tout
      refus poli. On exige desormais la preuve d'indexation, et le refus a son
      propre verdict pour que l'appelant puisse arreter au lieu de marteler.
    """
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "crawl",
                                  "arguments": {"url": url, "timeout": timeout}}}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8766/mcp", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + _hub_token(),
                 "X-Agent-Name": "DAEMON"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout + 20) as r:
            raw = r.read().decode("utf-8", errors="replace")
        if "GATE_DENIED" in raw:
            return "gate_denied"
        if "index" in raw and "chunk" in raw:
            return "ok"
        return "vide"
    except Exception as exc:
        return "echec: %s" % str(exc)[:70]


# Nombre d'echecs sur un MEME domaine avant de le mettre de cote pour la passe.
_MAX_ECHECS_DOMAINE = 5

# Domaines a ne plus solliciter avant une date, apres un 429. Vit au niveau
# MODULE a dessein : les passes successives tournent dans le MEME process, elles
# heritent donc du cooldown au lieu de re-marteler un serveur qui vient de dire
# stop. Mesure du 2026-08-17 : HuggingFace sert ~26 pages puis coupe, et 96 % du
# retard de veille est sur ce seul domaine — insister ne fait que prolonger la
# coupure.
_COOLDOWN_S = float(os.environ.get("NOKIDO_GAP_COOLDOWN_S", "300"))
_domaine_cooldown: dict = {}


def prochain_creneau() -> float:
    """Secondes restantes avant qu'un domaine au repos redevienne interrogeable.

    Mesure du 2026-08-17 : apres une passe productive (~100 pages), DEUX passes
    tournaient a vide — 14 tentatives sur des domaines morts, 596 URLs differees
    — parce que la pause entre passes (90 s) est plus courte que le cooldown
    (300 s). Chaque passe a vide coute pourtant un scan complet de la base.
    L'appelant peut desormais attendre la duree REELLE au lieu de bruler des
    passes. Rend 0.0 si aucun domaine n'est au repos.
    """
    if not _domaine_cooldown:
        return 0.0
    reste = max(0.0, min(_domaine_cooldown.values()) - time.time())
    return reste


def _table_mortes(con) -> None:
    """Cree la table SI besoin, puis COMMIT aussitot.

    Sans ce commit, le `CREATE TABLE` (DDL = transaction en ECRITURE) laisse la
    connexion sur un verrou RESERVED pendant toute la passe. `fetch_and_ingest`
    ecrit dans la MEME base : chaque page valide echouait alors en « database is
    locked ». Un simple oubli de commit transformait un rate-limit en blocage
    total du rattrapage.
    """
    con.execute(
        "CREATE TABLE IF NOT EXISTS veille_url_morte ("
        "url TEXT PRIMARY KEY, code INTEGER, vu_le TEXT)"
    )
    con.commit()


def _urls_mortes(con) -> set:
    """URLs dont le serveur a dit qu'elles N'EXISTENT PAS (404/410).

    Mesure du 2026-08-17 : sur 983 URLs « sans contenu », 948 sont sur
    huggingface.co, et le lot est MIXTE — `/docs/about` et `/docs/api` rendent
    404 (fabriquees, jamais existe), tandis que
    `/docs/huggingface_hub/concepts/git_vs_http` se recupere entierement. Comme
    le tri alphabetique place les fabriquees EN TETE, elles declenchaient la
    quarantaine du domaine et empechaient d'atteindre les valides. On les retient
    donc une fois pour toutes, au lieu de les repayer a chaque passe.
    Conforme a la consigne owner : on MARQUE, on ne supprime rien.
    """
    _table_mortes(con)
    return {u for (u,) in con.execute("SELECT url FROM veille_url_morte")}


def _marquer_mortes(con, lot) -> int:
    """Ecrit les URLs mortes EN LOT, et ne meurt pas sur un verrou.

    Une ecriture par URL au fil du crawl entrait en concurrence avec l'ingestion
    (`fetch_and_ingest` ecrit dans la MEME base) : `database is locked` a tue le
    job entier a la premiere collision. Le marquage est un confort d'optimisation,
    jamais une raison d'interrompre un rattrapage : on ecrit une seule fois, en
    fin de passe, et un echec est signale sans propager.
    """
    if not lot:
        return 0
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    try:
        _table_mortes(con)
        con.executemany(
            "INSERT OR REPLACE INTO veille_url_morte (url, code, vu_le) VALUES (?,?,?)",
            [(u, c, now) for (u, c) in lot],
        )
        con.commit()
        return len(lot)
    except sqlite3.OperationalError as exc:
        print("[gap] marquage des URLs mortes reporte : %s" % str(exc)[:60], flush=True)
        return 0


def _domaine(url: str) -> str:
    from urllib.parse import urlparse

    try:
        return urlparse(url).netloc.lower()
    except Exception:  # muet-ok : URL non parsable -> panier commun
        return ""


def _entrelacer_par_domaine(urls: list) -> list:
    """Round-robin sur le domaine : une passe ne peut plus etre monopolisee.

    `sorted(urls)` range les URLs par domaine (tri alphabetique) : les 120
    premieres manquantes etaient TOUTES sur huggingface.co, qui repond 429.
    La passe rendait donc 0 indexation, le garde coupait (rc=3), et la file
    n'avancait pas d'un pouce — passe apres passe, le meme lot. En entrelacant,
    un domaine qui rate-limit ne consomme plus qu'un cran par tour.
    """
    from collections import OrderedDict

    par_dom: "OrderedDict[str, list]" = OrderedDict()
    for u in urls:
        par_dom.setdefault(_domaine(u), []).append(u)
    sortie = []
    while par_dom:
        for dom in list(par_dom):
            sortie.append(par_dom[dom].pop(0))
            if not par_dom[dom]:
                del par_dom[dom]
    return sortie


def main() -> int:
    ap = argparse.ArgumentParser(description="Recupere le contenu de veille manquant en RAG")
    ap.add_argument("--crawl", action="store_true", help="re-crawle les URLs manquantes")
    ap.add_argument("--max", type=int, default=40, help="plafond de crawls par passe")
    a = ap.parse_args()

    # timeout : l'ingestion ecrit dans la MEME base ; sans attente, la moindre
    # collision rend « database is locked » immediatement.
    con = sqlite3.connect(DB, timeout=30)
    cur = con.cursor()
    urls = _urls_connues(cur)
    rag = _sources_rag(cur)
    mortes = _urls_mortes(con)
    manquantes = _entrelacer_par_domaine(
        [u for u in sorted(urls) if _norm(u) not in rag and u not in mortes]
    )
    if mortes:
        print("[gap] %s URL(s) marquees MORTES (404/410) — ignorees" % len(mortes))
    print("[gap] URLs connues (biblio+watch) : %s | SANS contenu RAG : %s"
          % (len(urls), len(manquantes)))
    for u in manquantes[:60]:
        print("   manque : %s" % u)
    if len(manquantes) > 60:
        print("   ... %s autres" % (len(manquantes) - 60))

    if a.crawl and manquantes:
        print("\n[gap] re-crawl (max %s) ..." % a.max, flush=True)
        from collections import Counter

        ok = denied = tentatives = morte = limite = repos = 0
        lot_mortes = []
        echecs_dom: "Counter[str]" = Counter()
        ignores: set = set()
        for u in manquantes:
            if tentatives >= a.max:
                break
            dom = _domaine(u)
            if dom in ignores:
                continue
            if _domaine_cooldown.get(dom, 0.0) > time.time():
                repos += 1
                continue
            if tentatives:
                # Borne de debit. Le crawl du hub est deja deporte (to_thread),
                # mais chaque page volumineuse declenche une ingestion RAG
                # (chunking + embeddings) : enchainer 120 crawls sans respirer a
                # fait monter le lag de l'event-loop a 1,3 s le 2026-08-16.
                # Ce n'est pas ce qui a tue le hub ce jour-la (RCA : list_providers
                # et le coffre), mais c'est une pression gratuite : ce job n'est
                # PAS urgent, il rattrape un retard de plusieurs semaines.
                time.sleep(_PAUSE_S)
            tentatives += 1
            r = _ingerer(u)
            if r == "ok":
                ok += 1
                echecs_dom.pop(dom, None)
            elif r.startswith("limite:"):
                # Le serveur a explicitement demande d'arreter : on le met de cote
                # pour cette passe ET pour les suivantes, le temps du cooldown.
                ignores.add(dom)
                _domaine_cooldown[dom] = time.time() + _COOLDOWN_S
                limite += 1
                print("   [limite] %s : 429 — repos %s s, creneaux rendus aux autres"
                      % (dom or "(sans domaine)", int(_COOLDOWN_S)))
            elif r.startswith("mort:"):
                # Le domaine n'est PAS en cause : on retire l'URL du perimetre et
                # on laisse ses voisines valides leur chance.
                morte += 1
                lot_mortes.append((u, int(r.split(":")[1])))
            else:
                if r == "gate_denied":
                    denied += 1
                echecs_dom[dom] += 1
                if echecs_dom[dom] >= _MAX_ECHECS_DOMAINE:
                    # Un domaine qui rate-limit (429) ou tombe ne se resorbe pas
                    # dans la passe : on le met de cote et on rend ses creneaux
                    # aux autres, au lieu de bruler le plafond sur lui seul.
                    ignores.add(dom)
                    print("   [quarantaine] %s : %s echecs — creneaux rendus aux autres domaines"
                          % (dom or "(sans domaine)", echecs_dom[dom]))
            # flush : sans lui, la sortie reste dans le tampon et le job PARAIT
            # fige pendant des minutes alors qu'il ingere — c'est ce qui m'a fait
            # douter d'un correctif qui marchait.
            print("   [%s] %s" % (r[:20], u), flush=True)
            if denied >= 3:
                # Un refus de gate ne se resorbe pas en insistant : il tient a
                # l'identite, pas a l'URL. Marteler 120 fois fabriquerait un
                # rapport rassurant sur zero octet ecrit.
                print("[gap] ARRET : %s refus de gate d'affilee — l'identite "
                      "n'a pas le ring requis par `crawl`." % denied)
                con.close()
                return 2
        marquees = _marquer_mortes(con, lot_mortes)
        print("[gap] %s/%s re-crawles (refus gate: %s, quarantaine: %s, 429: %s, "
              "differees: %s, mortes 404: %s dont %s marquees)"
              % (ok, tentatives, denied, len(ignores), limite, repos, morte, marquees), flush=True)
        if ok == 0 and tentatives and not morte:
            if limite or repos:
                # Un rate-limit n'est PAS un echec du rattrapage : le serveur
                # demande d'attendre. Rendre 3 ici arretait toute la campagne
                # alors qu'il suffisait de laisser passer le cooldown.
                # `repos` couvre le cas suivant, oublie d'abord : a la passe N+1
                # le domaine principal est DEJA au repos, donc aucun 429 n'est
                # rencontre (`limite` vaut 0) et seules des URLs mortes sont
                # tentees. La passe rendait alors « aucune indexation prouvee »
                # et tuait la campagne — alors que 96 % du travail attendait
                # simplement la fin du cooldown.
                print("[gap] rien d'indexe : %s 429, %s URL(s) differees (repos). "
                      "La prochaine passe reprendra apres le cooldown." % (limite, repos))
                con.close()
                return 0
            print("[gap] ARRET : aucune indexation prouvee sur %s tentatives." % tentatives)
            con.close()
            return 3
    elif manquantes:
        print("\n[gap] --crawl pour les recuperer (le crawl indexe direct, bypass dedup biblio)")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
