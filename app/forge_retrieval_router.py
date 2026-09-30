"""Routeur de recuperation — contrat, observation, et bascule SHADOW/ACTIVE.

__FORGE_COLOR__ = "cognition/routage-de-recuperation"

MANDAT OWNER 2026-09-01 : construire le routeur SANS modifier le ranking effectif de
`RAGEngine.search`. Le verrou de la baseline porte sur les CONCLUSIONS et sur
l'ACTIVATION, pas sur le developpement. Ce module est donc complet et inerte.

    SHADOW (defaut) : la decision est calculee et JOURNALISEE, jamais appliquee.
    ACTIVE          : la decision pondere la fusion. Bascule par donnee
                      (`LAFORGE_ROUTER_MODE`), sans autre changement architectural.

CE QUE CE MODULE NE PRETEND PAS. Les poids ci-dessous ne sont PAS optimaux et ne sont
presentes comme tels nulle part : ce sont des valeurs de depart EXPLICITES, destinees a
etre calibrees contre la baseline reelle. Aucune fixture synthetique ne vaut benchmark --
elles testent la MECANIQUE (le routeur reagit-il aux signaux ?), jamais la QUALITE (le
routeur retrouve-t-il mieux ?). Confondre les deux fabriquerait un faux verdict.

CE QU'IL REMPLACERA, quand la mesure l'aura justifie : `forge_rag_engine.search` decide
aujourd'hui par UN booleen -- `is_technical` (une regex CVE/IP/hex) qui multiplie le rang
lexical par 1,2. Ce booleen reste la BASELINE a battre : on ne le retire pas avant
d'avoir prouve qu'on fait mieux, sinon on perd la seule reference disponible.

POURQUOI UN SIGNAL ABSENT N'EST PAS UN SIGNAL NUL. Le routeur recoit la disponibilite par
canal (`forge_memory_availability`). Un `vector_status` a PENDING ou REFUSED_BY_POLICY
signifie « je n'ai pas pu voir », pas « ce n'est pas pertinent » : ponderer a la baisse
sur cette base condamnerait un chunk pour un signal que la politique lui interdit d'avoir
(626 646 chunks sont dans ce cas, mesure du jour). Quand le canal vectoriel est
indisponible, le routeur REPORTE son poids sur le lexical au lieu de penaliser.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

__FORGE_COLOR__ = "cognition/routage-de-recuperation"

SHADOW = "SHADOW"
ACTIVE = "ACTIVE"

_RACINE = Path(__file__).resolve().parent.parent
# AK3 (2026-09-12) : chemin REDIRIGEABLE. Il etait en dur, donc aucun test ne
# pouvait s'isoler — et le 2026-09-12 la mesure a trouve **9 des 10 observations
# du journal ecrites par les NR de B4**, dans la session meme. Un corpus de
# calibration qui se remplit des requetes de sa propre CI ne calibre rien.
_JOURNAL = Path(os.environ.get("LAFORGE_ROUTER_JOURNAL")
                or (_RACINE / "sandbox" / "router_observations.jsonl"))


def _chemin_journal() -> Path:
    """Resolu A CHAQUE APPEL, jamais fige a l'import.

    Une constante calculee au chargement ne peut pas etre redirigee ensuite — et
    ce module est charge sous DEUX noms (`forge_retrieval_router` et
    `nokido_agent.app.forge_retrieval_router`) unifies par le finder pose le
    2026-09-10 : un `importlib.reload` y rend l'objet DEJA charge et ne relit
    donc pas l'environnement. C'est le meme principe que l'interrupteur global
    `m2m.switch` : un etat partage se lit a l'appel, pas au chargement.

    Un `_JOURNAL` remplace par un test prime quand aucune variable n'est posee.
    """
    env = os.environ.get("LAFORGE_ROUTER_JOURNAL")
    return Path(env) if env else Path(_JOURNAL)
_JOURNAL_MAX_O = 8 * 1024 * 1024

# Regex de la baseline actuelle (`forge_rag_engine.search`), reprise TELLE QUELLE :
# le routeur doit pouvoir etre compare a elle, donc il doit savoir la reproduire.
_RE_TECHNIQUE = re.compile(r"cve-\d+|[a-z]{2,}-\d+|\d{1,3}\.\d{1,3}|\b0x[0-9a-f]+\b")
_RE_IDENT = re.compile(r"[a-z_]+_[a-z_]+|\b[A-Z][A-Z0-9_]{3,}\b|\.[a-z]{2,4}\b|::|/")
_RE_CHEMIN = re.compile(r"\b(?:app|tools|tests|docs|sandbox)/[\w./-]+")

# POIDS DE DEPART — NON CALIBRES, a battre contre la baseline. Ils sont ici pour etre
# VISIBLES et modifiables, pas parce qu'ils seraient justes.
_PROFILS = {
    "exact":       {"lexical": 0.75, "vector": 0.15, "structure": 0.10},
    "technique":   {"lexical": 0.60, "vector": 0.30, "structure": 0.10},
    "hybride":     {"lexical": 0.45, "vector": 0.45, "structure": 0.10},
    "conceptuel":  {"lexical": 0.20, "vector": 0.70, "structure": 0.10},
}


def mode() -> str:
    """SHADOW par defaut. L'activation est une DONNEE, jamais un effet de bord du code."""
    v = str(os.environ.get("LAFORGE_ROUTER_MODE", "")).strip().upper()
    return ACTIVE if v == ACTIVE else SHADOW


