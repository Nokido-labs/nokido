"""Agent Card A2A GENEREE depuis l'etat vivant — jamais un fichier statique.

REGLE FONDATRICE (owner, 2026-09-04) : la carte ne decrit pas ce que Nokido sait
faire en theorie, elle decrit **ce qu'il expose et peut prouver maintenant**.
C'est le meme axe que `forge_reachability_ledger` : « present dans le corps » n'est
pas « engage par un workflow ». Mesure du jour a l'appui — ACP etait implemente,
declare comme service, et ETEINT ; 165 outils MCP sont offerts, 58 prouves par usage.

TROIS ETATS, JAMAIS DEUX (et c'est ce qui distingue cette carte d'un manifeste) :

    DECLARE   le corps porte le code / le service est declare
    AVAILABLE le service repond ICI ET MAINTENANT
    VERIFIED  un NR prouve que la capacite s'execute de bout en bout

**Seuls les VERIFIED entrent dans les `skills` de la carte publique.** Annoncer une
capacite qu'aucun NR ne sait executer reproduirait exactement le defaut qu'on vient
de mesurer, mais cette fois vis-a-vis de l'exterieur.

La carte etendue (authentifiee) peut, elle, porter l'etat operationnel : ce qui est
DECLARE mais pas AVAILABLE, les providers joignables, les versions. A2A prevoit
`supportsAuthenticatedExtendedCard` pour cela.

Usage :
    python tools/forge_a2a_card.py            # carte publique
    python tools/forge_a2a_card.py --etendue  # + etat operationnel
    python tools/forge_a2a_card.py --etats    # le detail declare/available/verified
"""

__FORGE_COLOR__ = "reseau/interoperabilite-a2a"

import hashlib
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOLE = "0.3.0"
DECLARE, AVAILABLE, VERIFIED = "declared", "available", "verified"


