#!/usr/bin/env python3
"""forge_recon_breaker.py — coupe-circuit COMPORTEMENTAL anti-fuite-tokens (transients).

Capte les recon FINES (read/grep/glob/Agent-Explore) sur le code Nokido et, au-delà
d'un seuil PAR SESSION, FORCE la délégation locale au lieu de laisser un client cloud
boucler (cf. fuite réelle 92k tokens cloud, 2026-06-20 : 31 reads/greps + Agent(Explore)
là où une seule recon LOCALE suffisait).

Partagé par DEUX étages (DRY, anti-dup) — c'est l'analyse TEMPORELLE qui manquait, les
gardes existants (forge_videur ring/RBAC par-appel, forge_lane_admission 1-job-lourd-par-lane)
ne comptent PAS les recon répétées :
  - client hook  : tools/forge_tool_gate.py  (PreToolUse Claude/Gemini)  -> verdict()
  - hub serveur  : app/forge_mcp_registry.dispatch (universel, tout client MCP) -> verdict()

Token-bucket disque par (session, kind), fenêtre glissante. Fail-open partout (un bug du
breaker ne doit JAMAIS casser un flux légitime). Bucket dans C:/tmp (écrivable owner ET
sandbox — le hook tourne owner, le hub tourne LaForgeSbxOffline ; chemin commun).
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : coupe-circuit comportemental anti-fuite de tokens"  # organe declare le 2026-09-06 (audit de raccordement)

import hashlib
import json
import time
from pathlib import Path

_DIR = Path("C:/tmp/nokido_recon_buckets")

# Seuils : les N premières recon Nokido passent (flux/trivial préservé — directive
# historique « ne pas tuer l'intelligence »), au-delà on bascule nudge puis deny.
_SOFT = 3          # n <= SOFT : allow ; SOFT < n <= HARD : nudge (conseil non bloquant)
_HARD = 6          # n  > HARD : deny (force la délégation locale)
_WINDOW_S = 900    # fenêtre glissante 15 min par (session, kind)

#: kinds soumis au breaker
RECON_KINDS = ("read", "search", "recon_agent")

#: directive renvoyée au client (honeypot : pointe l'outil de délégation locale).
HINT = (
    "recon lourde détectée -> DÉLÈGUE en LOCAL : outil hub `forge_deep_explore` "
    "{intent, target, breadth} (recon souveraine, 0 token cloud, renvoie une synthèse "
    "condensée), ou `forge_local_explore`. Tu es un CLIENT de Nokido, pas l'exécuteur."
)


# ── CLE DE GARDE = IDENTITE PROUVEE (racine R2, 17/10 ; derogations owner forge_mcp_registry + nokido_hub) ─────────
# Les compteurs ci-dessous etaient cles par NOM declare : un appelant non prouve repartait de zero en changeant de nom.
# Le hub pose la preuve (sujet_prouve de forge_videur, via _identite_inbox) dans cette ContextVar avant le dispatch ;
# ToolRegistry.dispatch ne voit pas la requete. Appel interne (rien de pose) : son nom, il ne peut forger un en-tete.
# OBSERVER AVANT D'ENFORCER : par defaut le compteur reste par nom et l'appel non prouve est JOURNALISE ;
# LAFORGE_GARDES_PAR_PREUVE=refus fait partager UN compteur a tout appel non prouve (decision owner, sur mesure).
import contextvars  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402

IDENTITE_PROUVEE: contextvars.ContextVar = contextvars.ContextVar("nokido_identite_prouvee", default=None)
NON_PROUVE = "NON_PROUVE"
_OBSERVES: dict = {}
_log_garde = logging.getLogger("Nokido.ReconBreaker")


def poser_preuve(prouve):
    """Pose la preuve de l'appel en cours ; None = appel interne, rien n'est pose. Rend le jeton de `retirer_preuve`."""
    if prouve is None:
        return None
    return IDENTITE_PROUVEE.set(bool(prouve))


def retirer_preuve(jeton) -> None:
    if jeton is not None:
        IDENTITE_PROUVEE.reset(jeton)


def cle_de_garde(agent) -> str:
    """Cle des compteurs de garde (liste blanche : seule une preuve True garde son nom en mode refus)."""
    nom = str(agent or "HUB")
    prouve = IDENTITE_PROUVEE.get()
    if prouve is None:
        return nom
    if os.environ.get("LAFORGE_GARDES_PAR_PREUVE", "observe").strip().lower() != "refus":
        if prouve is not True and time.time() - _OBSERVES.get(nom, 0.0) > 600:
            _OBSERVES[nom] = time.time()
            _log_garde.warning("[cle_de_garde] observe : appel NON PROUVE sous le nom %s -- en mode refus il "
                               "partagerait le compteur %s (compteur par nom inchange)", nom, NON_PROUVE)
        return nom
    return nom.upper() if prouve is True else NON_PROUVE


def _key(session: str, kind: str) -> Path:
    h = hashlib.sha1(f"{session}:{kind}".encode("utf-8")).hexdigest()[:16]
    return _DIR / f"{h}.json"


def hit(session: str, kind: str) -> int:
    """Incrémente le compteur (session, kind) dans la fenêtre glissante et le renvoie.

    Fail-open -> 0 (le verdict traitera 0 comme 'allow')."""
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        p = _key(session or "UNKNOWN", kind)
        now = time.time()
        hits: list[float] = []
        if p.exists():
            try:
                hits = [float(t) for t in json.loads(p.read_text(encoding="utf-8"))]
            except Exception:
                hits = []
        hits = [t for t in hits if now - t < _WINDOW_S]
        hits.append(now)
        p.write_text(json.dumps(hits[-64:]), encoding="utf-8")
        return len(hits)
    except Exception:
        return 0


def verdict(session: str, kind: str, is_nokido: bool) -> tuple[str, str, int]:
    """('allow' | 'nudge' | 'deny', reason, count).

    N'agit QUE sur la recon de code Nokido. Agent(Explore)/Task sur Nokido = recon
    cloud massive -> deny direct (le coût était précisément là)."""
    if kind not in RECON_KINDS or not is_nokido:
        return ("allow", "", 0)
    n = hit(session, kind)
    if kind == "recon_agent":
        return ("deny", f"Agent(Explore) sur code Nokido = recon cloud facturée. {HINT}", n)
    if n > _HARD:
        return ("deny", f"{n} recon/{kind} Nokido en {_WINDOW_S // 60} min. {HINT}", n)
    if n > _SOFT:
        return ("nudge", f"recon Nokido répétée ({n}/{kind}) — pense `forge_deep_explore`.", n)
    return ("allow", "", n)


def is_nokido_args(args) -> bool:
    """Heuristique : les arguments d'outil visent-ils le code/système Nokido ?"""
    try:
        t = " ".join(str(v) for v in (args or {}).values()).lower()
    except Exception:
        return False
    return ("laforge" in t) or ("forge_" in t) or ("script python ia" in t)


