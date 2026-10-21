"""forge_pair_mcp.py - connecteur MCP des PAIRS cloud (claude.ai, ChatGPT) : lecture + quarantaine.

POURQUOI CE MODULE. Le `/mcp` du hub porte des outils d'action : il n'est JAMAIS expose. Le pont
GitHub (port 8791) sert une lecture de depot. Les pairs cloud ont besoin d'une autre surface :
LIRE l'etat vivant de Nokido et COLLABORER (proposer un fait au SSoT, envoyer un message M2M,
soumettre une tache) -- sans jamais pouvoir faire agir un agent local par eux-memes.

SURFACE FIGEE (NR test_pair_mcp_nr) :
  lecture : etat_corps, point_ssot, recherche_rag, journal_commits, derniere_capsule
  pair    : proposer_fait, envoyer_message, soumettre_tache, lire_reponses
Aucun outil n'execute, n'ecrit dans le depot, ne lit un fichier arbitraire ni un secret.

QUARANTAINE = LE CANAL M2M EXISTANT, pas une file de plus. Un depot de pair entre dans
`agent_messages` (forge_db_path.m2m_path) au statut `quarantaine`, adresse a la boite
`OWNER_APPROBATION` : les clients ne relevent que `unread`, donc rien n'atteint un agent tant que
l'owner n'a pas approuve (tools/forge_pair_quarantaine.py). Chaque depot porte une EtapeContrat
du harness (autorisation UNKNOWN, statut REQUESTED) et NEED_HUMAN_APPROVAL. Les reponses reviennent
par le meme canal, adressees a `PAIR:<client>`. Le texte d'un pair est une DONNEE marquee
EXTERNE_NON_VERIFIEE, jamais une instruction.

SORTIES : bornees, puis redigees -- `redact_tool_output`, plus les formes qu'il ne connait pas
(cle Anthropic, jeton hexadecimal long : mesure du 2026-09-28). Redaction indisponible = rien
n'est rendu (fail-closed).

AUTORISATION : l'autorite OAuth unique (`forge_bridge_oauth`), forcee sur la passerelle des pairs
(`forge_passerelle_pair`) dans ce processus. Ecoute en loopback seulement ; l'URL publique est
ANNONCEE (NOKIDO_PAIR_PUBLIC_URL, https exige), jamais ecoutee.
"""
from __future__ import annotations

__FORGE_COLOR__ = "membrane/connecteur-pair : surface MCP bornee des pairs cloud, lecture et quarantaine"

import datetime
import hashlib
import importlib.util
import json
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_LOG = logging.getLogger("Nokido.PairMCP")

HOTE = "127.0.0.1"
PORT_PAR_DEFAUT = 8793
CHEMIN_HTTP = "/mcp"

OUTILS_LECTURE = ("etat_corps", "point_ssot", "recherche_rag", "journal_commits", "derniere_capsule")
OUTILS_PAIR = ("proposer_fait", "envoyer_message", "soumettre_tache", "lire_reponses",
               "suivre")   # accuses d'un depot du pair (owner 2026-09-29), lecture seule
OUTILS = OUTILS_LECTURE + OUTILS_PAIR

DOMAINES_SSOT = ("roadmap", "rules")
# Le RAG melange sessions, notes internes, code maison et contenus offensifs (mesure du
# 2026-09-28) : ne sortent que des pages publiques, des documentations tierces et la veille.
SOURCES_EXPOSABLES = ("https:", "http:", "docset:", "watch:")
DESTINATAIRES = ("OWNER", "CLAUDE", "ANTIGRAVITY", "GEMINI")
GENRES_TACHE = ("deliberer", "executer")
# Intents qu'un pair cloud peut PORTER -- liste BLANCHE (2026-09-28). Aucun intent qui clot, autorise,
# libere, valide ou reclame un geste : ni OK_DONE, ni LOCK_*, AUTHZ_*, SCOPE_*, NEED_HUMAN_APPROVAL,
# BUDGET_EXCEEDED, REVIEW_OK, PLAN_READY, ERR_*, TRANSIENT_*. Une valeur inattendue tombe dans le REFUS.
INTENTS_MESSAGE_PAIR = ("COLLAB_PING", "NEED_CLARIFY", "REVIEW_FINDING", "REVIEW_UNKNOWN", "FACT_PROPOSED")
INTENTS_PAIR = INTENTS_MESSAGE_PAIR + ("HANDOFF_NEXT",)   # HANDOFF_NEXT : pose par soumettre_tache seul
BOITE_APPROBATION = "OWNER_APPROBATION"
STATUT_QUARANTAINE = "quarantaine"
MAX_SORTIE = 6000
MAX_TEXTE = 4000
DEBIT_PAR_HEURE = 30

_EN_PLUS_DU_PARE_FEU = (re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
                        re.compile(r"\b[0-9a-fA-F]{40,}\b"))


def dossier_sandbox() -> Path:
    return ROOT / "sandbox"


def dossier_capsules() -> Path:
    """Capsules PUBLIEES pour les pairs -- jamais C:/tmp, modifiable par tous les comptes."""
    return dossier_sandbox() / "capsules_pair"


def chemin_rag() -> Path:
    return ROOT / "RAG" / "embeddings.db"


def chemin_politique_rings() -> Path:
    """Politique versionnee des rings des pairs (decision owner 17/10) : config/pairs_rings.json.

    Cle = nom de client OAuth (client_name) -> ring ; sans secret, versionnee avec le depot.
    """
    return ROOT / "config" / "pairs_rings.json"


def chemin_m2m() -> str:
    from nokido_agent.app.forge_db_path import m2m_path
    return m2m_path()