@dataclass
class RouteDecision:
    lexical_weight: float
    vector_weight: float
    structure_weight: float
    reason: str
    profil: str
    features: dict = field(default_factory=dict)
    availability_context: dict = field(default_factory=dict)
    mode: str = SHADOW


def caracteriser(query: str) -> dict:
    """Traits OBSERVABLES de la requete. Aucun LLM, aucun appel reseau, aucun etat."""
    q = (query or "").strip()
    mots = [m for m in re.split(r"\W+", q) if m]
    return {
        "longueur_mots": len(mots),
        "technique_regex_baseline": bool(_RE_TECHNIQUE.search(q.lower())),
        "identifiant": bool(_RE_IDENT.search(q)),
        "chemin_fichier": bool(_RE_CHEMIN.search(q)),
        "majuscules_rares": sum(1 for m in mots if m.isupper() and len(m) > 2),
        "interrogatif": bool(re.match(r"^(comment|pourquoi|quel|qu|est-ce|a quoi)\b",
                                      q.lower())),
    }


def decider(query: str, availability: dict | None = None) -> RouteDecision:
    """Profil + poids + RAISON lisible. La raison est la partie utile : sans elle, une
    ponderation n'est qu'un nombre qu'on ne peut ni contester ni calibrer."""
    f = caracteriser(query)
    if f["chemin_fichier"] or f["identifiant"] or f["majuscules_rares"]:
        profil, motif = "exact", "identifiant, chemin ou sigle present"
    elif f["technique_regex_baseline"]:
        profil, motif = "technique", "motif technique de la regex baseline"
    elif f["interrogatif"] and f["longueur_mots"] >= 5:
        profil, motif = "conceptuel", "formulation interrogative et developpee"
    else:
        profil, motif = "hybride", "aucun trait dominant"

    p = dict(_PROFILS[profil])
    ctx = dict(availability or {})
    # REPORT, PAS PENALITE : si le canal vectoriel est indisponible, son poids passe au
    # lexical. Le penaliser reviendrait a conclure a la non-pertinence de ce qu'on n'a
    # pas pu voir -- exactement ce que la disponibilite par canal existe pour empecher.
    if ctx.get("vector") in ("PENDING", "REFUSED_BY_POLICY", "UNKNOWN"):
        p["lexical"] += p["vector"]
        p["vector"] = 0.0
        motif += f" ; vecteur indisponible ({ctx.get('vector')}) -> poids reporte au lexical"
    # Aucun canal structurel n'est branche dans le moteur : son poids ne doit pas
    # disparaitre en silence, il est reporte et le DIT.
    if p["structure"] and not ctx.get("structure_branche"):
        p["lexical"] += p["structure"]
        p["structure"] = 0.0
        motif += " ; canal structurel non branche -> poids reporte au lexical"

    return RouteDecision(lexical_weight=round(p["lexical"], 4),
                         vector_weight=round(p["vector"], 4),
                         structure_weight=round(p["structure"], 4),
                         reason=motif, profil=profil, features=f,
                         availability_context=ctx, mode=mode())


