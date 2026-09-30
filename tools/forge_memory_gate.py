"""forge_memory_gate — P2a du homeostat axiologique : filtre qualite AVANT
ingest/consolidation (foie/intestin). Anti-confabulation.

PROBLEME mesure : le RAG consolidait du BRUIT (reponses vides du daemon gemini) et
ingerait du web non-fiable (source_discovery duckduckgo) sans gate. qualify_for_ingest
QUALIFIE (calcule un trust) mais ne REJETTE rien.

P2a = un GATE avant INSERT rag_chunks : rejette le bruit (vide/trivial/placeholder),
plafonne le trust des sources web faibles, gate sur trust minimal. REUTILISE
forge_rag_qualify.qualify_for_ingest (n'invente pas le scoring). Invariant P0 :
memory_quality_gate. Source : docs/ALIGNMENT_HOMEOSTAT_ROADMAP.md (P2a).

Selftest : LAFORGE_PYTHON tools/forge_memory_gate.py
"""
from __future__ import annotations
import re

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# Placeholders de bruit connus (le daemon gemini consolidait "(reponse vide)").
_NOISE_RX = re.compile(r"^\s*\(?\s*(reponse\s+vide|empty|n/?a|none|null|\.\.\.|todo|tbd)\s*\)?\s*$", re.IGNORECASE)
_MIN_CHARS = 24  # contenu sous ce seuil = trivial = bruit
_LOW_TRUST_SOURCES = ("reddit.com", "linkedin.com", "quora.com", "medium.com", "facebook.com", "x.com", "twitter.com")
_LOW_TRUST_CAP = 0.3


def _confiance(meta) -> tuple:
    """(trust, etat) — V1 (2026-09-12) : un ETAT NOMME, plus un 0.5 par defaut.

    L'ancienne version rendait `0.5` dans TROIS situations distinctes : le
    qualifieur indisponible (`meta` None), le qualifieur muet sur la confiance,
    et… un vrai 0.5 mesure. Or 0.5 passe le seuil (`min_trust` 0.2) : une panne
    du capteur se lisait donc « confiance moyenne » et tout entrait en base, le
    gate restant vert en n'ayant rien controle.

    Fabriquer un nombre la ou il n'y a pas de mesure est la faute — qu'on le
    fabrique bas (et l'on conclut a tort a la non-pertinence) ou moyen (et l'on
    ouvre la porte). `None` + un etat nomme laissent la decision a l'appelant.
    """
    if not isinstance(meta, dict):
        return None, "NON_QUALIFIABLE"
    for k in ("trust_weight", "trust", "trust_score", "score"):
        v = meta.get(k)
        if isinstance(v, (int, float)):
            return float(v), "QUALIFIE"
    return None, "SANS_CHAMP_DE_CONFIANCE"


def _emit_indetermine(source: str, etat: str, motif: str) -> None:
    """Un fail-open MUET est indistinguable d'un fonctionnement normal.

    Celui-ci s'annonce : le jour ou le qualifieur meurt, la trace le dit au lieu
    de laisser un gate vert qui n'a rien mesure.
    """
    _tracer("indetermine", etat, source, motif)


def _tracer(verdict: str, kind: str, source: str, detail: str) -> None:
    """Trace d'alignement — un seul corps pour tous les verdicts du gate.

    V1 (2026-09-12) : l'ajout d'`_emit_indetermine` avait duplique mot pour mot
    `_emit_reject` a un litteral pres, et le cliquet de duplication l'a vu (« 1
    groupe de clones nouveau : tools/forge_memory_gate.py »). Le verdict devient
    donc un PARAMETRE. Ne leve jamais : une trace absente ne doit pas empecher
    une ingestion.
    """
    try:
        from nokido_agent.tools.forge_alignment_trace import emit as _atrace
        _atrace("ingest", "memory_quality_gate", verdict, str(source)[:80],
                f"{kind}: {detail}")
    except Exception:
        pass


def _emit_reject(kind: str, source: str, reason: str) -> None:
    _tracer("reject", kind, source, reason)