def _maintenant() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def rediger(resultat: dict, outil: str) -> dict:
    """Borne, puis redige. Sans redaction disponible, RIEN n'est rendu (fail-closed)."""
    texte = json.dumps(resultat, ensure_ascii=False, default=str)
    tronque = len(texte) > MAX_SORTIE
    texte = texte[:MAX_SORTIE]
    for motif in _EN_PLUS_DU_PARE_FEU:
        texte = motif.sub("<redige>", texte)
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_tool_output
        texte, _info = redact_tool_output(texte, "pair:" + outil)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erreur": "redaction indisponible (%s) : rien n'est rendu" % type(e).__name__}
    return {"ok": bool(resultat.get("ok", True)), "contenu": texte, "tronque": tronque}


# ── Lecture (liste blanche) ─────────────────────────────────────────────────

def lire_etat_corps() -> dict:
    p = dossier_sandbox() / "health_diagnostic.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        age = time.time() - p.stat().st_mtime
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "etat": "ILLISIBLE", "motif": type(e).__name__}
    manques = [str(g)[:200] for g in (d.get("gaps") or []) if str(g).startswith("❌")][:8]
    return {"ok": True, "score": d.get("score"), "confiance": d.get("confiance"),
            "manques": manques, "age_s": round(age)}


def lire_point_ssot(domaine: str) -> dict:
    if domaine not in DOMAINES_SSOT:
        return {"ok": False, "erreur": "domaine hors liste blanche", "domaines": list(DOMAINES_SSOT)}
    try:
        from nokido_agent.app import forge_ssot
        c = forge_ssot.consult_ssot(domaine)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "etat": "ILLISIBLE", "motif": type(e).__name__}
    return {"ok": c.get("kind") != "absent", "domaine": domaine, "genre": c.get("kind"),
            "age_s": c.get("stale_s"), "artefact": c.get("artifact")}


def _requete_fts(q: str):
    termes = re.findall(r"\w{2,}", q or "")[:8]
    return " ".join('"%s"' % t for t in termes) if termes else None


def rechercher_rag(q: str, limite: int = 5) -> dict:
    fts = _requete_fts(q)
    if not fts:
        return {"ok": False, "erreur": "requete vide"}
    limite = max(1, min(10, int(limite or 5)))
    clause = " OR ".join("source GLOB ?" for _ in SOURCES_EXPOSABLES)
    params = [fts, *[p + "*" for p in SOURCES_EXPOSABLES], limite * 3]
    try:
        con = sqlite3.connect("file:%s?mode=ro" % Path(chemin_rag()).as_posix(), uri=True, timeout=5)
        try:
            lignes = con.execute(
                "SELECT chunk_id, source, snippet(rag_fts, 1, '', '', ' ... ', 24) FROM rag_fts "
                "WHERE rag_fts MATCH ? AND (%s) LIMIT ?" % clause, params).fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        return {"ok": False, "etat": "ILLISIBLE", "motif": type(e).__name__}
    # Defense en profondeur : le filtre SQL est RE-verifie ici, ligne par ligne.
    res = [{"source": s, "extrait": x} for (_c, s, x) in lignes
           if isinstance(s, str) and s.startswith(SOURCES_EXPOSABLES)][:limite]
    return {"ok": True, "resultats": res, "sources_exposables": list(SOURCES_EXPOSABLES)}


def lire_journal_commits(n: int = 10) -> dict:
    n = max(1, min(20, int(n or 10)))
    try:
        p = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "log", "origin/alpha",
                            "-n", str(n), "--date=short", "--format=%h %ad %s"],
                           capture_output=True, text=True, errors="replace", timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "etat": "ILLISIBLE", "motif": type(e).__name__}
    if p.returncode != 0:
        return {"ok": False, "etat": "ILLISIBLE", "motif": "git rc=%d" % p.returncode}
    return {"ok": True, "branche": "origin/alpha (publie)", "commits": p.stdout.splitlines()}


# Regle de depot JOINTE a chaque capsule (owner 2026-10-06, apres le passage public de Nokido-labs/nokido) :
# les capsules ne nommaient pas de depot, et claude.ai poussait ses branches `claude/*` -- commits signes
# Claude, un trailer Co-Authored-By malgre la consigne -- sur le depot de DISTRIBUTION, devenu public.
# La consigne voyage desormais avec CHAQUE capsule, quelle que soit la mission ; et le ruleset
# « aucune autre branche » du depot public refuse de toute facon une branche poussee par l'app.
REGLE_DE_DEPOT = {
    "depot_de_travail": "Nokido-labs/nokido-private",
    "interdit": "Nokido-labs/nokido (public, distribution) : aucune branche, aucun push ; seule la "
                "promotion de l'owner y ecrit",
    "commits": "aucun trailer Co-Authored-By, d'aucun auteur ; un commit qui en porte est refuse a la relecture",
}