def fusionner(combined, decision: RouteDecision, rangs=None):
    """LE POINT DE BASCULE, et le seul.

    En SHADOW, rend l'objet d'entree LUI-MEME (identite, pas copie) : aucune
    modification du ranking n'est possible, et le test d'equivalence le prouve par
    `is`. En ACTIVE, applique les poids. Passer de l'un a l'autre ne demande aucun
    autre changement architectural -- c'est la condition posee par l'owner.
    """
    if decision.mode != ACTIVE:
        return combined
    if not rangs:
        return combined
    out = dict(combined)
    for idx, (r_lex, r_vec) in rangs.items():
        w = 0.0
        if r_lex is not None:
            w += decision.lexical_weight / (60.0 + r_lex + 1.0)
        if r_vec is not None:
            w += decision.vector_weight / (60.0 + r_vec + 1.0)
        out[idx] = w
    return out


# NATURES D'ARTEFACT — jamais confondues, c'est la condition pour qu'un chiffre veuille
# dire quelque chose. Une fixture qui passerait pour une observation reelle, ou une
# simulation pour un benchmark, fabriquerait un verdict a partir de rien.
OBSERVATION_REELLE = "OBSERVATION_REELLE"   # produite par le moteur, en conditions reelles
FIXTURE_TEST = "FIXTURE_TEST"               # jeu de test, ne vaut JAMAIS mesure
BASELINE = "BASELINE"                       # temoin fige de reference
SIMULATION = "SIMULATION"                   # recalcul hors moteur (replay)
_NATURES = (OBSERVATION_REELLE, FIXTURE_TEST, BASELINE, SIMULATION)

SCHEMA_OBSERVATION = 1
_COMMIT_CACHE: dict = {}


def engine_commit() -> str:
    """Commit du depot, lu UNE fois. Une observation sans version du moteur n'est pas
    rejouable : on ne saurait pas contre quel code elle a ete produite."""
    if "v" not in _COMMIT_CACHE:
        try:
            import subprocess

            r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(_RACINE),
                                "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True, errors="replace", timeout=15)
            _COMMIT_CACHE["v"] = (r.stdout or "").strip() or "INCONNU"
        except Exception as exc:  # noqa: BLE001
            _COMMIT_CACHE["v"] = f"INCONNU ({type(exc).__name__})"
    return _COMMIT_CACHE["v"]


def observer(query_id: str, query: str, decision: RouteDecision, resultats,
             kind: str = OBSERVATION_REELLE, contexte: dict | None = None) -> None:
    """Journal d'observation. Un score indisponible reste INDISPONIBLE, jamais 0.

    `kind` est OBLIGATOIREMENT l'une des natures declarees : une valeur inconnue est
    refusee plutot que journalisee sous une etiquette fausse.
    """
    if kind not in _NATURES:
        logger.warning("[router] nature d'artefact inconnue (%r) -- observation REFUSEE", kind)
        return
    try:
        _j = _chemin_journal()
        if _j.exists() and _j.stat().st_size > _JOURNAL_MAX_O:
            return
        ligne = {
            "schema": SCHEMA_OBSERVATION, "kind": kind, "engine_commit": engine_commit(),
            "ts": time.time(), "query_id": query_id, "query": (query or "")[:300],
            "mode": decision.mode, "decision": asdict(decision),
            # Le CONTEXTE de la recherche : sans lui, deux observations identiques en
            # apparence peuvent venir de pipelines differents (reranker actif ou non,
            # k different). Comparer sans lui melangerait des regimes distincts.
            "contexte": dict(contexte or {}),
            # AK3 : l'ORIGINE se pose a l'ECRITURE. La deduire a la lecture
            # supposerait qu'on sache apres coup d'ou vient une ligne — on ne le
            # sait pas. `PYTEST_CURRENT_TEST` n'est pose que dans un test.
            "origine": "test" if os.environ.get("PYTEST_CURRENT_TEST") else "runtime",
            "resultats": [{
                "chunk_id": r.get("chunk_id"),
                "rank": r.get("rank"),
                "lexical_score": r.get("lexical_score", "NOT_OBSERVABLE"),
                "vector_score": r.get("vector_score", "NOT_OBSERVABLE"),
                "structure_score": "NOT_OBSERVABLE",
                "final_score": r.get("final_score"),
                "availability": r.get("availability"),
            } for r in (resultats or [])],
        }
        with _j.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 - observer ne doit jamais casser une recherche
        logger.debug("[router] observation ignoree (%r)", exc)