# --- Phase 2 COTE HUB (owner 17/10 : « les garde fous doivent emaner du hub... et pareil pour les autres cli ») ----------
# Un run qui ouvre un fichier de CODE du depot est une LECTURE. Mesure 17/10 : CLAUDE relisait le depot par read_text dans
# `run action=python` apres le disjoncteur -- le hub executait sans compter, seul l'outil `read` passait ici. Un journal,
# un etat (sandbox/) ou un calcul n'en sont pas : le garde vise la recon de code, pas la mesure.
import re as _re

_LECTURE = _re.compile(r"read_text|read_bytes|\bopen\s*\(|Get-Content|\btype\s|\bcat\s|\bmore\s|\bhead\s|\btail\s"
                       r"|\bsed\s+-n", _re.I)
_FICHIER_CODE = _re.compile(r"(?:^|[\\/\"'\s(])(?:app|tools|tests|proxy_deno)[\\/][^\s\"')]*\.(?:py|ts|toml|md)\b", _re.I)


def lit_le_depot(code: str) -> bool:
    """Le code passe a `run` (python ou shell) ouvre-t-il un fichier de CODE du depot ?"""
    t = str(code or "")
    return bool(_LECTURE.search(t) and _FICHIER_CODE.search(t))


# IMPULSION comptee par le HUB, par identite d'agent (phase 2, brique E). Meme coeur que le hook de Claude
# (hook_capability_gate.compter_tour) : pas une seconde logique, une seconde PORTEE -- tous les clients MCP, agy et vibe
# compris, qui n'ont pas les hooks de Claude Code.
IMPULSION = Path(__file__).resolve().parent.parent / "sandbox" / "impulsion_agents.json"