def lire_derniere_capsule() -> dict:
    try:
        fichiers = sorted(dossier_capsules().glob("*.capsule.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError as e:
        return {"ok": False, "etat": "ILLISIBLE", "motif": type(e).__name__}
    if not fichiers:
        return {"ok": True, "capsule": None, "note": "aucune capsule publiee pour les pairs"}
    try:
        capsule = json.loads(fichiers[0].read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "etat": "ILLISIBLE", "motif": type(e).__name__}
    return {"ok": True, "capsule": capsule, "fichier": fichiers[0].name, "regle_de_depot": REGLE_DE_DEPOT}


def _nom_du_client(client: str) -> str | None:
    """client_name de CET identifiant OAuth au registre, sinon None (fail-closed).

    Registre absent, illisible, client inconnu ou sans nom : None. Le nom est la cle de
    config/pairs_rings.json (claude.ai s'inscrit sous un nouvel identifiant a chaque
    autorisation, mais toujours sous le meme nom).
    """
    if not _client_valide(client):
        return None
    chemin = (os.environ.get("NOKIDO_BRIDGE_OAUTH_CLIENTS") or "").strip()
    if not chemin:
        return None
    try:
        inscrits = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(inscrits, list):
        return None
    for c in inscrits:
        if isinstance(c, dict) and c.get("client_id") == client:
            nom = str(c.get("client_name") or "").strip()
            return nom or None
    return None


def _politique_rings() -> dict | None:
    """config/pairs_rings.json lu en dict, sinon None -- illisible = ferme, et le DIRE."""
    try:
        politique = json.loads(Path(chemin_politique_rings()).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _LOG.warning("[pair] politique des rings ILLISIBLE (%s) : tout reste ferme", type(e).__name__)
        return None
    if not isinstance(politique, dict):
        _LOG.warning("[pair] politique des rings MAL FORMEE (pas un objet) : tout reste ferme")
        return None
    return politique


def _paire_listee(politique: dict | None, nom: str) -> bool:
    """Ce NOM figure-t-il dans la section `pairs` ? Egalite stricte, insensible a la casse.

    Jamais une sous-chaine : « ClaudeX » ne correspond pas a « claude ».
    """
    if not isinstance(politique, dict):
        return False
    pairs = politique.get("pairs")
    if not isinstance(pairs, dict):
        return False
    cible = nom.casefold()
    return any(isinstance(cle, str) and cible == cle.casefold() for cle in pairs)


def _ring_du_pair(client: str) -> int | None:
    """Ring du PAIR dans la politique versionnee (config/pairs_rings.json), sinon None.

    Decision owner 17/10 : les pairs cloud (claude.ai, ChatGPT web) sont ring 2 -- la source
    est la politique, plus le registre OAuth (qui ne porte aucun ring). Cle = client_name,
    compare a l'egalite INSensible a la casse (jamais une sous-chaine). Politique absente ou
    illisible, client sans nom, nom absent de `pairs`, valeur non entiere : None (ferme,
    fail-closed) et le refus est DIT dans le journal.
    """
    if not _client_valide(client):
        return None
    nom = _nom_du_client(client)
    if not nom:
        _LOG.warning("[pair] ring INCONNU : client '%s' sans nom lisible au registre OAuth", client)
        return None
    politique = _politique_rings()
    if politique is None:
        return None          # deja DIT par _politique_rings()
    pairs = politique.get("pairs")
    if not isinstance(pairs, dict):
        _LOG.warning("[pair] politique des rings sans section 'pairs' : '%s' reste ferme", nom)
        return None
    cible = nom.casefold()
    for cle, ring in pairs.items():
        if isinstance(cle, str) and cible == cle.casefold():
            if isinstance(ring, int) and not isinstance(ring, bool):
                return ring
            _LOG.warning("[pair] ring NON ENTIER pour '%s' : ferme", nom)
            return None
    _LOG.warning("[pair] '%s' absent de config/pairs_rings.json : ferme (ring INCONNU)", nom)
    return None


def _decouper_en_pages(texte: str, max_sortie: int = MAX_SORTIE) -> list[str]:
    """Decoupe un texte pour que chaque page, enveloppee dans sa reponse JSON, passe sous max_sortie."""
    if not texte:
        return [""]
    pages = []
    debut = 0
    n = len(texte)
    while debut < n:
        fin = min(n, debut + 4000)
        while fin > debut:
            morceau = texte[debut:fin]
            charge_test = {
                "ok": True,
                "page": len(pages),
                "pages": 9999,
                "sha256": "0" * 64,
                "contenu": morceau,
            }
            if len(json.dumps(charge_test, ensure_ascii=False)) <= max_sortie:
                break
            fin -= 200
        if fin <= debut:
            fin = debut + 1
        pages.append(texte[debut:fin])
        debut = fin
    return pages


def lire_annexe(client: str, pointeur: str, page: int = 0) -> dict:
    """Lit une annexe de capsule confirmee par pointeur 'annexe:<capsule>/<nom>', page par page.

    Fail-closed partout : pointeur confine, ring du pair verifie face a ring_annexes de la
    capsule, et un pair de config/pairs_rings.json ne lit que les capsules de relecture
    (usage_annexes = "relecture").
    """
    if not isinstance(pointeur, str) or not pointeur.startswith("annexe:"):
        return {"ok": False, "erreur": "format de pointeur invalide (doit commencer par 'annexe:')"}
    corps = pointeur[len("annexe:"):]
    if "/" not in corps or "\\" in corps:
        return {"ok": False, "erreur": "format de pointeur invalide (attendu: annexe:<capsule>/<nom>)"}
    parties = corps.split("/")
    if len(parties) != 2:
        return {"ok": False, "erreur": "format de pointeur invalide (un seul separateur autorise)"}
    capsule, nom = parties
    motif = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not motif.fullmatch(capsule) or not motif.fullmatch(nom):
        return {"ok": False, "erreur": "caracteres invalides dans le pointeur"}
    if ".." in capsule or ".." in nom or capsule in (".", "..") or nom in (".", ".."):
        return {"ok": False, "erreur": "pointeur invalide (traversee .. interdite)"}

    dossier_base = dossier_capsules().resolve()
    fichier_capsule = (dossier_base / f"{capsule}.capsule.json").resolve()
    dossier_annexes = (dossier_base / capsule / "annexes").resolve()
    fichier_annexe = (dossier_annexes / nom).resolve()

    try:
        fichier_capsule.relative_to(dossier_base)
        dossier_annexes.relative_to(dossier_base)
        fichier_annexe.relative_to(dossier_annexes)
    except ValueError:
        return {"ok": False, "erreur": "chemin hors du dossier des capsules"}

    if not fichier_capsule.is_file():
        return {"ok": False, "erreur": "capsule introuvable"}
    if not fichier_annexe.is_file():
        return {"ok": False, "erreur": "annexe introuvable"}

    try:
        meta = json.loads(fichier_capsule.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "erreur": "capsule illisible (%s)" % type(e).__name__}

    ring_annexes = meta.get("ring_annexes")
    if ring_annexes is None or not isinstance(ring_annexes, int):
        return {"ok": False, "erreur": "ring_annexes absent de la capsule"}

    ring_pair = _ring_du_pair(client)
    if ring_pair is None:
        return {"ok": False, "erreur": "ring INCONNU : client non autorise"}
    if ring_pair > ring_annexes:
        return {"ok": False, "erreur": "ring insuffisant (pair %d > requis %d)" % (ring_pair, ring_annexes)}

    # Decision owner 17/10 : « ring 2, et seulement pour les annexes de relecture ». Le ring
    # d'un pair de la politique n'ouvre QUE les capsules qui declarerent usage_annexes
    # = "relecture" ; tout le reste (absent, "mission", casse, ...) reste FERME, refus DIT.
    if _paire_listee(_politique_rings(), _nom_du_client(client) or ""):
        if meta.get("usage_annexes") != "relecture":
            return {"ok": False,
                    "erreur": "annexes fermees : seules les capsules de relecture s'ouvrent aux "
                              "pairs (il faut usage_annexes='relecture'), ici usage_annexes=%s"
                              % json.dumps(meta.get("usage_annexes"))}

    try:
        contenu_total = fichier_annexe.read_text(encoding="utf-8")
    except Exception as e:
        return {"ok": False, "erreur": "annexe illisible (%s)" % type(e).__name__}

    sha256_total = hashlib.sha256(contenu_total.encode("utf-8")).hexdigest()
    pages = _decouper_en_pages(contenu_total)
    total_pages = len(pages)

    try:
        p = int(page)
    except (TypeError, ValueError):
        return {"ok": False, "erreur": "page invalide (doit etre un entier)", "pages": total_pages}

    if p < 0 or p >= total_pages:
        return {"ok": False, "erreur": "page hors borne (%d hors de [0, %d])" % (p, total_pages - 1),
                "page": p, "pages": total_pages}

    return {
        "ok": True,
        "page": p,
        "pages": total_pages,
        "sha256": sha256_total,
        "contenu": pages[p],
    }


_lire_annexe_impl = lire_annexe


# ---------------------------------------------------------------------------------------------------------------
# Lecture du VIVANT (owner 17/10 : « tout »). Mesure : la relecture claude.ai des clotures R7/R8 avait ete faite sur le
# dist PUBLIC 0.20.12 et 12 objections ont du etre contre-verifiees sur alpha. Portee : tout fichier SUIVI d'alpha,
# hors exclusions ; ring <= 2 ; pages ; lecture git seule, aucune ecriture ; sortie redigee par `rediger`.
# ---------------------------------------------------------------------------------------------------------------
RING_MAX_VIVANT = 2
TAILLE_MAX_VIVANT = 1_000_000
_CHEMIN_VIVANT = re.compile(r"[\w.\- /]+")
# Exclus MEME suivis : coffre, .env, secrets, cles, RAG, configuration des clients (MCP, settings).
_EXCLUS_VIVANT = (
    re.compile(r"(^|/)[^/]*\.env(\.[^/]*)?$", re.I),                     # .env, Nokido.env, .env.local
    re.compile(r"\.(pem|key|p12|pfx|crt|cer|der|jks|keystore|kdbx|gpg|asc|ppk)$", re.I),
    re.compile(r"(^|/)(id_rsa|id_dsa|id_ecdsa|id_ed25519)[^/]*$", re.I),
    re.compile(r"(^|/)\.mcp\.json", re.I),
    re.compile(r"(^|/)\.claude(/|$)", re.I),
    re.compile(r"(^|/)settings(\.local)?\.json$", re.I),
    re.compile(r"(^|/)RAG(/|$)", re.I),
)
# Un nom de secret exclut tout fichier de DONNEES ; le code (.py) reste lisible, redige comme toute sortie.
_EXCLUS_DONNEES_VIVANT = re.compile(r"secret|coffre|vault|credential|passw", re.I)


def _refus_chemin_vivant(chemin) -> str | None:
    """Motif du refus, ou None si le chemin est confine au depot. Verifie AVANT toute lecture git."""
    if not isinstance(chemin, str) or not chemin.strip():
        return "chemin vide"
    if "\\" in chemin or "\x00" in chemin or chemin.startswith("/") or re.match(r"^[A-Za-z]:", chemin):
        return "chemin absolu ou separateur invalide (attendu : chemin relatif au depot, separateur /)"
    if any(p in ("", ".", "..") for p in chemin.split("/")):
        return "chemin invalide (traversee ou segment vide interdits)"
    if not _CHEMIN_VIVANT.fullmatch(chemin):
        return "caracteres invalides dans le chemin"
    if any(m.search(chemin) for m in _EXCLUS_VIVANT) or (
            not chemin.endswith(".py") and _EXCLUS_DONNEES_VIVANT.search(chemin)):
        return "chemin exclu de la lecture du vivant (coffre, .env, secrets, cles, RAG, configuration client)"
    return None


def _contenu_suivi(chemin: str):
    """(sha COURT d'alpha, texte) du fichier SUIVI sur alpha ; None s'il n'y est pas suivi ou si git est illisible.
    Sha court : un sha de 40 hex serait redige par _EN_PLUS_DU_PARE_FEU."""
    base = ["git", "-c", "safe.directory=*", "-C", str(ROOT)]
    try:
        sha = subprocess.run(base + ["rev-parse", "--short=12", "alpha"], capture_output=True, text=True,
                             errors="replace", timeout=15)
        genre = subprocess.run(base + ["cat-file", "-t", "alpha:" + chemin], capture_output=True, text=True,
                               errors="replace", timeout=15)
        if sha.returncode != 0 or genre.returncode != 0 or genre.stdout.strip() != "blob":
            return None
        brut = subprocess.run(base + ["show", "alpha:" + chemin], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if brut.returncode != 0:
        return None
    return sha.stdout.strip(), brut.stdout.decode("utf-8", "replace")


def lire_vivant(client: str, chemin: str, page: int = 0) -> dict:
    """Lit un fichier SUIVI d'alpha, page par page, pour un pair de ring <= 2. Fail-closed : ring inconnu, chemin
    hors depot ou exclu, fichier non suivi, page hors borne -> refus DIT. Lecture seule."""
    ring_pair = _ring_du_pair(client)
    if ring_pair is None:
        return {"ok": False, "erreur": "ring INCONNU : client non autorise"}
    if ring_pair > RING_MAX_VIVANT:
        return {"ok": False, "erreur": "ring insuffisant (pair %d > requis %d)" % (ring_pair, RING_MAX_VIVANT)}
    motif = _refus_chemin_vivant(chemin)
    if motif:
        return {"ok": False, "erreur": motif}
    res = _contenu_suivi(chemin)
    if res is None:
        return {"ok": False, "erreur": "fichier non suivi sur alpha (ou git illisible) : %s" % chemin}
    sha, texte = res
    if len(texte) > TAILLE_MAX_VIVANT:
        return {"ok": False, "erreur": "fichier trop gros pour la lecture paginee (%d > %d caracteres)"
                                       % (len(texte), TAILLE_MAX_VIVANT)}
    pages = _decouper_en_pages(texte, MAX_SORTIE - len(chemin) - 64)
    try:
        p = int(page)
    except (TypeError, ValueError):
        return {"ok": False, "erreur": "page invalide (doit etre un entier)", "pages": len(pages)}
    if p < 0 or p >= len(pages):
        return {"ok": False, "erreur": "page hors borne (%d hors de [0, %d])" % (p, len(pages) - 1),
                "page": p, "pages": len(pages)}
    return {"ok": True, "chemin": chemin, "sha": sha, "page": p, "pages": len(pages), "contenu": pages[p]}


_lire_vivant_impl = lire_vivant


# ── Collaboration (quarantaine) ─────────────────────────────────────────────

def _nettoyer(texte) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(texte or ""))[:MAX_TEXTE]


def _client_valide(client) -> bool:
    return isinstance(client, str) and bool(re.fullmatch(r"[A-Za-z0-9_.:\-]{1,80}", client))


def deposer(client: str, methode: str, intent: str, objectif: str, texte: str,
            destinataire: str, extra: dict = None) -> dict:
    """Entre un depot de pair en QUARANTAINE. Rien n'agit avant l'approbation de l'owner."""
    if not _client_valide(client):
        return {"ok": False, "erreur": "client non identifie : depot refuse"}
    from nokido_agent.app.forge_harness_contract import EtapeContrat, verdict_etape

    de = "PAIR:" + client
    ident = "pair_" + secrets.token_hex(8)
    etape = EtapeContrat(objectif=_nettoyer(objectif)[:300], capacite="pair." + methode,
                         preconditions=["approbation owner (NEED_HUMAN_APPROVAL)"],
                         action={"intent": intent, "pointer_ref": "pair:" + ident},
                         effet_attendu="aucun avant approbation owner")
    charge = {"intent": intent, "pointer_ref": "pair:" + ident, "approbation": "NEED_HUMAN_APPROVAL",
              "destinataire": destinataire, "texte": _nettoyer(texte),
              "provenance": {"client": client, "recu_a": _maintenant(), "confiance": "EXTERNE_NON_VERIFIEE"},
              "etape": etape.to_dict(), "verdict": verdict_etape(etape)}
    charge.update(extra or {})
    # Une borne DIT combien (19/10 : le plan en 6 vagues de ChatGPT web coupe a MAX_TEXTE en silence, vague 5 perdue).
    recu = len(str(texte or ""))
    tronque = {"recu": recu, "garde": MAX_TEXTE} if recu > MAX_TEXTE else None
    if tronque:
        charge["tronque"] = tronque
    depuis = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=1)).isoformat(timespec="seconds")
    try:
        con = sqlite3.connect(chemin_m2m(), timeout=10)
    except sqlite3.Error as e:
        return {"ok": False, "etat": "ILLISIBLE", "motif": type(e).__name__}
    try:
        n = con.execute("SELECT COUNT(*) FROM agent_messages WHERE from_agent=? AND created_at>=?",
                        (de, depuis)).fetchone()[0]
        if n >= DEBIT_PAR_HEURE:
            return {"ok": False, "erreur": "debit depasse (%d depots par heure)" % DEBIT_PAR_HEURE}
        con.execute("INSERT INTO agent_messages (id, from_agent, to_agent, correlation_id, method, payload, "
                    "status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (ident, de, BOITE_APPROBATION, ident, "pair." + methode,
                     json.dumps(charge, ensure_ascii=False), STATUT_QUARANTAINE, _maintenant()))
        con.commit()
    except sqlite3.Error as e:
        return {"ok": False, "etat": "ECRITURE_REFUSEE", "motif": type(e).__name__}
    finally:
        con.close()
    _LOG.info("[pair] depot %s de %s en quarantaine (%s)%s", ident, de, methode,
              " -- TRONQUE %d -> %d" % (tronque["recu"], tronque["garde"]) if tronque else "")
    rep = {"ok": True, "id": ident, "statut": STATUT_QUARANTAINE,
           "note": "en quarantaine : rien n'agit avant l'approbation de l'owner"}
    if tronque:
        rep["tronque"] = tronque
        rep["note"] += (" ; TRONQUE : %d caracteres recus, %d gardes -- renvoie des pointeurs (cles bb exactes, "
                        "ordre = dependance) ou decoupe en depots 1/n citant le precedent"
                        % (tronque["recu"], tronque["garde"]))
    return rep


