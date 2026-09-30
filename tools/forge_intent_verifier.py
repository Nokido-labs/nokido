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
            # Decoupe aussi sur les puces et numerotations : dans une spec collee,
            # une exigence tient sur une puce, pas sur une phrase ponctuee.
            for ph in re.split(r"[.!?\n]+|(?:^|\s)[-*•]\s+|(?:^|\s)\d+[.)]\s+",
                               bloc[:6000]):
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
                if _RE_MACHINE.search(ph):
                    continue
                cle = re.sub(r"[^a-z0-9]+", " ", ph.lower()).strip()[:110]
                if not cle:
                    continue
                e = vus.setdefault(cle, {"texte": ph, "occurrences": 0,
                                         "vu_le": None, "revu_le": None})
                e["occurrences"] += 1
                # Premiere et DERNIERE fois que la demande a ete formulee. C'est
                # `revu_le` qui arbitre : une consigne reprise en aout prime sur
                # une consigne de juin, et une demande jamais reprise depuis des
                # mois n'a pas le meme poids qu'une demande d'hier.
                if quand:
                    e["vu_le"] = quand if e["vu_le"] is None else min(e["vu_le"], quand)
                    e["revu_le"] = quand if e["revu_le"] is None else max(e["revu_le"], quand)
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


def _main_enonces() -> int:
    print("[verif] extraction des ENONCES owner...", flush=True)
    ens = _enonces()
    print("[verif] %d demandes distinctes" % len(ens), flush=True)
    idx, nfic = _index()
    print("[verif] %d fichiers indexes" % nfic, flush=True)
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
        res.append({"texte": e["texte"], "occurrences": e["occurrences"],
                    "verdict": v, "termes_rares": rares[:10],
                    "fichiers_ancrage": ancrage[:4],
                    "vu_le": e.get("vu_le"), "revu_le": e.get("revu_le")})

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


if __name__ == "__main__":
    sys.exit(main())
