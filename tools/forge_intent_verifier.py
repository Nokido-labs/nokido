#!/usr/bin/env python3
"""forge_intent_verifier.py — chaque demande owner est-elle DANS LE CODE ?

`forge_intent_miner` repond « le mot-clef apparait-il dans un MESSAGE DE COMMIT ».
Ce n'est pas la question. Un commit raconte une intention ; seul le code dit si
elle a pris. Mesure 2026-08-12 : 485 intentions distinctes sur 24 210 tours owner,
dont 57 sans aucune trace git — mais AUCUNE n'avait ete confrontee au depot.

METHODE (deterministe, zero quota, zero cloud)
==============================================
1. Reutilise `extraire()` du mineur : meme corpus, memes filtres de parole.
2. Construit UN index inverse du code (une seule passe) : terme -> fichiers.
   app/, tools/, tests/, docs/ + sous-dossiers de premier niveau.
3. Pour chaque intention, prend les termes DISCRIMINANTS de ses exemples et
   demande a l'index qui les porte.

Verdict, volontairement prudent :
  ANCRE   >= 2 termes discriminants presents ET un identifiant de code parmi eux
  PRESENT >= 2 termes discriminants presents
  PARTIEL  1 terme
  ABSENT   0 -> la demande n'a laisse AUCUNE trace dans le depot

Un terme discriminant est un token >= 5 caracteres, hors mots outils francais et
hors vocabulaire ubiquitaire du projet (`nokido`, `forge`, `hub`...) : ces mots-la
matchent partout et feraient passer n'importe quoi pour livre. La lecon des 99
faux positifs de la journee est ecrite ici : ne jamais conclure sur un terme
generique.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "sandbox" / "intentions_verifiees.json"
# Registre des demandes owner (owner 17/10 : « a l'avenir aucune demande ne doit se perdre ») : zone PERENNE du
# tableau noir (forge_swarm_blackboard._ZONES_PERENNES, jamais elaguee) + copie locale du dernier passage.
REGISTRE = ROOT / "sandbox" / "demandes_owner_registre.json"
ZONE_DEMANDES = "demandes_owner"

# Mots outils + vocabulaire ubiquitaire : presents partout, donc sans valeur de preuve.
_BANNIS = {
    "alors", "apres", "avant", "avoir", "beaucoup", "cela", "cette", "chaque",
    "comme", "comment", "dans", "depuis", "donc", "elle", "encore", "entre",
    "etre", "faire", "fait", "faut", "hors", "jamais", "leur", "mais", "meme",
    "moins", "notre", "nous", "parce", "pareil", "plus", "pour", "pourquoi",
    "quand", "quoi", "sans", "sera", "seulement", "sous", "sur", "toujours",
    "tous", "tout", "toute", "toutes", "tres", "veux", "voir", "vraiment",
    "avec", "cest", "peut", "bien", "aussi", "deja", "faudrait", "merci",
    # ubiquitaire projet
    "nokido", "laforge", "forge", "code", "fichier", "fichiers", "python",
    "session", "sessions", "agent", "agents", "outil", "outils", "tool",
    "tools", "system", "systeme", "projet", "test", "tests", "error", "erreur",
    "self", "return", "import", "print", "true", "false", "none", "data",
}
_RE_TOK = re.compile(r"[a-z_][a-z0-9_]{4,}")
# Un identifiant de code vaut plus qu'un mot de prose : snake_case ou .py
_RE_IDENT = re.compile(r"^[a-z]+_[a-z0-9_]+$")

_ZONES = ("app", "tools", "tests", "docs", "proxy_deno")
_EXT = {".py", ".ts", ".md", ".toml", ".json", ".ps1", ".bat"}
# AUTO-CONTAMINATION, mesuree le 2026-08-12 : mes propres sorties
# (`docs/demandes_graph*.json`, `sandbox/demandes_verifiees.json`) contiennent le
# TEXTE des demandes. Une fois ecrites, elles sont reindexees au passage suivant,
# chaque demande y retrouve tous ses mots rares, la co-occurrence est garantie et
# tout bascule en PRESENT. Effet mesure : ABSENT 28 -> 25 et PARTIEL 69 -> 45
# sans qu'une ligne de code applicatif n'ait bouge, et les deux exports arrivaient
# EN TETE du PPR. Un outil qui se lit lui-meme se donne raison.
_SKIP = ("__pycache__", "node_modules", ".git", "_attic", "cutover_",
         "RAG_plain_bak", "sandbox/workspace",
         "demandes_graph", "demandes_verifiees", "intentions_verifiees",
         "triage_regressions", "intentions.json")


def _fichiers():
    # La RACINE d'abord : CLAUDE.md, GEMINI.md, INFRA.md, README... c'est la que
    # vivent les REGLES. Sans elle, une consigne parfaitement ecrite passait pour
    # un manque — « anti-dup strict : savoir si ca existe AVANT d'en coder un »
    # est la section 3 de CLAUDE.md, et sortait pourtant en ABSENT. Une demande
    # satisfaite par une regle est satisfaite.
    for f in sorted(ROOT.iterdir()):
        if f.is_file() and f.suffix.lower() in _EXT:
            yield f, f.name
    for z in _ZONES:
        base = ROOT / z
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            rel = f.relative_to(ROOT).as_posix()
            if not f.is_file() or f.suffix.lower() not in _EXT:
                continue
            if any(s in rel for s in _SKIP):
                continue
            yield f, rel


def _index():
    """terme -> set(chemins). Une seule passe sur le depot."""
    idx: dict = {}
    n = 0
    for f, rel in _fichiers():
        try:
            txt = f.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_intent_verifier.py', 105, exc_info=True)
            continue
        n += 1
        for t in set(_RE_TOK.findall(txt)):
            if t in _BANNIS:
                continue
            idx.setdefault(t, set()).add(rel)
    return idx, n


# PONTS DE VOCABULAIRE. L'owner demande en francais courant, le code s'ecrit en
# anglais technique : sans passerelle, une demande PARFAITEMENT satisfaite sort
# en ABSENT. Mesure 2026-08-12, quatre faux manques verifies a la main :
#   « mode dev a acces libre »        -> tools/forge_dev_mode.py (arm/disarm de
#                                        l'escape hatch privileged=true)
#   « une autre VM ... serveur dns »  -> tools/forge_vm_dns.py (VM StackDNS
#                                        AdGuardHome, localhost)
#   « lancement auto brain_worker/Llama » -> forge_llm_ondemand + llama_keeper vivant
#   « couche de droits pour un llm admin » -> app/forge_access_switches.py (ReBAC)
# Envoyer rebatir ces quatre-la aurait produit exactement le doublon que la regle
# anti-duplication interdit. Le pont est DETERMINISTE et court : pas de LLM, pas
# de synonymie devinee — seulement des correspondances constatees.
_PONTS = {
    "dev": ["dev_mode", "privileged", "escape"],
    "libre": ["dev_mode", "privileged"],
    "dns": ["vm_dns", "adguard", "netcfg", "resolver"],
    "doh": ["vm_dns", "adguard", "dnsovertls", "dnscrypt"],
    "dot": ["vm_dns", "adguard", "dnsovertls"],
    "autonome": ["ondemand", "keeper", "autonomous", "wanted"],
    "lancement": ["ondemand", "keeper", "spawn", "launcher"],
    "automatique": ["ondemand", "keeper", "autostart", "wanted"],
    "droit": ["rbac", "access_switches", "ring", "acl"],
    "droits": ["rbac", "access_switches", "ring", "acl"],
    "admin": ["rbac", "privileged", "access_switches"],
    "logger": ["network_logger", "trace_sidecar", "audit"],
    "log": ["network_logger", "trace_sidecar", "audit"],
    "stdio": ["stdio_bridge", "mcp_stdio"],
    "interface": ["web_hub", "dashboard", "widget"],
    "monitoring": ["vitals", "health_diagnostic", "inspector"],
    "notification": ["notify", "postal", "inbox"],
    "token": ["bearer", "vault", "dpapi", "capability"],
    "certificat": ["cert", "tls", "x509"],
    "backend": ["settings", "config", "toml"],
    "emuler": ["mock", "fixture", "simul"],
    "parc": ["netcfg", "equipment", "topology"],
}


def _elargis(termes: list) -> list:
    """Ajoute les identifiants de code correspondant au vocabulaire owner."""
    out = list(termes)
    for t in termes:
        out.extend(_PONTS.get(t, ()))
    vus, res = set(), []
    for t in out:
        if t not in vus:
            vus.add(t)
            res.append(t)
    return res


def _termes(intent: dict) -> list:
    """Termes discriminants d'une intention, tires de ses exemples reels."""
    txt = " ".join(intent.get("exemples") or [])[:4000].lower()
    vus, out = set(), []
    for t in _RE_TOK.findall(txt):
        if t in _BANNIS or t in vus:
            continue
        vus.add(t)
        out.append(t)
    return out[:40]