def deposer_fait(client: str, texte: str, domaine: str = "roadmap") -> dict:
    if domaine not in DOMAINES_SSOT:
        return {"ok": False, "erreur": "domaine hors liste blanche", "domaines": list(DOMAINES_SSOT)}
    return deposer(client, "proposer_fait", "FACT_PROPOSED", "proposition de fait SSoT (%s)" % domaine,
                   texte, "OWNER", {"domaine": domaine})


def deposer_message(client: str, intent: str, texte: str, destinataire: str) -> dict:
    if destinataire not in DESTINATAIRES:
        return {"ok": False, "erreur": "destinataire hors liste", "destinataires": list(DESTINATAIRES)}
    if intent not in INTENTS_MESSAGE_PAIR:
        return {"ok": False, "erreur": "intent non ouvert aux pairs", "intents": list(INTENTS_MESSAGE_PAIR)}
    from nokido_agent.app.forge_m2m_protocol import validate
    verdict = validate("notify", {"intent": intent, "pointer_ref": "pair:depot"})
    if str(verdict.get("code", "")).startswith("M2M_ERR"):
        return {"ok": False, "erreur": "message M2M refuse", "verdict": verdict}
    return deposer(client, "envoyer_message", intent, "message M2M vers %s" % destinataire, texte, destinataire)