def _etat_impulsion(qui: str) -> tuple:
    """(etat de tous les agents, fenetre de `qui`) ; absent ou illisible = fenetre vide."""
    try:
        d = json.loads(IMPULSION.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # muet-ok : etat absent ou illisible = fenetre vide
        d = {}
    d = d if isinstance(d, dict) else {}
    return d, (d.get(qui) or {})


def impulsion(agent: str, maintenant: float | None = None) -> tuple:
    """(statut, message) : None, 'avertissement' (2e tour en 90 s) ou 'refus' (3e et au-dela), par identite d'agent."""
    try:
        from nokido_agent.tools.hook_capability_gate import compter_tour
    except ImportError:
        from hook_capability_gate import compter_tour  # type: ignore
    t = time.time() if maintenant is None else maintenant
    qui = str(agent or "HUB").upper()
    try:
        d, a = _etat_impulsion(qui)
        tours, dernier, n = compter_tour(a.get("tours"), a.get("dernier"), t)
        d[qui] = {"tours": tours, "dernier": dernier}
        IMPULSION.parent.mkdir(parents=True, exist_ok=True)
        IMPULSION.write_text(json.dumps(d), encoding="utf-8")
    except Exception:  # noqa: BLE001 - muet-ok : un garde ne casse jamais son porteur
        return (None, "")
    if n <= 1:
        return (None, "")
    if n == 2:
        return ("avertissement", "[impulsion hub] 2e tour de sondes en 90 s pour %s : au 3e, refus (mode refus). "
                                 "Fusionner en UN script ou run_job." % qui)
    return ("refus", "[impulsion hub] %de tour de sondes en 90 s pour %s : fusionner en UN script ou run_job." % (n, qui))


def impulsion_remise(agent: str) -> None:
    """Une ecriture (governed_edit) remet la fenetre de l'agent a zero, comme dans le hook."""
    try:
        qui = str(agent or "HUB").upper()
        d, a = _etat_impulsion(qui)
        if qui in d:
            del d[qui]
            IMPULSION.write_text(json.dumps(d), encoding="utf-8")
    except Exception:  # noqa: BLE001 - muet-ok : un garde ne casse jamais son porteur
        pass


# Le registre des CONSULTATIONS par agent existe deja cote hub : app/forge_introspect.py (consultation_recente,
# noter_edition, lu par le handler governed_edit depuis le 31/08). C'est LUI qu'on etend au domaine -- un second
# registre ici a ete ecrit puis retire le 17/10 (anti-dup).


# --- Variante IN-MEMORY (hub : process long-vécu, évite WORKSPACE_GUARD / FS) ---
_MEM: dict = {}


def hit_mem(key: str, kind: str) -> int:
    """Compteur recon EN MÉMOIRE process (pour le hub). Même fenêtre glissante."""
    import time as _t
    now = _t.time()
    k = f"{key}:{kind}"
    h = [t for t in _MEM.get(k, []) if now - t < _WINDOW_S]
    h.append(now)
    _MEM[k] = h[-64:]
    return len(h)


def verdict_mem(key: str, kind: str, is_nokido: bool) -> tuple[str, str, int]:
    """Comme verdict() mais compteur EN MÉMOIRE (hub-side, universel tout client MCP)."""
    if kind not in RECON_KINDS or not is_nokido:
        return ("allow", "", 0)
    n = hit_mem(key or "UNKNOWN", kind)
    if kind == "recon_agent":
        return ("deny", f"Agent(Explore) sur code Nokido = recon cloud. {HINT}", n)
    if n > _HARD:
        return ("deny", f"{n} recon/{kind} Nokido en {_WINDOW_S // 60} min. {HINT}", n)
    if n > _SOFT:
        return ("nudge", f"recon Nokido répétée ({n}/{kind}).", n)
    return ("allow", "", n)


def reset(session: str) -> int:
    """Purge les buckets d'une session (ex. après une délégation réussie). -> nb purgés."""
    cnt = 0
    try:
        for kind in RECON_KINDS:
            p = _key(session or "UNKNOWN", kind)
            if p.exists():
                p.unlink()
                cnt += 1
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_recon_breaker.py', 255, exc_info=True)
    return cnt