# Marqueurs d'une DEMANDE. Deux registres, parce que l'owner commande de deux
# facons : de sa propre voix, et en COLLANT une spec (« coller = endosser »,
# regle du 2026-08-12). Une spec collee ne dit pas « je veux » : elle dit
# « doit », « exigence », « objectif », ou pose une puce markdown. Ne chercher
# que le premier registre revenait a ignorer la moitie des commandes.
_RE_IMPERATIF = re.compile(
    r"\b(il faut|faudrait|je veux|j'aimerais|tu dois|n'oublie|noublie|"
    r"corrige|corriges|ajoute|ajoutes|mets|met en|fais|refais|arrete|arrête|"
    r"verifie|vérifie|assure-toi|assure toi|pense a|pense à|attention|"
    r"surtout pas|jamais|toujours|je veu|je vx|remets|repare|répare|"
    r"implemente|implémente|cable|câble|branche|supprime|nettoie|"
    # registre SPEC (copier-coller endosse)
    r"doit|doivent|devra|devront|necessaire|nécessaire|exigence|requis|"
    r"obligatoire|objectif|garantir|assurer|permettre|eviter|éviter|"
    r"interdire|empecher|empêcher|a implementer|à implémenter|a cabler|"
    r"à câbler|todo|on veut|il nous faut|prevoir|prévoir|mettre en place)\b",
    re.IGNORECASE)

# CONTAMINATIONS. Tout ce qui traverse un tour owner n'est pas sa parole : il y
# passe aussi mes comptes rendus, des messages de service, des fragments de
# tableaux et des extraits de code numerotes. Mesure 2026-08-12 : la liste des
# manques etait polluee par « SSH_HOST obligatoire » (132 fois — un message de
# service), « py  3121 chars -> disque TODO » (une cellule de tableau) et
# « 2c382 toujours present) » (un bout de hash). Chacun de ces faux manques
# aurait envoye travailler sur du vide.
_RE_MA_VOIX = re.compile(
    r"^\s*(py:|\d+:|\[|--- )|gate (vert|rouge)|reste non verifie|"
    r"\brc=\d|\bok\b.*\bcommit\b|^\s*[A-Za-z_/\\.]+\.py:\d+", re.IGNORECASE)