def deposer_tache(client: str, objectif: str, destinataire: str = "CLAUDE", genre: str = "deliberer") -> dict:
    if genre not in GENRES_TACHE:
        return {"ok": False, "erreur": "genre de tache hors liste", "genres": list(GENRES_TACHE)}
    if destinataire not in DESTINATAIRES:
        return {"ok": False, "erreur": "destinataire hors liste", "destinataires": list(DESTINATAIRES)}
    return deposer(client, "soumettre_tache", "HANDOFF_NEXT", objectif, objectif, destinataire,
                   {"genre": genre})


def clients_du_meme_pair(client: str) -> list:
    """Tous les identifiants inscrits sous le MEME nom que `client`.

    Mesure 2026-09-29 : claude.ai s'inscrit comme un NOUVEAU client OAuth a chaque autorisation
    du connecteur (trois « Claude » au registre) ; une reponse de l'owner adressee a l'identifiant
    d'hier restait invisible a la session du jour -- « limite par conversation » (owner). Regrouper
    par nom est sur : aucun client n'obtient de jeton sans le consentement de l'owner (code
    d'appariement), donc seul un client qu'il a autorise peut lire. Registre illisible, ou client
    sans nom : le seul `client`, jamais davantage.
    """
    chemin = (os.environ.get("NOKIDO_BRIDGE_OAUTH_CLIENTS") or "").strip()
    if not chemin:
        return [client]
    try:
        inscrits = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [client]
    noms = {str(c.get("client_id")): str(c.get("client_name") or "").strip()
            for c in (inscrits if isinstance(inscrits, list) else []) if isinstance(c, dict)}
    nom = noms.get(client)
    if not nom:
        return [client]
    return sorted({cid for cid, n in noms.items() if n == nom and _client_valide(cid)} | {client})


