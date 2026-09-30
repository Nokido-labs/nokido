#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_veille_backlog_github.py — le RETARD de veille, depot par depot.

QUESTION OWNER (2026-08-31) : « rattraper toutes les veilles demandees sur les
depots GitHub depuis le debut (mars) ». Pour y repondre il faut un DENOMINATEUR,
et il n'existait pas : les outils en place mesurent chacun un NUMERATEUR.

  - `forge_veille_audit`         : les watch_jobs lances (veille thematique SearXNG).
  - `forge_veille_gap_recover`   : les URLs deja en biblio_raw et sans contenu RAG.
  - `forge_veille_clone_ingest`  : les 12 depots CABLES EN DUR dans son dict REPOS.
  - `forge_veille_github_direct` : les depots d'une campagne, en dur eux aussi.

Aucun ne sait ce que l'owner a DEMANDE. Un depot nomme dans une conversation et
jamais recopie dans un dict est invisible pour les quatre — il n'apparait dans
aucun rapport, pas meme comme manquant. C'est exactement le trou que cet outil
comble : il lit les CONVERSATIONS, en extrait les depots GitHub cites, et les
rapproche de ce qui est reellement en base.

Il ne juge pas et n'ingere rien : il RAPPROCHE et laisse voir les trous.

TROIS ETATS, JAMAIS DEUX (cf. RULES_SHARED « ne jamais conclure d'une source qui
se tait ») : un depot est `INGERE`, `ABSENT`, ou `ILLISIBLE` (corpus non couvert).
Le rapport imprime son propre denominateur — chunks scannes, domaines retenus et
ECARTES — sans quoi « aucune demande trouvee » ne se distingue pas de « je n'ai
pas pu regarder ».

Sortie : sandbox/veille_backlog_github.md + resume compact sur stdout.
Usage  : run action=run_job script=tools/forge_veille_backlog_github.py
         (lecture seule ; aucun reseau requis)