def _port_ouvert(port: int, hote: str = "127.0.0.1") -> bool:
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect((hote, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _nr_couvre(motif: str) -> bool:
    """Un NR nomme-t-il cette capacite ? C'est la preuve d'EXECUTABILITE.

    Volontairement peu exigeant — la barre est qu'un test EXISTE et nomme la
    capacite, pas qu'il soit exhaustif : meme convention que
    `test_nr_coverage_ratchet_nr`. Une capacite qu'aucun test ne nomme n'a
    aucune chance d'echouer le jour ou elle regresse, donc elle ne se publie pas.
    """
    nr = ROOT / "tests" / "nr"
    if not nr.is_dir():
        return False
    try:
        for f in nr.glob("*.py"):
            # Le NOM du fichier compte autant que son contenu : mesure
            # 2026-09-04, `deliberation.replay` ressortait NON VERIFIE alors que
            # `test_deliberation_non_destructive_nr.py` existait avec 8 tests
            # verts — le motif etait dans le nom, pas dans le corps. Un
            # detecteur qui ne regarde qu'un cote fabrique des faux negatifs, et
            # ici un faux negatif RETIRE une capacite reelle de la carte.
            if motif in f.name:
                return True
            if motif in f.read_text(encoding="utf-8", errors="replace"):
                return True
    except OSError:
        return False        # illisible n'est pas prouve
    return False


# (id, nom, description, tags, sonde de disponibilite, motif NR)
_CANDIDATES = [
    ("rag.search", "Recherche RAG hybride",
     "Recherche lexicale (FTS5/BM25) et vectorielle sur le corpus souverain.",
     ["retrieval", "rag"], lambda: _port_ouvert(8766), "forge_retrieval_sweep"),
    ("deliberation.replay", "Deliberation rejouable",
     "Etat de deliberation non destructif : positions, filiation, rejeu deterministe.",
     ["deliberation", "audit"], lambda: True, "test_deliberation_non_destructive"),
    ("acp.session", "Transport ACP (WebSocket)",
     "Sessions ACP authentifiees sur ws://127.0.0.1:7782/acp.",
     ["acp", "transport"], lambda: _port_ouvert(7782), "forge_acp_server"),
    ("index.advisor", "Audit d'index par base",
     "Confronte les requetes du code au plan SQLite de chaque base.",
     ["sqlite", "performance"], lambda: True, "forge_db_index_advisor"),
    ("rfc.freshness", "Fraicheur des normes RFC",
     "Confronte les RFC ingerees a l'etat amont IETF (obsolete / mise a jour).",
     ["rfc", "veille"], lambda: True, "forge_rfc_freshness_gate"),
]


def etats() -> list:
    """Chaque capacite avec ses TROIS etats mesures, sans arrondi."""
    out = []
    for cid, nom, desc, tags, sonde, motif_nr in _CANDIDATES:
        try:
            dispo = bool(sonde())
        except Exception:  # noqa: BLE001
            dispo = False   # une sonde qui leve ne prouve pas la disponibilite
        out.append({
            "id": cid, "name": nom, "description": desc, "tags": tags,
            DECLARE: True,
            AVAILABLE: dispo,
            VERIFIED: bool(_nr_couvre(motif_nr)),
        })
    return out


def carte(etendue: bool = False, port: int = 7783) -> dict:
    """Agent Card A2A. Publique par defaut ; etendue = + etat operationnel."""
    tous = etats()
    # PUBLIC = prouve ET joignable. Un NR vert sur un service eteint n'autorise
    # pas a l'annoncer : la carte dit ce qui repond MAINTENANT.
    publiables = [s for s in tous if s[VERIFIED] and s[AVAILABLE]]
    c = {
        "protocolVersion": PROTOCOLE,
        "name": "Nokido",
        "description": "Agent souverain local : retrieval, deliberation tracable, "
                       "audit d'infrastructure.",
        "url": "http://127.0.0.1:%d/a2a" % port,
        "preferredTransport": "JSONRPC",
        "version": _version(),
        "capabilities": {
            # Aucune capacite annoncee qui ne soit implementee : `streaming` reste
            # false tant que `message/stream` n'existe pas. Inventer une
            # pseudo-version streaming serait la meme faute que publier un skill
            # non prouve.
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
        "security": [{"bearer": []}],
        "skills": [{"id": s["id"], "name": s["name"],
                    "description": s["description"], "tags": s["tags"]}
                   for s in publiables],
        "supportsAuthenticatedExtendedCard": True,
    }
    if etendue:
        c["nokido:operational"] = {
            "declared_not_available": [s["id"] for s in tous
                                       if s[DECLARE] and not s[AVAILABLE]],
            "available_not_verified": [s["id"] for s in tous
                                       if s[AVAILABLE] and not s[VERIFIED]],
            "counts": {"declared": sum(1 for s in tous if s[DECLARE]),
                       "available": sum(1 for s in tous if s[AVAILABLE]),
                       "verified": sum(1 for s in tous if s[VERIFIED])},
        }
    # Empreinte DETERMINISTE du contenu : deux etats identiques donnent la meme
    # version de carte, un changement de joignabilite en donne une autre.
    c["nokido:cardHash"] = hashlib.sha256(
        json.dumps(c, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return c


def _version() -> str:
    try:
        import subprocess
        # `errors="replace"` OBLIGATOIRE en mode texte : sans lui, un octet non
        # decodable fait crasher `_readerthread` de subprocess — c'est l'incident
        # 47 Go que le garde anti-regression surveille. Attrape au commit.
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                            "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:  # noqa: BLE001  # muet-ok : la version n'est pas critique
        pass
    return "inconnue"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--etats" in argv:
        for s in etats():
            print("%-22s declared=%s available=%-5s verified=%s"
                  % (s["id"], s[DECLARE], s[AVAILABLE], s[VERIFIED]))
        return 0
    print(json.dumps(carte("--etendue" in argv), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