def _quarantaine():
    """tools/forge_pair_quarantaine.py, charge par chemin (meme motif que forge_ordres_bureau)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("forge_pair_quarantaine_pair",
                                                  Path(__file__).resolve().parent / "forge_pair_quarantaine.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def suivre_depot(client: str, ident: str) -> dict:
    """Les cinq accuses d'un depot DE CE PAIR (envoye, recu, lu, repondu, reponse lue).
    Un pair ne suit que ses propres depots : ceux de ses inscriptions (clients_du_meme_pair)."""
    if not _client_valide(client) or not re.fullmatch(r"pair_[0-9a-f]{16}", str(ident or "")):
        return {"ok": False, "erreur": "client ou identifiant de depot invalide"}
    r = _quarantaine().suivi(ident)
    if not r.get("ok") or r.get("de") not in {"PAIR:" + c for c in clients_du_meme_pair(client)}:
        return {"ok": False, "erreur": "depot inconnu pour ce pair"}      # jamais dire a qui il appartient
    return r


def _accuser_reponse_lue(client: str, reponse: str) -> None:
    """Accuse « reponse lue » : courrier postal M2M vers CLAUDE (pointeur seulement). Echec DIT."""
    try:
        from nokido_agent.app import forge_postal
        corps = json.dumps({"intent": "OK_DONE", "pointer_ref": "pair-reponse:" + reponse, "confidence": 1.0})
        forge_postal.post("PAIR:" + client, "CLAUDE", corps, dedup_key="pair-lu:" + reponse,
                          trace_id="pair-lu:" + reponse)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("[pair] accuse 'reponse lue' NON poste pour %s (%s)", reponse, type(exc).__name__)


def relever_reponses(client: str) -> dict:
    """Les reponses adressees a CE pair -- a tous ses identifiants, cf `clients_du_meme_pair` --
    (statut unread), marquees lues."""
    if not _client_valide(client):
        return {"ok": False, "erreur": "client non identifie"}
    boites = ["PAIR:" + c for c in clients_du_meme_pair(client)]
    # 19/10 : `pair-repondre` adresse au NOM du pair (comme les rings) ; une nouvelle session OAuth du meme pair ne
    # relevait jamais `PAIR:<nom>` (tache claude.ai apr_1f4408f74c3c9af4 restee unread). Jamais la boite d'un autre pair.
    nom = _nom_du_client(client)
    if nom and "PAIR:" + nom not in boites:
        boites.append("PAIR:" + nom)
    try:
        con = sqlite3.connect(chemin_m2m(), timeout=10)
    except sqlite3.Error as e:
        return {"ok": False, "etat": "ILLISIBLE", "motif": type(e).__name__}
    try:
        lignes = con.execute("SELECT id, from_agent, method, payload, created_at FROM agent_messages "
                             "WHERE to_agent IN (%s) AND status='unread' ORDER BY created_at LIMIT 20"
                             % ",".join("?" * len(boites)), tuple(boites)).fetchall()
        for (ident, *_r) in lignes:
            con.execute("UPDATE agent_messages SET status='read' WHERE id=?", (ident,))
        con.commit()
    except sqlite3.Error as e:
        return {"ok": False, "etat": "ILLISIBLE", "motif": type(e).__name__}
    finally:
        con.close()
    reponses = []
    for ident, de, methode, charge, recu in lignes:
        try:
            charge = json.loads(charge)
        except (TypeError, ValueError):
            charge = str(charge)[:MAX_TEXTE]
        reponses.append({"id": ident, "de": de, "methode": methode, "charge": charge, "recu_a": recu})
        _accuser_reponse_lue(client, ident)
    return {"ok": True, "reponses": reponses}


# ── Transport ───────────────────────────────────────────────────────────────

def _entete_autorisation():
    """En-tete Authorization de la requete HTTP en cours (None hors HTTP, "" si absent)."""
    try:
        from mcp.server.lowlevel.server import request_ctx
    except Exception:  # noqa: BLE001
        return None
    contexte = request_ctx.get(None)
    requete = getattr(contexte, "request", None) if contexte is not None else None
    if requete is None:
        return None
    try:
        return requete.headers.get("authorization") or ""
    except Exception:  # noqa: BLE001
        return ""


def client_courant(module_oauth):
    """Le client OAuth (`sub`) de la requete, relu a chaque appel -- None s'il n'y en a pas."""
    if module_oauth is None:
        return None
    entete = _entete_autorisation() or ""
    if not entete.lower().startswith("bearer "):
        return None
    charge, _motif = module_oauth.verifier(entete[7:].strip())
    return charge.get("sub") if charge else None


def charger_oauth():
    """L'autorite OAuth unique, FORCEE sur la passerelle des pairs pour CE chargement.

    La variable n'est posee que le temps du chargement (le module lit sa passerelle a l'import),
    puis restauree : laissee en place, elle ferait basculer tout chargement ulterieur de
    l'autorite -- celle du pont GitHub comprise -- sur la passerelle des pairs.
    """
    precedent = os.environ.get("NOKIDO_OAUTH_PASSERELLE")
    os.environ["NOKIDO_OAUTH_PASSERELLE"] = "forge_passerelle_pair.py"
    try:
        chemin = ROOT / "tools" / "forge_bridge_oauth.py"
        spec = importlib.util.spec_from_file_location("forge_bridge_oauth_pair", chemin)
        if spec is None or spec.loader is None:
            raise SystemExit("autorite OAuth illisible : %s" % chemin)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if precedent is None:
            os.environ.pop("NOKIDO_OAUTH_PASSERELLE", None)
        else:
            os.environ["NOKIDO_OAUTH_PASSERELLE"] = precedent
    return module


def base_publique(port: int) -> str:
    """L'URL ANNONCEE (tunnel), jamais celle d'ecoute. https exige des qu'elle est declaree."""
    declaree = (os.environ.get("NOKIDO_PAIR_PUBLIC_URL") or "").strip().rstrip("/")
    if declaree:
        if not declaree.startswith("https://"):
            raise SystemExit("NOKIDO_PAIR_PUBLIC_URL doit etre en https : %s" % declaree)
        return declaree
    return "http://%s:%d" % (HOTE, port)