# ── AK3 (2026-09-12) : CHIFFRER LE LEXICAL CONTRE LE DENSE ───────────────────
# Le journal porte `lexical_score` et `vector_score` par document depuis le
# 2026-09-08. Personne ne les confrontait. Ce comparateur le fait — et refuse de
# conclure tant que la matiere manque, plutot que de rendre un pourcentage bati
# sur une poignee de documents.
_SEUIL_OBSERVATIONS = 30


def _num(v):
    """Un score est un nombre, ou il n'est PAS. `NOT_OBSERVABLE` n'est pas zero :
    le confondre fait conclure a la non-pertinence de ce qu'on n'a pas pu voir."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def comparer_canaux(observations=None, seuil: int = _SEUIL_OBSERVATIONS) -> dict:
    """Quelle part du resultat le canal LEXICAL trouve-t-il seul ?

    C'est la question propre a AK3 : la baseline non generative doit etre
    chiffree AVANT d'ajouter du modele. Rend `MESURE` avec les taux, ou
    `NON_MESURABLE` **avec son denominateur** — jamais un taux sans matiere.

    Les observations etiquetees `origine="test"` sont ECARTEES : sans cela, la CI
    se calibre sur ses propres requetes.
    """
    _j = _chemin_journal()
    if observations is None:
        observations = []
        try:
            if _j.exists():
                for l in _j.read_text(encoding="utf-8",
                                      errors="replace").splitlines():
                    if l.strip():
                        try:
                            observations.append(json.loads(l))
                        except Exception:  # noqa: BLE001
                            pass
        except OSError as exc:
            return {"verdict": "ILLISIBLE", "raison": f"{type(exc).__name__}",
                    "journal": str(_j)}

    retenues, ecartees = [], 0
    for o in observations:
        if (o or {}).get("origine") == "test":
            ecartees += 1
        else:
            retenues.append(o)

    docs = lex_seul = vec_seul = les_deux = aucun = 0
    dense_non_obs = lex_non_obs = 0
    for o in retenues:
        for r in (o.get("resultats") or []):
            docs += 1
            lx, vc = _num(r.get("lexical_score")), _num(r.get("vector_score"))
            if lx is None:
                lex_non_obs += 1
            if vc is None:
                dense_non_obs += 1
            if lx is None or vc is None:
                continue  # hors denominateur : un canal muet n'est pas un echec
            if lx > 0 and vc > 0:
                les_deux += 1
            elif lx > 0:
                lex_seul += 1
            elif vc > 0:
                vec_seul += 1
            else:
                aucun += 1

    comparables = les_deux + lex_seul + vec_seul + aucun
    base = {
        "journal": str(_j),
        "observations_retenues": len(retenues),
        "observations_de_test_ecartees": ecartees,
        "seuil": seuil,
        "documents": docs,
        "documents_comparables": comparables,
        "documents_canal_dense_NON_OBSERVABLE": dense_non_obs,
        "documents_canal_lexical_NON_OBSERVABLE": lex_non_obs,
    }
    if len(retenues) < seuil or comparables == 0:
        base.update({
            "verdict": "NON_MESURABLE",
            "raison": "moins de %d observations hors test (ou aucun document "
                      "dont les DEUX canaux se soient exprimes)" % seuil,
            "taux_lexical_seul": None, "taux_dense_seul": None,
            "taux_les_deux": None, "taux_aucun": None,
        })
        return base
    base.update({
        "verdict": "MESURE",
        "taux_lexical_seul": round(100.0 * lex_seul / comparables, 1),
        "taux_dense_seul": round(100.0 * vec_seul / comparables, 1),
        "taux_les_deux": round(100.0 * les_deux / comparables, 1),
        "taux_aucun": round(100.0 * aucun / comparables, 1),
    })
    return base


def main() -> int:
    exemples = ["forge_tier_guard", "AUTH_FAILED OpenVPN",
                "comment eviter les regressions", "app/forge_rag_engine.py"]
    for q in exemples:
        d = decider(q, {"vector": "AVAILABLE"})
        print(json.dumps({"q": q, "profil": d.profil, "lex": d.lexical_weight,
                          "vec": d.vector_weight, "raison": d.reason},
                         ensure_ascii=False))
    print(json.dumps({"mode_courant": mode(),
                      "note": "SHADOW = calcule et journalise, n'applique RIEN"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