"""
from __future__ import annotations

__FORGE_COLOR__ = "digestif/inventaire-veille"

import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
OUT = ROOT / "sandbox" / "veille_backlog_github.md"
# REGISTRE : la cible d'une veille est une DONNEE. Tant qu'elle vit dans un dict
# en dur, chaque campagne reecrit un script (plus de cinquante `veille_*.py`
# one-shot dans C:/tmp en temoignent). Ce fichier est produit par l'inventaire et
# consomme par les trois voies (clone, README, ecosysteme) : une seule liste,
# une seule verite sur ce qui a ete demande et ou on en est.
#
# Sous `sandbox/` et non `config/` : le compte du job (LaForgeSbxOffline) n'a pas
# le droit d'ecrire a la RACINE du depot -- mesure du 31/08, le job sortait en
# rc=1 juste apres le rapport. Le registre est de toute facon REGENERABLE depuis
# la base, il a sa place avec les autres artefacts produits.
REGISTRE = ROOT / "sandbox" / "veille_targets.json"

sys.path.insert(0, str(ROOT))
from nokido_agent.tools.forge_veille_registre import (  # noqa: E402
    AMBIGU,
    MATCH,
    ORPHELIN,
    RegistreInvalide,
    construire_registre,
    dossiers_dumps,
    ecrire_registre,
    noms_dumps,
    rattacher_dumps,
    resoudre_dumps,
)


def _rattacher_dumps_historiques(doc: dict) -> tuple:
    """Pose `nom_dump` sur les cibles dont un dump porte la PREUVE de l'identite.

    POURQUOI ICI. Mesure 2026-08-31 : 339 cibles au registre, 12 dumps dans
    `docs/`, et AUCUN rattachement — le capteur GitHub ne surveillait donc rien.
    Le faire une fois a la main ne tiendrait pas : la prochaine regeneration du
    registre EFFACERAIT `nom_dump`. Le rattachement appartient a l'endroit qui
    ECRIT le registre, pas a une operation ponctuelle.

    La preuve est l'URL portee par `REPOS`, jamais une ressemblance de nom. Les
    etats AMBIGU et ORPHELIN sont NOMMES et laisses tels quels : rattacher un
    dump a la premiere cible venue ferait surveiller le mauvais depot pendant
    des mois, avec des verdicts parfaitement coherents sur la mauvaise cible.
    """
    try:
        from nokido_agent.tools.forge_veille_clone_ingest import _NOM_HISTORIQUE  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        print("[backlog] table des noms historiques ILLISIBLE (%s) : aucun "
              "rattachement pose, le capteur GitHub ne verra aucune cible"
              % type(exc).__name__, flush=True)
        return doc, {}
    # docs/ ET les dossiers hors depot (`sandbox/veille_dumps.dir`, 2026-09-23) :
    # un dump sur E: absent de ce comptage serait un faux ABSENT.
    dumps = noms_dumps(dossiers_dumps(ROOT))
    res = resoudre_dumps(dumps, doc.get("cibles") or {}, _NOM_HISTORIQUE)
    par_etat: dict = {}
    for nom, r in res.items():
        par_etat.setdefault(r["etat"], []).append(nom)
    print("[backlog] dumps historiques : %d vus — %d MATCH, %d AMBIGU, %d ORPHELIN"
          % (len(dumps), len(par_etat.get(MATCH, [])), len(par_etat.get(AMBIGU, [])),
             len(par_etat.get(ORPHELIN, []))), flush=True)
    for etat in (AMBIGU, ORPHELIN):
        for nom in sorted(par_etat.get(etat, [])):
            print("    %-9s %-24s %s" % (etat, nom, res[nom].get("preuve")),
                  flush=True)
    return rattacher_dumps(doc, res), res

# Un depot dont le nom ne passe pas la forme canonique `org/nom` n'entre PAS au
# registre -- mais il est COMPTE et NOMME. Le laisser passer ferait echouer la
# validation a l'ecriture et perdrait les 341 autres ; le taire ferait croire a
# une extraction complete.
_RE_REPO_VALIDE = re.compile(r"^[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*$")

# Un depot GitHub cite : github.com/<org>/<nom>. On refuse les chemins profonds
# (blob/, tree/, issues/) en ne gardant que les deux premiers segments.
_RE_REPO = re.compile(
    r"github\.com/([A-Za-z0-9][\w.-]{0,38})/([A-Za-z0-9][\w.-]{0,99})", re.I)

# Depots qui ne sont PAS une demande de veille : outillage cite en passant.
# Liste courte et EXPLICITE — un filtre large masquerait de vraies demandes.
_BRUIT = {
    "anthropics/claude-code", "openai/openai-python", "python/cpython",
    "actions/checkout", "actions/setup-python", "git/git",
    "microsoft/vscode", "pypa/pip", "nodejs/node",
}

# Depots FICTIFS : les placeholders des exemples de documentation. Ils passent
# toutes les regex parce qu'ils sont bien formes, et ils gonflent le retard d'une
# dizaine d'entrees qu'aucun clone ne pourra jamais satisfaire.
_FICTIFS = {
    "owner/repo", "user/repo", "org/repo", "x/repo", "owner/name",
    "ton_user/ton_repo", "ton_user/tenacity", "utilisateur/mon-projet",
    "your-org/your-repo", "username/repo", "monorg/monrepo",
}

# `github.com/<x>/<y>` ne designe pas toujours un depot : l'interface du site
# occupe le meme espace de noms. Mesure de la 1re passe : `settings/tokens`,
# `resources/articles` et `en/copilot` etaient comptes comme des depots ABSENTS,
# ce qui GONFLE le retard dans le sens qui m'arrange (« regardez tout ce qui
# manque »). Un chiffre flatteur se verifie avant d'etre rapporte.
_RESERVE_GH = {
    "settings", "resources", "features", "orgs", "sponsors", "topics", "apps",
    "marketplace", "notifications", "pricing", "security", "about", "enterprise",
    "collections", "explore", "login", "join", "pulls", "issues", "search",
    "codespaces", "customer-stories", "readme", "en", "fr", "site", "contact",
    "repos", "rest", "user", "users", "orgs-", "graphql", "sponsors-",
    "advisories", "user-attachments", "solutions", "v3", "assets", "raw",
}

# Le depot MAISON n'est pas une veille : Nokido cite sa propre URL a longueur de
# conversation (x771 en 1re passe). Le compter en « jamais ingere » est absurde —
# son code EST le depot de travail.
_ORGS_MAISON = {"user", "laforge", "nokido"}


def _classe(plein: str) -> str:
    """`externe` (candidat veille) · `maison` · `reserve` (chemin d'interface)."""
    org = plein.split("/", 1)[0].lower()
    if org in _RESERVE_GH:
        return "reserve"
    if org in _ORGS_MAISON:
        return "maison"
    return "externe"
# Suffixes parasites colles par la ponctuation d'une phrase ou d'un markdown.
# Le tiret vient des URLs coupees en fin de ligne : `HeyPuter/firefox-` et
# `HeyPuter/firefox-wasm` ressortaient comme DEUX depots distincts.
_QUEUE = (".git", ")", "].", ".", ",", ";", ":", "'", '"', "»", "*", "_", "-")

# `api.github.com/repos/<org>/<nom>` : la regex y lisait `repos/<org>`, ce qui
# fabriquait des depots inexistants (`repos/ggml-org`, `rest/repos`). On ramene
# la forme API a la forme web AVANT extraction.
_RE_API = re.compile(r"api\.github\.com/repos/", re.I)

# Les chunks conversationnels portent leur role EN TETE du texte (`[user] ...`).
# Sans cette lecture, une URL que J'AI moi-meme citee compte comme une demande de
# l'owner — le retard se gonfle de mes propres sorties.
_RE_ROLE = re.compile(r"^\s*\[(user|assistant|system)\]\s*(.?)")
# `[user] [MONITOR]`, `[user] [RESCUE]`, `[user] [claude-hook]` : un tour `user`
# dont le contenu ouvre sur un second crochet est une INJECTION machine (hook,
# moniteur, rappel systeme), pas une phrase de l'owner.
_INJECTE = "["


def _propre(nom: str) -> str:
    n = nom.strip()
    change = True
    while change and n:
        change = False
        for q in _QUEUE:
            if n.lower().endswith(q) and len(n) > len(q):
                n, change = n[: -len(q)], True
    return n


def _date(v) -> str:
    """created_at est tantot ISO, tantot un epoch en TEXTE (mesure 2026-08-31).

    Traiter les deux comme une chaine triait « 1788127397 » avant « 2026-03-… » :
    la premiere demande d'un depot en devenait fausse sans que rien ne le signale.
    """
    s = str(v or "").strip()
    if not s:
        return ""
    if s.isdigit() and len(s) >= 9:
        try:
            return datetime.fromtimestamp(int(s), timezone.utc).isoformat()[:10]
        except (OverflowError, OSError, ValueError):
            # muet-ok : epoch hors bornes ou illisible -> pas de date, ce que
            # l'appelant compte deja dans `borne["sans_date"]`.
            return ""
    return s[:10]


def _domaines(conn) -> tuple[list, list, int]:
    """Domaines conversationnels RETENUS et ECARTES, plus le total scanne."""
    rows = conn.execute(
        "SELECT domain, COUNT(*) FROM rag_chunks GROUP BY domain").fetchall()
    total = sum(n for _, n in rows)
    retenus, ecartes = [], []
    for dom, n in rows:
        d = (dom or "").lower()
        cible = retenus if any(
            m in d for m in ("conv", "session", "transcript", "chat", "dialog")) else ecartes
        cible.append((dom or "(null)", n))
    retenus.sort(key=lambda x: -x[1])
    ecartes.sort(key=lambda x: -x[1])
    return retenus, ecartes, total


def _demandes(conn, domaines: list) -> tuple[dict, int]:
    """Depots cites dans les conversations : premiere date + nombre de mentions."""
    vus: dict = defaultdict(
        lambda: {"premier": "", "mentions": 0, "owner": 0, "agent": 0, "auteurs": set()})
    scannes = 0
    borne: dict = {"min": "", "max": "", "sans_date": 0}
    for dom, _n in domaines:
        cur = conn.execute(
            "SELECT text, created_at, author FROM rag_chunks WHERE domain = ?", (dom,))
        for texte, cree, auteur in cur:
            scannes += 1
            quand = _date(cree)
            # Couverture TEMPORELLE du corpus, mesuree sur tous les chunks lus et
            # pas seulement sur ceux qui citent GitHub : sans elle, « aucune demande
            # avant juin » ne se distingue pas de « le corpus commence en juin ».
            if quand:
                if not borne["min"] or quand < borne["min"]:
                    borne["min"] = quand
                if not borne["max"] or quand > borne["max"]:
                    borne["max"] = quand
            else:
                borne["sans_date"] += 1
            if not texte or "github.com" not in texte:
                continue
            texte = _RE_API.sub("github.com/", texte)
            m = _RE_ROLE.match(texte)
            role = m.group(1) if m else "?"
            est_owner = bool(m) and role == "user" and m.group(2) != _INJECTE
            for org, nom in _RE_REPO.findall(texte):
                plein = "%s/%s" % (org, _propre(nom))
                if plein.lower() in _BRUIT or plein.lower() in _FICTIFS:
                    continue
                e = vus[plein]
                e["mentions"] += 1
                e["owner" if est_owner else "agent"] += 1
                if auteur:
                    e["auteurs"].add(str(auteur)[:24])
                # La 1re date OWNER prime : c'est la date de la DEMANDE. Prendre la
                # 1re mention toutes origines confondues daterait la demande du jour
                # ou un agent a cite le depot, ce qui peut etre bien anterieur.
                if quand and est_owner and (not e["premier"] or quand < e["premier"]):
                    e["premier"] = quand
    return vus, scannes, borne


def _sources_scripts() -> list:
    """Repertoires ou vivent les scripts de campagne.

    `C:/tmp` etait code en dur : le module devenait alors dependant d'un poste
    Windows precis, et sur toute autre machine ce chemin ressortait « absent »
    sans que la difference entre « pas de scratch ici » et « mauvais chemin
    code en dur » soit visible. Surchargeable par `NOKIDO_VEILLE_SCRIPT_DIRS`
    (separateur de chemins du systeme) ; sinon le scratch est celui du systeme.
    """
    surcharge = os.environ.get("NOKIDO_VEILLE_SCRIPT_DIRS", "").strip()
    if surcharge:
        return [Path(p) for p in surcharge.split(os.pathsep) if p.strip()]
    scratch = Path("C:/tmp") if os.name == "nt" else Path(tempfile.gettempdir())
    return [ROOT / "tools", ROOT / "app", scratch]


def _demandes_scripts() -> tuple[dict, dict]:
    """Depots cables en dur dans les scripts de veille.

    POURQUOI cette seconde source. Le corpus conversationnel commence le
    2026-06-08 alors que le depot a ete cree le 2026-03-08 : trois mois de
    demandes n'y sont PAS. Le code, lui, couvre toute la periode — un depot
    nomme dans `ingest_gitingest_batch` ou `ingest_ami_repos` est une demande
    tout aussi reelle qu'une URL collee dans une conversation.

    La date retenue est le mtime du fichier : approximative (un script retouche
    depuis parait recent), et c'est DIT plutot que presente comme une date de
    demande. La `git log --follow` par fichier serait juste mais coute un
    subprocess par fichier sur ~800 fichiers.
    """
    vus: dict = defaultdict(lambda: {"premier": "", "mentions": 0, "fichiers": set()})
    couverture = {"fichiers_lus": 0, "illisibles": 0,
                  "repertoires_absents": [], "repertoires_illisibles": []}
    for base in _sources_scripts():
        # ABSENT et ILLISIBLE demandent des actions differentes : le premier est
        # normal sur une autre machine, le second est un droit manquant qui
        # RETIRE des demandes de l'inventaire sans le dire.
        if not base.exists():
            couverture["repertoires_absents"].append(str(base))
            continue
        try:
            fichiers = sorted(base.glob("*.py"))
        except OSError as exc:  # noqa: BLE001
            couverture["repertoires_illisibles"].append(
                "%s (%s)" % (base, type(exc).__name__))
            continue
        for f in fichiers:
            try:
                texte = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                # muet-ok : ACL / fichier tenu. ILLISIBLE n'est pas « absent » —
                # le compteur `couverture["illisibles"]` est imprime en fin de
                # passe, donc ce chemin laisse bien une trace.
                couverture["illisibles"] += 1
                continue
            couverture["fichiers_lus"] += 1
            if "github.com" not in texte:
                continue
            texte = _RE_API.sub("github.com/", texte)
            try:
                quand = datetime.fromtimestamp(
                    f.stat().st_mtime, timezone.utc).isoformat()[:10]
            except OSError as exc:  # noqa: BLE001
                print("[backlog] mtime illisible sur %s (%s) — date inconnue"
                      % (f.name, type(exc).__name__), flush=True)
                quand = ""
            for org, nom in _RE_REPO.findall(texte):
                plein = "%s/%s" % (org, _propre(nom))
                if plein.lower() in _BRUIT or plein.lower() in _FICTIFS:
                    continue
                e = vus[plein]
                e["mentions"] += 1
                e["fichiers"].add(f.name)
                if quand and (not e["premier"] or quand < e["premier"]):
                    e["premier"] = quand
    return vus, couverture


def _ingere_direct(conn) -> dict:
    """Depots ingeres par la voie README (`forge_veille_github_direct`)."""
    out: dict = {}
    illisibles = 0
    cur = conn.execute(
        "SELECT meta FROM rag_chunks WHERE domain = 'watch_veille' AND meta IS NOT NULL")
    for (meta,) in cur:
        try:
            d = json.loads(meta)
        except (TypeError, ValueError):
            # Un meta illisible fait paraitre un depot ABSENT alors qu'il est
            # ingere : c'est un faux negatif, il se COMPTE.
            illisibles += 1
            continue
        r = d.get("repo")
        if r:
            out[r.lower()] = out.get(r.lower(), 0) + 1
    if illisibles:
        print("[backlog] %d meta illisibles en watch_veille — autant de faux "
              "« ABSENT » possibles" % illisibles, flush=True)
    return out


# DEUX domaines portent la convention des dumps de clone (mesure 2026-09-05 sur un
# echantillon de `source`) : `sdk_gitingest` ET `veille_code`. N'en lire qu'un fait
# paraitre ABSENTS les depots ingeres par l'autre voie — c'est le defaut qui a
# classe `BerriAI/litellm` ABSENT alors que 92 682 chunks sont en base.
DOMAINES_CLONE = ("sdk_gitingest", "veille_code")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def _prefixes_clones(conn) -> dict:
    """Chunks des dumps de clone, agreges par premier segment de `source`."""
    par: dict = {}
    for dom in DOMAINES_CLONE:
        cur = conn.execute(
            "SELECT source, COUNT(*) FROM rag_chunks WHERE domain = ? GROUP BY source",
            (dom,))
        for src, n in cur:
            p = (src or "").split("/")[0]
            if p:
                par[p] = par.get(p, 0) + n
    return par


def _ingere_clone(conn, pleins) -> dict:
    """Depots ingeres par la voie CLONE. Rend {plein_lower: (chunks, voie)}.

    TROIS voies de preuve, decroissantes — et la voie est REPORTEE dans le rapport,
    parce qu'elles n'ont pas la meme force :

    - `table`     : le dict REPOS relie explicitement le nom local et l'URL GitHub.
                    Seule voie qui PROUVE l'identite du depot.
    - `structure` : le prefixe normalise vaut `owner_repo` — le dump porte les deux
                    moities du nom, la correspondance est structurelle.
    - `ambigu`    : seul le nom de depot correspond, sans son owner. Deux depots
                    homonymes sont indiscernables : on ne conclut donc PAS `INGERE`,
                    on rend INDETERMINE. Un match par nom seul n'est pas une preuve.
    """
    par_prefixe = _prefixes_clones(conn)
    par_norme: dict = {}
    for p, n in par_prefixe.items():
        par_norme.setdefault(_norm(p), []).append((p, n))
    res: dict = {}
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_veille_clone_ingest import REPOS  # noqa: PLC0415

        for local, url in REPOS.items():
            plein = url.rstrip("/").split("github.com/")[-1].lower()
            n = par_prefixe.get(local, 0)
            if n:
                res[plein] = (n, "table")
    except Exception as exc:  # noqa: BLE001 — on le DIT, un import muet fausserait tout
        print("[backlog] dict REPOS illisible (%s) : la voie TABLE est perdue, "
              "les voies structurelles restent" % type(exc).__name__, flush=True)
    for plein in pleins:
        bas = (plein or "").lower()
        if bas in res or "/" not in bas:
            continue
        owner, repo = bas.split("/", 1)
        cle = _norm(owner + "_" + repo)
        if cle in par_norme:
            res[bas] = (sum(v for _, v in par_norme[cle]), "structure")
            continue
        cle = _norm(repo)
        if cle in par_norme:
            res[bas] = (sum(v for _, v in par_norme[cle]), "ambigu")
    return res


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — muet-ok : sortie non reconfigurable, sans effet ici
        pass
    if not DB.exists():
        print("ERR base introuvable:", DB)
        return 2

    conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    retenus, ecartes, total = _domaines(conn)
    if not retenus:
        print("[backlog] ILLISIBLE : aucun domaine conversationnel dans %d chunks. "
              "Le corpus n'est pas absent, il n'est pas COUVERT — ne rien conclure."
              % total)
        conn.close()
        return 3

    demandes, scannes, borne = _demandes(conn, retenus)
    scripts, couv_scripts = _demandes_scripts()
    # Fusion : un depot demande dans une conversation ET cable dans un script
    # garde la PLUS ANCIENNE des deux dates.
    origines: dict = {}
    for plein in demandes:
        origines[plein] = "conv"
    for plein, e in scripts.items():
        if plein in demandes:
            origines[plein] = "conv+script"
            d = demandes[plein]
            d["mentions"] += e["mentions"]
            if e["premier"] and (not d["premier"] or e["premier"] < d["premier"]):
                d["premier"] = e["premier"]
        else:
            origines[plein] = "script"
            demandes[plein] = e
    direct = _ingere_direct(conn)
    clone = _ingere_clone(conn, list(demandes))
    conn.close()

    lignes = []
    for plein, e in demandes.items():
        bas = plein.lower()
        n_clone, voie = clone.get(bas, (0, ""))
        n_direct = direct.get(bas, 0)
        if n_clone and voie == "ambigu":
            etat = "INDETERMINE"
            detail = ("clone %d, correspondance par NOM SEUL — l'owner n'est pas "
                      "porte par le dump, un homonyme est indiscernable" % n_clone)
        elif n_clone:
            etat, detail = "INGERE", "clone %d (%s)" % (n_clone, voie)
        elif n_direct:
            etat, detail = "PARTIEL", "README %d" % n_direct
        else:
            etat, detail = "ABSENT", "-"
        lignes.append({"repo": plein, "premier": e["premier"] or "?",
                       "mentions": e["mentions"], "etat": etat, "detail": detail,
                       "classe": _classe(plein), "origine": origines.get(plein, "?"),
                       "owner": e.get("owner", 0), "agent": e.get("agent", 0),
                       "auteurs": ",".join(sorted(e.get("auteurs") or [])[:3])})
    ecartes_classe = {"maison": 0, "reserve": 0}
    for r in lignes:
        if r["classe"] != "externe":
            ecartes_classe[r["classe"]] += 1
    lignes = [r for r in lignes if r["classe"] == "externe"]
    # Trier par etat (ce qui manque d'abord) puis par nombre de mentions : un depot
    # cite dix fois et jamais ingere est le plus gros trou, il doit sortir en tete.
    rang = {"ABSENT": 0, "PARTIEL": 1, "INDETERMINE": 2, "INGERE": 3}
    # Un depot NOMME PAR L'OWNER passe devant : c'est une demande, le reste est du
    # contexte. Un depot vu uniquement dans un script de campagne compte aussi comme
    # demande (quelqu'un l'a cable exprès), d'ou le `or "script" in origine`.
    def _demande(r):
        return r["owner"] > 0 or "script" in r["origine"]

    lignes.sort(key=lambda r: (0 if _demande(r) else 1, rang[r["etat"]], -r["owner"],
                               -r["mentions"]))

    compte = {"ABSENT": 0, "PARTIEL": 0, "INDETERMINE": 0, "INGERE": 0}
    for r in lignes:
        compte[r["etat"]] += 1

    md = ["# Retard de veille GitHub — demande contre ingere", "",
          "Genere le %s par tools/forge_veille_backlog_github.py (deterministe, 0 LLM)."
          % datetime.now(timezone.utc).isoformat(timespec="seconds"), "",
          "## Denominateur (sans lui, « rien trouve » ne se distingue pas de « pas pu regarder »)",
          "", "- chunks en base : **%d**" % total,
          "- domaines conversationnels RETENUS : **%d** (%s)"
          % (len(retenus), ", ".join("`%s`=%d" % (d, n) for d, n in retenus[:8])),
          "- domaines ECARTES : **%d** (non conversationnels)" % len(ecartes),
          "- chunks conversationnels scannes : **%d**" % scannes,
          "- couverture temporelle du corpus : **%s -> %s** (%d chunks sans date)"
          % (borne["min"] or "?", borne["max"] or "?", borne["sans_date"]),
          "- depots GitHub distincts cites : **%d**" % len(demandes),
          "- ECARTES : %d depots maison, %d chemins d'interface GitHub (non depots)"
          % (ecartes_classe["maison"], ecartes_classe["reserve"]),
          "- retenus comme DEMANDES EXTERNES : **%d**" % len(lignes), "",
          "## Verdict", "",
          "- **ABSENT** (jamais ingere) : %d" % compte["ABSENT"],
          "- **PARTIEL** (README seul, pas le code) : %d" % compte["PARTIEL"],
          "- **INDETERMINE** (un dump porte ce NOM, sans son owner) : %d"
          % compte["INDETERMINE"],
          "- **INGERE** (clone complet) : %d" % compte["INGERE"], "",
          "| depot | 1re demande | origine | owner | agent | etat | detail |",
          "|---|---|---|---|---|---|---|"]
    for r in lignes:
        md.append("| %s | %s | %s | %d | %d | %s | %s |"
                  % (r["repo"], r["premier"], r["origine"], r["owner"], r["agent"],
                     r["etat"], r["detail"]))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(md), encoding="utf-8")

    print("=== RETARD DE VEILLE GITHUB ===")
    print("chunks base %d | conversationnels scannes %d | domaines retenus %d / ecartes %d"
          % (total, scannes, len(retenus), len(ecartes)))
    print("domaines conv :", ", ".join("%s=%d" % (d, n) for d, n in retenus))
    _auteurs: dict = {}
    for r in lignes:
        for a in (r["auteurs"] or "").split(","):
            if a:
                _auteurs[a] = _auteurs.get(a, 0) + 1
    print("cite par :", ", ".join("%s=%d" % (a, n) for a, n in
                                  sorted(_auteurs.items(), key=lambda x: -x[1])[:8])
          or "(aucun auteur renseigne)")
    print("couverture corpus : %s -> %s (%d sans date)"
          % (borne["min"] or "?", borne["max"] or "?", borne["sans_date"]))
    print("scripts : %d lus, %d ILLISIBLES, repertoires absents %s | depots cables %d"
          % (couv_scripts["fichiers_lus"], couv_scripts["illisibles"],
             couv_scripts["repertoires_absents"] or "aucun", len(scripts)))
    _org: dict = {}
    for r in lignes:
        _org[r["origine"]] = _org.get(r["origine"], 0) + 1
    print("origine des demandes :", ", ".join("%s=%d" % kv for kv in sorted(_org.items())))
    print("depots cites %d | ecartes %d maison + %d chemins d'interface | externes %d"
          % (len(demandes), ecartes_classe["maison"], ecartes_classe["reserve"], len(lignes)))
    print("externes -> ABSENT %d | PARTIEL %d | INDETERMINE %d | INGERE %d"
          % (compte["ABSENT"], compte["PARTIEL"], compte["INDETERMINE"],
             compte["INGERE"]))
    _dem = [r for r in lignes if _demande(r)]
    _dem_abs = [r for r in _dem if r["etat"] == "ABSENT"]
    print("DEMANDES (nommees par l'owner ou cablees en script) : %d — dont ABSENT %d"
          % (len(_dem), len(_dem_abs)))
    print("contexte (cite par un agent seulement) : %d" % (len(lignes) - len(_dem)))
    # Liste EXPLOITABLE, une ligne par depot : c'est elle qui alimente le
    # rattrapage (clone/ingest). Un rapport qu'on doit re-parser a la main n'est
    # pas un livrable.
    liste = OUT.parent / "veille_backlog_demandes.txt"
    liste.write_text("\n".join(r["repo"] for r in _dem_abs), encoding="utf-8")

    # Le registre porte TOUS les depots externes cites, pas seulement les
    # demandes : l'owner a tranche le 31/08 « une passe sur l'ensemble des depots
    # cites ». La colonne `priorite` conserve la distinction, pour que l'ordre de
    # traitement reste celui de la valeur et non celui de l'alphabet.
    entrees, mal_formes = [], []
    for r in lignes:
        if not _RE_REPO_VALIDE.match(r["repo"]):
            mal_formes.append(r["repo"])
            continue
        entrees.append({
            "repo": r["repo"],
            "priorite": "demande" if _demande(r) else "contexte",
            "premiere_demande": r["premier"],
            "origine": r["origine"],
            "mentions_owner": r["owner"],
            "mentions_agent": r["agent"],
            "etat": r["etat"],
            "detail": r["detail"],
        })
    doc = construire_registre(
        entrees, source="tools/forge_veille_backlog_github.py",
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    doc, _ = _rattacher_dumps_historiques(doc)
    try:
        ecrire_registre(REGISTRE, doc)
        print("registre : %d cibles, generation %s -> %s"
              % (doc["count"], doc["generation_id"], REGISTRE))
    except (OSError, RegistreInvalide) as exc:  # noqa: BLE001
        # Un registre non ecrit fait travailler l'ingestion sur RIEN (elle est
        # fail-closed) : ce n'est pas une degradation silencieuse, mais il faut
        # savoir POURQUOI pour le corriger.
        print("registre NON ECRIT (%s: %s) — l'ingestion refusera de tourner, "
              "%d cibles indisponibles"
              % (type(exc).__name__, str(exc)[:120], doc["count"]), flush=True)
    for col in doc.get("collisions", []):
        print("  collision %s : %s" % (col.get("type"), col), flush=True)
    if mal_formes:
        print("  %d nom(s) hors forme canonique org/nom, NON inscrits : %s"
              % (len(mal_formes), ", ".join(mal_formes[:8])), flush=True)
    if couverture_illisible := couv_scripts.get("repertoires_illisibles"):
        print("  repertoires de scripts ILLISIBLES (demandes possiblement "
              "manquantes) : %s" % ", ".join(couverture_illisible), flush=True)

    print("\n-- DEMANDES jamais ingerees (%d) --" % len(_dem_abs))
    for r in _dem_abs[:25]:
        print("  %-46s 1re %s  owner x%d / agent x%d  [%s]"
              % (r["repo"], r["premier"], r["owner"], r["agent"], r["origine"]))
    print("  ... liste complete :", liste)
    print("\nrapport:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