def securite_transport(base: str):
    """Protection DNS-rebinding de FastMCP GARDEE, etendue au SEUL hote annonce.

    FastMCP l'active d'office sur 127.0.0.1 avec les seuls hotes loopback (mcp 1.28.1). Derriere
    le tunnel (Tailscale Funnel conserve l'en-tete Host), le Host public serait refuse en 421 --
    et le NR du 401 ne le voit pas : l'authentification repond AVANT le controle du Host. On
    ajoute l'hote de NOKIDO_PAIR_PUBLIC_URL et lui seul ; jamais `*`, jamais la protection coupee.
    """
    from urllib.parse import urlsplit
    from mcp.server.transport_security import TransportSecuritySettings

    hotes = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origines = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    publique = urlsplit(base)
    if publique.scheme == "https" and publique.hostname:
        hotes += [publique.netloc, publique.hostname + ":*"]
        origines.append("https://" + publique.netloc)
    return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                     allowed_hosts=hotes, allowed_origins=origines)


def construire_serveur(port: int = PORT_PAR_DEFAUT, oauth: bool = True):
    from mcp.server.fastmcp import FastMCP

    reglages = {"host": HOTE, "port": int(port), "streamable_http_path": CHEMIN_HTTP,
                "stateless_http": True, "json_response": True,
                "transport_security": securite_transport(base_publique(port))}
    module_oauth = autorite = None
    if oauth:
        module_oauth = charger_oauth()
        autorite = module_oauth.AutoriteLocale()
        reglages["auth_server_provider"] = autorite
        reglages["auth"] = module_oauth.reglages(base_publique(port), CHEMIN_HTTP,
                                                 "http://%s:%d" % (HOTE, int(port)))
    serveur = FastMCP("nokido-pair", **reglages)

    def _client():
        return client_courant(module_oauth)

    def _anonyme(outil):
        return rediger({"ok": False, "erreur": "client non identifie : aucune collaboration anonyme"}, outil)

    def _au_nom_du_pair(outil, fonction, *args):
        """Tout outil de pair : client IDENTIFIE ou refus, et sortie toujours redigee."""
        c = _client()
        return rediger(fonction(c, *args), outil) if c else _anonyme(outil)

    @serveur.tool(name="etat_corps", description="Bilan de sante de Nokido (score, confiance, manques).")
    async def etat_corps() -> dict:
        return rediger(lire_etat_corps(), "etat_corps")

    @serveur.tool(name="point_ssot", description="Point SSoT structure : domaine 'roadmap' ou 'rules'.")
    async def point_ssot(domaine: str = "roadmap") -> dict:
        return rediger(lire_point_ssot(domaine), "point_ssot")

    @serveur.tool(name="recherche_rag", description="Recherche plein texte dans les sources PUBLIQUES du RAG (limite <= 10).")
    async def recherche_rag(requete: str, limite: int = 5) -> dict:
        return rediger(rechercher_rag(requete, limite), "recherche_rag")

    @serveur.tool(name="journal_commits", description="Derniers commits PUBLIES (origin/alpha, n <= 20).")
    async def journal_commits(n: int = 10) -> dict:
        return rediger(lire_journal_commits(n), "journal_commits")

    @serveur.tool(name="derniere_capsule", description="Derniere capsule cognitive (deliberation RecursiveMAS) publiee pour les pairs.")
    async def derniere_capsule() -> dict:
        return rediger(lire_derniere_capsule(), "derniere_capsule")

    @serveur.tool(name="proposer_fait", description=(
        "Propose un fait au SSoT (roadmap ou rules) : QUARANTAINE, approbation owner. Texte <= %d caracteres "
        "(au-dela COUPE, et la reponse le DIT) : envoie des POINTEURS -- cles EXACTES du tableau noir (bb:<cle>), "
        "ordre = dependance -- pas de prose ni de copie d'etat (Nokido lit le vivant) ; contenu long = plusieurs "
        "depots numerotes 1/n citant le pointer_ref du precedent." % MAX_TEXTE))
    async def proposer_fait(texte: str, domaine: str = "roadmap") -> dict:
        return _au_nom_du_pair("proposer_fait", deposer_fait, texte, domaine)

    @serveur.tool(name="envoyer_message", description="Message M2M vers OWNER, CLAUDE, ANTIGRAVITY ou GEMINI : QUARANTAINE. "
                  "Intents ouverts aux pairs : " + ", ".join(INTENTS_MESSAGE_PAIR) + ". Texte <= %d caracteres "
                  "(au-dela COUPE et DIT) : des POINTEURS (bb:<cle>, commit, pair_<id>), pas de prose." % MAX_TEXTE)
    async def envoyer_message(intent: str, texte: str, destinataire: str = "OWNER") -> dict:
        return _au_nom_du_pair("envoyer_message", deposer_message, intent, texte, destinataire)

    # La route reelle est celle de forge_pair_quarantaine.approuver (mesure 2026-09-29) : un pair
    # (claude.ai) a soumis en 'deliberer' pour « Claude Code local » en croyant cette description --
    # or 'deliberer' IGNORE le destinataire et renvoie la capsule au pair. Le contrat dit la route.
    @serveur.tool(name="soumettre_tache", description=(
        "Tache pour Nokido, en QUARANTAINE : rien ne s'execute avant l'approbation owner. "
        "Texte <= MAX_TEXTE = 4000 caracteres (au-dela COUPE et DIT) : des POINTEURS (bb:<cle>, fichier:ligne), "
        "pas de prose. "
        "genre='deliberer' : debat LOCAL RecursiveMAS (modeles locaux) ; le destinataire est IGNORE "
        "et la capsule de resultat est RENVOYEE AU PAIR -- aucun agent local ne la recoit. "
        "genre='executer' : livree, apres approbation, dans la boite de l'agent `destinataire` "
        "(CLAUDE par defaut), qui decide de la suite."))
    async def soumettre_tache(objectif: str, destinataire: str = "CLAUDE", genre: str = "deliberer") -> dict:
        return _au_nom_du_pair("soumettre_tache", deposer_tache, objectif, destinataire, genre)

    @serveur.tool(name="suivre", description=(
        "Accuses d'un de TES depots (id pair_...) : envoye, recu (approuve et livre), lu, repondu, "
        "reponse lue -- horodatages, None = pas encore. Lecture seule."))
    async def suivre(id: str) -> dict:
        return _au_nom_du_pair("suivre", suivre_depot, id)

    @serveur.tool(name="lire_reponses", description="Reponses adressees a CE pair (capsules, messages M2M).")
    async def lire_reponses() -> dict:
        return _au_nom_du_pair("lire_reponses", relever_reponses)

    if oauth:
        @serveur.tool(name="lire_annexe", description=(
            "Lit une annexe de capsule cognitive par son pointeur (annexe:<capsule>/<nom>), page par page. "
            "Le pair doit etre identifie, son ring inferieur ou egal a ring_annexes de la capsule, "
            "et la capsule doit declarer usage_annexes = 'relecture' (decision owner 17/10)."))
        async def lire_annexe(pointeur: str, page: int = 0) -> dict:
            return _au_nom_du_pair("lire_annexe", _lire_annexe_impl, pointeur, page)

        @serveur.tool(name="lire_vivant", description=(
            "Lit un fichier SUIVI de la branche alpha de Nokido (le code VIVANT, pas le dist public), page par page. "
            "chemin relatif au depot avec separateur /. Ring <= 2 ; exclus : coffre, .env, secrets, cles, RAG, "
            "configuration client. Lecture seule, sortie redigee. Le sha court d'alpha est rendu."))
        async def lire_vivant(chemin: str, page: int = 0) -> dict:
            return _au_nom_du_pair("lire_vivant", _lire_vivant_impl, chemin, page)

    if autorite is not None:
        module_oauth.poser_consentement(serveur, autorite)
        serveur._nokido_oauth = module_oauth
    return serveur


def main(argv=None) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=PORT_PAR_DEFAUT)
    args = ap.parse_args(argv)
    serveur = construire_serveur(args.port)
    import uvicorn

    application = serveur.streamable_http_app()
    serveur._nokido_oauth.poser_complements(application)
    _LOG.info("[pair] ecoute %s:%d%s ; annonce %s", HOTE, args.port, CHEMIN_HTTP, base_publique(args.port))
    uvicorn.run(application, host=HOTE, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())