def should_ingest(text: str, source: str = "", domain: str = "", author: str = "",
                  min_trust: float = 0.2) -> dict:
    """Gate avant INSERT rag_chunks. Retourne {ok, reason, meta, trust}."""
    t = (text or "").strip()
    # 1. Bruit : vide / trivial / placeholder
    if not t or len(t) < _MIN_CHARS or _NOISE_RX.match(t):
        _emit_reject("noise", source, f"len={len(t)}")
        # `trust` est None et non 0.0 : rien n'a ete mesure ici, et un zero se
        # lit comme une confiance mesuree nulle.
        return {"ok": False, "reason": f"bruit (len={len(t)})", "meta": None,
                "trust": None, "etat_confiance": "BRUIT",
                "motif_non_qualifiable": None}
    # 2. Qualification (reutilise l'existant)
    meta, motif_ko = None, None
    try:
        from nokido_agent.app.forge_rag_qualify import qualify_for_ingest
        meta = qualify_for_ingest(text=t, source=source, domain=domain, author=author)
    except Exception as exc:  # noqa: BLE001
        # Le motif est CONSERVE : sans lui, une dependance absente (ImportError)
        # ne se distingue pas d'un qualifieur qui plante (RuntimeError), et les
        # deux appellent des gestes differents.
        motif_ko = f"{type(exc).__name__}: {str(exc)[:90]}"
    trust, etat = _confiance(meta)

    src_low = any(d in (source or "").lower() for d in _LOW_TRUST_SOURCES)

    # 3. Confiance NON MESUREE : fail-open assume, mais NOMME et TRACE.
    if trust is None:
        motif = motif_ko or "le qualifieur n'expose aucun champ de confiance"
        _emit_indetermine(source, etat, motif)
        return {"ok": True,
                "reason": f"{etat} ({motif})"
                          + (" [low-trust source]" if src_low else ""),
                "meta": meta, "trust": None, "etat_confiance": etat,
                "motif_non_qualifiable": motif_ko}

    # 4. Source web faible -> plafonne le trust (accepte si substantiel, mais marque)
    if src_low:
        trust = min(trust, _LOW_TRUST_CAP)
        etat = "SOURCE_PLAFONNEE"

    # 5. Gate trust minimal — ici, et ici SEULEMENT, le refus repose sur une mesure
    if trust < min_trust:
        _emit_reject("low_trust", source, f"trust {trust:.2f} < {min_trust}")
        return {"ok": False, "reason": f"trust {trust:.2f} < {min_trust}",
                "meta": meta, "trust": trust, "etat_confiance": etat,
                "motif_non_qualifiable": None}
    return {"ok": True,
            "reason": "ok" + (" [low-trust source]" if src_low else ""),
            "meta": meta, "trust": trust, "etat_confiance": etat,
            "motif_non_qualifiable": None}


def selftest() -> bool:
    cases = [
        ("(reponse vide)", "gemini_poll_daemon", False),
        ("", "x", False),
        ("ok", "x", False),  # trivial
        ("TBD", "x", False),
        ("Un vrai contenu substantiel sur l'alignement IA et la corrigibilite des agents.",
         "https://arxiv.org/abs/2401.05566", True),
        ("Un contenu substantiel mais source faible : un long thread de discussion reddit ici.",
         "https://www.reddit.com/r/agi/x", True),  # accepte mais low-trust
    ]
    allok = True
    for text, src, expect in cases:
        r = should_ingest(text, source=src)
        verdict = "OK " if r["ok"] == expect else "FAIL"
        if r["ok"] != expect:
            allok = False
        # V1 : `trust` peut valoir None — une confiance NON MESUREE ne se
        # formate pas comme un nombre. Le format s'adapte au lieu de lever, et
        # l'etat nomme est affiche a cote : c'est lui qui porte l'information.
        _t = "  n/a" if r["trust"] is None else f"{r['trust']:5.2f}"
        print(f"  [{verdict}] ok={r['ok']!s:5} trust={_t} "
              f"{r['etat_confiance']:24} ({r['reason']:28}) :: {text[:30]!r}")
    print("P2a MEMORY GATE:", "PASS" if allok else "FAIL")
    return allok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