_RE_CONTAMINE = re.compile(
    r"\s{4,}"                       # alignement de tableau / colonnes
    r"|\bchars\b\s*->"              # « 3121 chars -> disque »
    r"|^\s*(py|rst|md|json|toml|txt|yml|yaml|log)\b\s"   # cellule = extension seule
    r"|^\s*\\n\s*\d+:"              # extrait de source numerote
    r"|\bobligatoire\b.*⚠|⚠.*\bobligatoire\b"           # message de service
    r"|^[0-9a-f]{4,}\b"             # fragment de hash
    r"|\bTODO\s*$"                  # cellule TODO
    r"|done_when:|^\s*toml\s*\(",
    re.IGNORECASE)


def _instant(quand):
    """Un instant comparable quelle que soit la surface : le RAG date en epoch (entier, rendu tel quel), la capture en
    ISO (converti en epoch, UTC si sans fuseau). Illisible -> None : jamais une date inventee."""
    if quand is None or isinstance(quand, (int, float)):
        return quand
    try:
        from datetime import datetime, timezone
        d = datetime.fromisoformat(str(quand).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:  # muet-ok : une date illisible vaut None, que _date affiche « ? » -- jamais une date inventee
        return None


def _date(quand) -> str:
    import time
    q = _instant(quand)
    return time.strftime("%Y-%m-%d", time.gmtime(q)) if q is not None else "?"


def _norme(phrase: str) -> str:
    """Cle de deduplication d'une demande : la meme pour toutes les surfaces et pour le registre."""
    return re.sub(r"[^a-z0-9]+", " ", str(phrase).lower()).strip()[:110]


def _accumuler(vus: dict, bloc: str, quand, re_machine, surface: str = "") -> None:
    """Ajoute a `vus` les phrases-demandes d'UN tour owner, quelle que soit la surface qui l'a recu (conversation
    ingeree au RAG ou tour capture en direct) : meme decoupe, memes filtres, meme cle de deduplication."""
    quand = _instant(quand)
    # Decoupe aussi sur les puces et numerotations : dans une spec collee,
    # une exigence tient sur une puce, pas sur une phrase ponctuee.
    for ph in re.split(r"[.!?\n]+|(?:^|\s)[-*•]\s+|(?:^|\s)\d+[.)]\s+", bloc[:6000]):
        if not ph:
            continue
        ph = ph.strip()
        if not (20 <= len(ph) <= 600) or not _RE_IMPERATIF.search(ph):
            continue
        if _RE_MA_VOIX.search(ph) or _RE_CONTAMINE.search(ph):
            continue
        # PREMIER JET : on rappelait ici `_est_parole_owner`. Double filtre
        # redondant — la phrase vient DEJA d'un tour owner — et il coupait
        # tout : 96 demandes retenues sur 24 210 tours, toutes a 1
        # occurrence (donc la deduplication ne fusionnait rien : il n'y
        # avait presque rien a fusionner). Seul le rejet de la matiere
        # MACHINE (logs, JSON, diffs colles) reste justifie.
        if re_machine.search(ph):
            continue
        cle = _norme(ph)
        if not cle:
            continue
        e = vus.setdefault(cle, {"texte": ph, "occurrences": 0, "vu_le": None, "revu_le": None})
        e["occurrences"] += 1
        if surface:
            e.setdefault("surfaces", set()).add(surface)
        # Premiere et DERNIERE fois que la demande a ete formulee. C'est
        # `revu_le` qui arbitre : une consigne reprise en aout prime sur
        # une consigne de juin, et une demande jamais reprise depuis des
        # mois n'a pas le meme poids qu'une demande d'hier.
        if quand:
            e["vu_le"] = quand if e["vu_le"] is None else min(e["vu_le"], quand)
            e["revu_le"] = quand if e["revu_le"] is None else max(e["revu_le"], quand)


def _enonces() -> list:
    """Les DEMANDES owner, une par une, dedupliquees.

    L'unite d'analyse du mineur est la signature `verbe:objet` : elle fond
    24 210 tours en 485 etiquettes (`executer:ci` en agrege 440 a lui seul). Une
    etiquette pareille trouve TOUJOURS un ancrage dans le depot — la verification
    ne veut alors plus rien dire. On redescend donc au grain de la phrase
    reellement prononcee, seule unite ou « cette demande a-t-elle pris ? » a un sens.
    """
    import sqlite3

    from nokido_agent.tools.forge_intent_miner import RAG_DB, _RE_MACHINE, _RE_TOUR_OWNER

    con = sqlite3.connect(f"file:{RAG_DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT text, created_at FROM rag_chunks "
        "WHERE source LIKE 'conv_%' OR source LIKE 'agy%'"
    ).fetchall()
    con.close()
    vus: dict = {}
    for (txt, quand) in rows:
        if not txt:
            continue
        for bloc in _RE_TOUR_OWNER.split(txt)[1:]:
            _accumuler(vus, bloc, quand, _RE_MACHINE)
    return sorted(vus.values(), key=lambda x: -x["occurrences"])


def _capture_db():
    """Base des tours captures EN DIRECT par les clients (cli_capture_lib.DB), ou None si illisible."""
    try:
        from nokido_agent.tools import cli_capture_lib
        return cli_capture_lib.DB
    except Exception as e:
        print("[registre] base de capture introuvable (%s %s)" % (type(e).__name__, e), flush=True)
        return None


def _capture_spool():
    """Spool des tours que la base de capture a REFUSES (cli_capture_lib, 17/10) : ils comptent comme les autres."""
    return ROOT / "sandbox" / "cli_capture_spool.jsonl"


def _enonces_du_spool(vus: dict, re_machine) -> int:
    """Ajoute a `vus` les tours owner du spool ; rend le nombre de lignes illisibles (DITES par l'appelant)."""
    p = Path(_capture_spool())
    if not p.exists():
        return 0
    n = 0
    for ligne in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            t = json.loads(ligne)
        except ValueError:
            n += 1
            continue
        if t.get("role") == "user":
            _accumuler(vus, str(t.get("content") or ""), t.get("ts"), re_machine, surface="cli_%s" % t.get("surface"))
    return n


def _enonces_captures() -> list:
    """Demandes owner des tours CAPTURES EN DIRECT par n'importe quel client (cli_capture_lib -> agent_messages,
    from_agent `cli_<surface>`) : une demande compte sans attendre l'ingestion de sa conversation au RAG.
    Owner 17/10 : « ces outils doivent pouvoir en entree fonctionner sur d'autres cli aussi, tu n'es qu'un client
    parmi d'autres ». Seuls les tours `role=user` comptent : la voix d'un agent n'est jamais une demande."""
    import sqlite3

    from nokido_agent.tools.forge_intent_miner import _RE_MACHINE

    db = _capture_db()
    rows = []
    if db is None or not Path(db).exists():
        print("[registre] base de capture ILLISIBLE (%s) : seuls le spool et les conversations ingerees comptent" % db,
              flush=True)
    else:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
        try:
            rows = con.execute("SELECT from_agent, payload, created_at FROM agent_messages "
                               "WHERE method = 'conversation.turn' AND substr(from_agent, 1, 4) = 'cli_'").fetchall()
        finally:
            con.close()
    vus: dict = {}
    illisibles = 0
    for surface, payload, quand in rows:
        try:
            p = json.loads(payload or "{}")
        except ValueError:
            illisibles += 1
            continue
        if p.get("role") != "user":
            continue
        _accumuler(vus, str(p.get("content") or ""), quand, _RE_MACHINE, surface=surface)
    illisibles += _enonces_du_spool(vus, _RE_MACHINE)
    if illisibles:
        print("[registre] %d tour(s) capture(s) ECARTE(S) : JSON illisible (base ou spool)" % illisibles, flush=True)
    for e in vus.values():
        e["surfaces"] = sorted(e.get("surfaces") or ())
    return sorted(vus.values(), key=lambda x: -x["occurrences"])


def _supersessions(res: list) -> None:
    """Marque les demandes qu'une formulation PLUS RECENTE recouvre.

    Deux demandes qui partagent >= 2 termes rares parlent du meme sujet. Si l'une
    a ete reprise plus tard que l'autre, l'ancienne est `recouverte_par` la
    recente. Sans cela on traite 235 demandes comme simultanees, et l'on risque
    de « satisfaire » une consigne que l'owner a lui-meme remplacee depuis — plus
    nuisible que de ne rien faire. Le schema rag_chunks prevoit d'ailleurs
    `superseded_by` / `active` : le concept existe, il n'etait pas alimente.
    """
    for a in res:
        a["recouverte_par"] = None
        if not a.get("revu_le"):
            continue
        sa = set(a.get("termes_rares") or [])
        if len(sa) < 2:
            continue
        for b in res:
            if b is a or not b.get("revu_le") or b["revu_le"] <= a["revu_le"]:
                continue
            if len(sa & set(b.get("termes_rares") or [])) >= 2:
                a["recouverte_par"] = b["texte"][:70]
                break


def _graphe_universel(res: list) -> dict:
    """Branche les demandes sur `UniversalGraph` (app/forge_graph_universal.py).

    Pourquoi ce moteur plutot qu'un export maison : il porte deja
    `personalized_pagerank`, `communities`, `top_central_nodes`, `to_cytoscape`,
    `to_json` et `to_mermaid`. Reecrire un graphe a cote aurait ete le duplicata
    que la regle anti-duplication interdit.

    Ce que le graphe rend visible, qu'une liste ne peut pas :
      - le PPR pondere par le nombre d'occurrences ET la fraicheur -> quelles
        demandes irriguent le plus le reste, au lieu du simple compte de repetitions ;
      - les communautes -> les demandes qui parlent du meme sujet sans partager
        de mot-clef, donc les chantiers reels derriere des phrases eparses ;
      - les fichiers-carrefour, cites par plusieurs demandes non satisfaites.

    Rend {} si le moteur ou networkx manque : le rapport texte reste produit.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_graph_universal import GraphEdge, GraphNode, UniversalGraph
    except Exception as e:  # noqa: BLE001
        print("[verif] UniversalGraph indisponible (%s) — graphe non construit"
              % type(e).__name__, flush=True)
        return {}

    g = UniversalGraph(name="demandes_owner", directed=True)
    perso, vus_f = {}, set()
    for i, r in enumerate(res):
        nid = "D%d" % i
        g.add_node(GraphNode(id=nid, label=r["texte"][:80], domain="demande",
                             meta={"verdict": r["verdict"],
                                   "occurrences": r["occurrences"],
                                   "revu_le": r.get("revu_le"),
                                   "recouverte_par": r.get("recouverte_par")}))
        # Personnalisation du PPR : une demande NON satisfaite et RECENTE pese
        # plus. Un poids uniforme dirait seulement « qui est cite souvent ».
        poids = {"ABSENT": 4.0, "PARTIEL": 2.0, "PRESENT": 0.5, "ANCRE": 0.2}[r["verdict"]]
        if r.get("recouverte_par"):
            poids *= 0.25          # deja remplacee : elle ne commande plus
        perso[nid] = poids * (1 + min(r["occurrences"], 10) / 10)

        for f in (r.get("fichiers_ancrage") or [])[:4]:
            fid = "F:" + f
            if fid not in vus_f:
                g.add_node(GraphNode(id=fid, label=f, domain="fichier", meta={}))
                vus_f.add(fid)
            g.add_edge(GraphEdge(src=nid, dst=fid, weight=1.0, relation="trace_dans"))
        # Arete de SUPERSESSION : l'ancienne pointe vers celle qui la remplace.
        for j, autre in enumerate(res):
            if r.get("recouverte_par") and autre["texte"][:70] == r["recouverte_par"]:
                g.add_edge(GraphEdge(src=nid, dst="D%d" % j, weight=2.0,
                                     relation="remplacee_par"))
                break

    out: dict = {"stats": g.stats()}
    try:
        # `personalized_pagerank` rend une LISTE de tuples deja triee (pas un
        # dict), et `G` est une @property (pas une methode) : deux erreurs
        # d'appel de ma part, corrigees en lisant la source du moteur plutot
        # qu'en supposant son API.
        ppr = g.personalized_pagerank(perso)
        noeuds = g.G.nodes
        out["ppr_top"] = [{"id": n, "score": s,
                           "label": str(noeuds[n].get("label", n))[:90]}
                          for n, s in ppr[:15] if n in noeuds]
    except Exception as e:  # noqa: BLE001
        out["ppr_erreur"] = "%s: %s" % (type(e).__name__, str(e)[:90])
    try:
        # `communities()` du moteur s'appuie sur label_propagation, qui exige un
        # graphe NON dirige. Le notre l'est (l'arete `remplacee_par` a un sens).
        # On calcule donc sur la vue non dirigee, sans toucher au graphe.
        import networkx as _nx

        comms = list(_nx.community.label_propagation_communities(g.G.to_undirected()))
        out["communautes"] = len(comms)
        out["communautes_taille"] = sorted((len(c) for c in comms), reverse=True)[:8]
    except Exception as e:  # noqa: BLE001
        out["communautes_erreur"] = "%s: %s" % (type(e).__name__, str(e)[:70])
    for nom, fn in (("demandes_graph.json", g.to_json),
                    ("demandes_graph.cyto.json", g.to_cytoscape)):
        try:
            fn(str(ROOT / "docs" / nom))
            out[nom] = True
        except Exception as e:  # noqa: BLE001
            out[nom] = "KO %s" % type(e).__name__
    return out


def _mermaid(res: list, limite: int = 26) -> str:
    """Vue mermaid des demandes NON satisfaites (lecture humaine directe)."""
    import datetime as _d

    def _n(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", s)[:26] or "x"

    lignes = ["graph LR",
              "  classDef absent fill:#3a1414,stroke:#F24F4F,color:#EDEBF4;",
              "  classDef partiel fill:#3a2f14,stroke:#FFC22D,color:#EDEBF4;",
              "  classDef fichier fill:#1C1928,stroke:#3BB2D0,color:#B2AEC4;",
              "  classDef vieux fill:#1C1928,stroke:#6E6A82,color:#6E6A82;"]
    vus_f = set()
    for i, r in enumerate(res):
        if r["verdict"] not in ("ABSENT", "PARTIEL") or i > limite:
            continue
        nid = "D%d" % i
        quand = ""
        if r.get("revu_le"):
            quand = _d.datetime.fromtimestamp(r["revu_le"]).strftime("%d/%m")
        txt = r["texte"][:58].replace('"', "'").replace("\n", " ")
        lignes.append('  %s["%s<br/><i>%s</i>"]' % (nid, txt, quand))
        lignes.append("  class %s %s;" % (
            nid, "vieux" if r.get("recouverte_par") else r["verdict"].lower()))
        for f in (r.get("fichiers_ancrage") or [])[:2]:
            fid = "F" + _n(f)
            if fid not in vus_f:
                lignes.append('  %s["%s"]' % (fid, f))
                lignes.append("  class %s fichier;" % fid)
                vus_f.add(fid)
            lignes.append("  %s -.->|trace| %s" % (nid, fid))
        if r.get("recouverte_par"):
            lignes.append('  %s -->|remplacee par| R%d["%s"]' % (
                nid, i, r["recouverte_par"][:52].replace('"', "'")))
    return "\n".join(lignes)


def main() -> int:
    # Le grain PAR DEFAUT est la demande owner prise une par une : c'est la seule
    # unite ou « cette demande a-t-elle pris ? » a un sens. Le mode agrege par
    # signature reste accessible via --signatures, mais il ne repond pas a la
    # question posee. (Accessoirement, `run_job` ne transmet pas script_args :
    # un mode utile qui depend d'un drapeau ne serait jamais joue en detache.)
    if "--registre" in sys.argv:
        return _main_registre()
    if "--signatures" not in sys.argv:
        return _main_enonces()

    from nokido_agent.tools.forge_intent_miner import extraire

    print("[verif] extraction des intentions...", flush=True)
    intents = extraire()
    if isinstance(intents, dict):
        intents = intents.get("intentions") or list(intents.values())[0]
    print("[verif] %d intentions" % len(intents), flush=True)

    print("[verif] indexation du code...", flush=True)
    idx, nfic = _index()
    print("[verif] %d fichiers, %d termes indexes" % (nfic, len(idx)), flush=True)

    # PREMIER JET FAUX, corrige ici : « >= 2 termes presents quelque part » donnait
    # ANCRE 144 / PRESENT 340 / ABSENT 0 sur 485. Zero demande sans trace, le
    # lendemain d'une journee a en corriger 30 : invraisemblable. Sur 3 071 fichiers
    # et 69 254 termes, deux mots de prose francaise se trouvent TOUJOURS. Deux
    # garde-fous, tires des 99 faux positifs de la journee :
    #   1. RARETE — un terme porte par plus de _DF_MAX % des fichiers ne prouve
    #      rien (il est du decor, pas une empreinte de la demande) ;
    #   2. CO-OCCURRENCE — les termes doivent se rencontrer dans un MEME fichier.
    #      Deux mots dans deux coins opposes du depot ne temoignent d'aucun lien.
    _DF_MAX = max(8, int(nfic * 0.02))
    res, compte = [], {"ANCRE": 0, "PRESENT": 0, "PARTIEL": 0, "ABSENT": 0}
    for it in intents:
        termes = _termes(it)
        trouves, preuves, ens = [], {}, []
        for t in termes:
            f = idx.get(t)
            if not f or len(f) > _DF_MAX:      # absent, ou trop banal pour prouver
                continue
            trouves.append(t)
            ens.append(f)
            preuves[t] = sorted(f)[:3]
        # Un fichier qui porte AU MOINS deux termes rares de la meme demande.
        porteurs: dict = {}
        for f in ens:
            for chemin in f:
                porteurs[chemin] = porteurs.get(chemin, 0) + 1
        ancrage = sorted([c for c, n in porteurs.items() if n >= 2])
        ident = [t for t in trouves if _RE_IDENT.match(t)]
        if ancrage and ident:
            v = "ANCRE"
        elif ancrage:
            v = "PRESENT"
        elif trouves:
            v = "PARTIEL"
        else:
            v = "ABSENT"
        compte[v] += 1
        res.append({
            "signature": it.get("signature"),
            "occurrences": it.get("occurrences"),
            "portee": it.get("portee"),
            "jamais_dans_git": it.get("jamais_dans_git"),
            "verdict": v,
            "termes_rares_trouves": trouves[:12],
            "identifiants": ident[:6],
            "fichiers_ancrage": ancrage[:5],
            "preuves": {k: preuves[k] for k in list(preuves)[:6]},
            "exemple": (it.get("exemples") or [""])[0][:300],
        })

    res.sort(key=lambda r: (r["verdict"] != "ABSENT", -(r["occurrences"] or 0)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"compte": compte, "intentions": res},
                              ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    print("  DEMANDES OWNER CONFRONTEES AU CODE")
    print("=" * 70)
    for k in ("ANCRE", "PRESENT", "PARTIEL", "ABSENT"):
        print("  %-8s %4d" % (k, compte[k]))
    orphelines = [r for r in res if r["verdict"] == "ABSENT"]
    jamais = [r for r in orphelines if r.get("jamais_dans_git")]
    print("\n  ABSENTES du code ET du git : %d" % len(jamais))
    print("\n--- les 30 plus reclamees SANS trace dans le code ---")
    for r in orphelines[:30]:
        print("  [%4dx] %-22s %s" % (r["occurrences"], r["signature"] or "?",
                                     r["exemple"][:88].replace("\n", " ")))
    print("\n  ecrit : %s" % OUT)
    return 0


def _verdicts(ens: list, idx: dict, nfic: int) -> tuple:
    """Verdict CODE de chaque enonce (ANCRE / PRESENT / PARTIEL / ABSENT) : un seul calcul, lu par le point des
    enonces et par le registre des demandes."""
    df_max = max(8, int(nfic * 0.02))
    res, compte = [], {"ANCRE": 0, "PRESENT": 0, "PARTIEL": 0, "ABSENT": 0}
    for e in ens:
        termes = _elargis([t for t in dict.fromkeys(_RE_TOK.findall(e["texte"].lower()))
                           if t not in _BANNIS][:25])
        porteurs: dict = {}
        rares = []
        for t in termes:
            f = idx.get(t)
            if not f or len(f) > df_max:
                continue
            rares.append(t)
            for c in f:
                porteurs[c] = porteurs.get(c, 0) + 1
        ancrage = sorted([c for c, n in porteurs.items() if n >= 2])
        ident = [t for t in rares if _RE_IDENT.match(t)]
        v = ("ANCRE" if (ancrage and ident) else "PRESENT" if ancrage
             else "PARTIEL" if rares else "ABSENT")
        compte[v] += 1
        r = {"texte": e["texte"], "occurrences": e["occurrences"],
             "verdict": v, "termes_rares": rares[:10],
             "fichiers_ancrage": ancrage[:4],
             "vu_le": e.get("vu_le"), "revu_le": e.get("revu_le")}
        if e.get("surfaces"):
            r["surfaces"] = list(e["surfaces"])
        res.append(r)
    return res, compte


# ---------------------------------------------------------------------------------------------------------------
# REGISTRE DES DEMANDES OWNER (owner 17/10 : « a l'avenir aucune demande ne doit se perdre, ancre le ! »)
# Mesure du jour : des demandes sans trace dans le code NI suivi au SSoT (la passe native decidee le 16/10, jamais
# profilee). Le point des enonces confronte au CODE ; le registre confronte AUSSI au SSoT et INSCRIT chaque orpheline
# dans la zone PERENNE demandes_owner, cle = empreinte de la phrase : une demande redite reste UNE entree ; elle se
# ferme par un marqueur ([CLOS] ...), jamais par effacement. Entree = TOUTES les surfaces (conversations ingerees et
# tours captures en direct par n'importe quel client) : Claude Code n'est qu'un client parmi d'autres.
# ---------------------------------------------------------------------------------------------------------------
_RE_CLOS = re.compile(r"^\s*(?:(?:P\d|BLOCKER|NEXT|CURRENT)\s*[:\-]\s*)?\[\s*(CLOS|RESOLU|RÉSOLU|FAIT|LIVRE|LIVRÉ|"
                      r"RETRACTE|PERIME|PÉRIMÉ)", re.I)


def cle_demande(texte: str) -> str:
    import hashlib
    return "demande_" + hashlib.sha256(_norme(texte).encode("utf-8")).hexdigest()[:12]


def _termes_demande(texte: str) -> set:
    return {t for t in _RE_TOK.findall(str(texte).lower().replace("_", " ")) if t not in _BANNIS}


def _fusionner(*listes) -> list:
    """Une demande dite sur plusieurs surfaces reste UNE demande : occurrences et surfaces cumulees."""
    vus: dict = {}
    for liste in listes:
        for e in liste:
            k = _norme(e["texte"])
            if k not in vus:
                vus[k] = dict(e, surfaces=list(e.get("surfaces") or []),
                              vu_le=_instant(e.get("vu_le")), revu_le=_instant(e.get("revu_le")))
                continue
            a = vus[k]
            a["occurrences"] += e.get("occurrences") or 0
            a["surfaces"] = sorted(set(a["surfaces"]) | set(e.get("surfaces") or []))
            for champ, choix in (("vu_le", min), ("revu_le", max)):
                q = _instant(e.get(champ))
                if q is not None:
                    a[champ] = q if a.get(champ) is None else choix(a[champ], q)
    return sorted(vus.values(), key=lambda x: -x["occurrences"])


def demandes_sans_suivi(res: list, suivis: list, seuil: float = 0.5) -> list:
    """Demandes SANS trace dans le code (ABSENT, PARTIEL) ET sans suivi au SSoT. Un fait du registre lui-meme ne vaut
    suivi que par sa CLE : apparier par les mots le texte d'une demande inscrite ferait passer pour suivie toute
    demande voisine -- un registre qui se lit lui-meme se donne raison (meme piege que _SKIP)."""
    cles = {s.get("cle") for s in suivis}
    index: dict = {}
    for i, s in enumerate(suivis):
        if s.get("registre"):
            continue
        for t in _termes_demande("%s %s" % (s.get("cle", ""), s.get("titre", ""))):
            index.setdefault(t, set()).add(i)
    orph = []
    for r in res:
        if r.get("recouverte_par") or r.get("verdict") in ("ANCRE", "PRESENT"):
            continue
        if cle_demande(r["texte"]) in cles:
            continue
        t = _termes_demande(r["texte"])
        meilleur = 0
        if len(t) >= 2:
            par_suivi: dict = {}
            for w in t:
                for i in index.get(w, ()):
                    par_suivi[i] = par_suivi.get(i, 0) + 1
            meilleur = max(par_suivi.values(), default=0)
        if meilleur >= 2 and meilleur / len(t) >= seuil:
            continue
        orph.append(r)
    return orph


def _suivis_ssot() -> list:
    """Tous les suivis lisibles du tableau noir. LEVE si le registre lui-meme est illisible : inscrire sans l'avoir lu
    ecraserait les marqueurs de tri ([CLOS] -> [A TRIER])."""
    from nokido_agent.app import forge_swarm_blackboard as B
    out = []
    for zone in ("architecture_rules", "active_bugs", "discovered_facts", "mission", ZONE_DEMANDES):
        try:
            r = B.read_zone(zone, limit=20000)
        except Exception as e:
            if zone == ZONE_DEMANDES:
                raise
            print("[registre] zone %s ILLISIBLE (%s) : ses suivis ne comptent pas" % (zone, type(e).__name__), flush=True)
            continue
        for f in (r.get("facts", r) if isinstance(r, dict) else r) or []:
            v = str(f.get("value", ""))
            out.append({"cle": str(f.get("key", "")), "titre": v[:400], "registre": zone == ZONE_DEMANDES,
                        "statut": "clos" if _RE_CLOS.match(v) else "ouvert"})
    return out


def _ecrire_fait(zone: str, fact: str, **kw) -> dict:
    from nokido_agent.app import forge_swarm_blackboard as B
    return B.apply_fact_sync(zone, fact, **kw)


def inscrire_demandes(orph: list, ecrire=None) -> dict:
    """Une entree par demande, cle = empreinte de la phrase (idempotent). ring=2 : ACL de la zone, comme active_bugs."""
    import time
    ecrire = ecrire or _ecrire_fait
    jour = time.strftime("%Y-%m-%d")
    compte = {"ok": 0, "refus": 0}
    for r in orph:
        fait = "[A TRIER %s] « %s » (x%d ; dite du %s au %s ; trace code %s ; surfaces %s)" % (
            jour, r["texte"][:600], r.get("occurrences") or 1, _date(r.get("vu_le")),
            _date(r.get("revu_le")), r.get("verdict"), ",".join(r.get("surfaces") or []) or "conversations")
        res = ecrire(ZONE_DEMANDES, fait, key=cle_demande(r["texte"]), category="demande_owner", ring=2,
                     source="forge_intent_verifier")
        if (res or {}).get("error"):
            compte["refus"] += 1
            print("[registre] REFUS d'inscription : %s" % res.get("error"), flush=True)
        else:
            compte["ok"] += 1
    return compte


def _main_enonces() -> int:
    print("[verif] extraction des ENONCES owner...", flush=True)
    ens = _enonces()
    print("[verif] %d demandes distinctes" % len(ens), flush=True)
    idx, nfic = _index()
    print("[verif] %d fichiers indexes" % nfic, flush=True)
    res, compte = _verdicts(ens, idx, nfic)

    res.sort(key=lambda r: ({"ABSENT": 0, "PARTIEL": 1, "PRESENT": 2, "ANCRE": 3}[r["verdict"]],
                            -r["occurrences"]))
    _supersessions(res)
    recouvertes = sum(1 for r in res if r.get("recouverte_par"))
    out = ROOT / "sandbox" / "demandes_verifiees.json"
    out.write_text(json.dumps({"compte": compte, "recouvertes": recouvertes,
                               "demandes": res},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    mmd = ROOT / "docs" / "demandes_graph.mmd"
    mmd.parent.mkdir(parents=True, exist_ok=True)
    mmd.write_text(_mermaid(res), encoding="utf-8")
    infos = _graphe_universel(res)
    print("\n" + "=" * 70)
    print("  DEMANDES OWNER, UNE PAR UNE, CONFRONTEES AU CODE")
    print("=" * 70)
    for k in ("ABSENT", "PARTIEL", "PRESENT", "ANCRE"):
        print("  %-8s %5d" % (k, compte[k]))
    dates = [r for r in res if r.get("revu_le")]
    print("  %-8s %5d  (dont %d recouvertes par une formulation plus recente)"
          % ("datees", len(dates), recouvertes))
    print("  graphe  : %s" % mmd)
    if infos:
        print("  UniversalGraph : %s | communautes=%s"
              % (infos.get("stats"), infos.get("communautes", "?")))
        for e in infos.get("ppr_top", [])[:10]:
            print("     PPR %.5f  %s" % (e["score"], e["label"][:78]))
        if infos.get("ppr_erreur"):
            print("     PPR indisponible : %s" % infos["ppr_erreur"])
    print("\n--- SANS AUCUNE TRACE dans le code (les 40 plus repetees) ---")
    for r in [x for x in res if x["verdict"] == "ABSENT"][:40]:
        print("  [%3dx] %s" % (r["occurrences"], r["texte"][:104].replace("\n", " ")))
    print("\n--- TRACE FAIBLE : un seul terme rare (les 25 plus repetees) ---")
    for r in [x for x in res if x["verdict"] == "PARTIEL"][:25]:
        print("  [%3dx] %-78s | %s" % (r["occurrences"], r["texte"][:78].replace("\n", " "),
                                       ",".join(r["termes_rares"][:3])))
    print("\n  ecrit : %s" % out)
    return 0


def _main_registre() -> int:
    """Passe du registre (declenchee chaque nuit en NREM1 par le superviseur) : toutes surfaces -> verdict code ->
    croisement SSoT -> inscription des orphelines -> resume. Rend 2 si le registre est illisible (rien ecrit)."""
    import time
    ens = _fusionner(_enonces(), _enonces_captures())
    print("[registre] %d demandes owner distinctes (toutes surfaces)" % len(ens), flush=True)
    idx, nfic = _index()
    res, compte = _verdicts(ens, idx, nfic)
    try:
        _supersessions(res)
    except Exception as e:
        print("[registre] supersessions ILLISIBLES (%s) : aucune demande ecartee comme recouverte" % type(e).__name__)
    try:
        suivis = _suivis_ssot()
    except Exception as e:
        print("[registre] ARRET : registre %s illisible (%s %s) -- rien n'est inscrit" % (ZONE_DEMANDES, type(e).__name__, e),
              flush=True)
        return 2
    orph = demandes_sans_suivi(res, suivis)
    nouvelles = [r for r in orph if cle_demande(r["texte"]) not in {s["cle"] for s in suivis}]
    ins = inscrire_demandes(nouvelles)
    surfaces = sorted({s for r in res for s in (r.get("surfaces") or [])})
    resume = ("[REGISTRE %s] %d demandes owner distinctes ; code %s ; %d sans trace ni suivi, %d inscrites ce passage "
              "(refus %d) ; surfaces capturees en direct : %s ; conversations ingerees : conv_* et agy*. Fermer une "
              "demande = marqueur [CLOS] sur son fait, jamais un effacement." % (
                  time.strftime("%Y-%m-%d %H:%M"), len(res), json.dumps(compte), len(orph), ins["ok"], ins["refus"],
                  ",".join(surfaces) or "aucune"))
    _ecrire_fait(ZONE_DEMANDES, resume, key="resume_registre", category="resume", ring=2, source="forge_intent_verifier")
    REGISTRE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRE.write_text(json.dumps({"resume": resume, "orphelines": orph}, ensure_ascii=False, indent=1, default=list),
                        encoding="utf-8")
    print("BILAN registre demandes=%d orphelines=%d inscrites=%d refus=%d" % (len(res), len(orph), ins["ok"], ins["refus"]),
          flush=True)
    return 0 if not ins["refus"] else 1


if __name__ == "__main__":
    sys.exit(main())
