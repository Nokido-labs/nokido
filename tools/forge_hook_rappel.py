"""forge_hook_rappel.py -- un rappel de hook deja montre a l'identique n'est pas reinjecte (P1a, GO owner 22/10).

__FORGE_COLOR__ = 'metabolisme-llm/regulation'

Mesure P0 (22/10, tools/forge_contexte_par_source.py) : les injections de hooks pesent 7-8 % du cout de relecture
d'une session, et 60-67 % d'entre elles repetent mot pour mot un texte deja dans le contexte. Ce module ETEND
`claude_inbox_tick._sans_repetition`, qui ne couvrait que les sections [memoire...], a toute section ouverte par une
balise `[...]` et a tous les hooks (UserPromptSubmit, PreToolUse). Leger a l'import : chaque appel d'outil le charge.

Rien de la reflexion ne se perd :
  - seul un texte IDENTIQUE, deja montre a CETTE session, est retire ; un texte qui change revient ;
  - il revient de toute facon apres RAPPEL_S (LAFORGE_MEMOIRE_RAPPEL_S, defaut 3600 s) ;
  - `oublier(session)` a chaque compaction ou /clear (claude_session_start) : tout revient une fois ;
  - un REFUS (deny) ne passe jamais par ici, seul le texte additionnel non bloquant est filtre ;
  - etat illisible ou session inconnue : tout est montre (jamais de silence par defaut).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

RAPPEL_S = int(os.environ.get("LAFORGE_MEMOIRE_RAPPEL_S", "3600"))
_PLAFOND_ENTREES = 2000


def _racine_etat():
    """Dossier d'etat sous la racine de DONNEES canonique (forge_db_path.racine_donnees, cliquet racine_donnees) ;
    None si la primitive est introuvable -- le filtre s'ouvre alors (on montre tout)."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except Exception:  # noqa: BLE001
        try:
            from forge_db_path import racine_donnees
        except Exception:  # noqa: BLE001
            return None
    return racine_donnees() / "sandbox" / "claude_hook_state"


def _dossier(etat_dir=None):
    d = etat_dir or os.environ.get("LAFORGE_HOOK_RAPPEL_DIR") or _racine_etat()
    return Path(d) if d else None


def _fichier(session: str, etat_dir=None):
    d = _dossier(etat_dir)
    return d / ("rappels_%s.json" % "".join(c for c in session if c.isalnum() or c in "-_")[:80]) if d else None


def _sections(texte: str) -> list[str]:
    sections, courante = [], None
    for ligne in texte.splitlines():
        if courante is None or ligne.startswith("["):
            courante = [ligne]
            sections.append(courante)
        else:
            courante.append(ligne)
    return ["\n".join(s) for s in sections]


def filtrer(texte, session, maintenant=None, etat_dir=None, rappel_s=None):
    """Retire de `texte` les sections deja montrees a l'identique a cette session dans la fenetre de rappel.
    -> texte restant, ou None s'il ne reste rien."""
    if not texte or not session:
        return texte or None
    fichier = _fichier(session, etat_dir)
    if fichier is None:
        return texte      # racine de donnees introuvable : on montre tout
    maintenant = time.time() if maintenant is None else float(maintenant)
    rappel_s = RAPPEL_S if rappel_s is None else rappel_s
    try:
        vu = json.loads(fichier.read_text(encoding="utf-8"))
        if not isinstance(vu, dict) or not all(isinstance(v, (int, float)) for v in vu.values()):
            vu = {}      # ancien format (titre -> [empreinte, t]) ou contenu inattendu : on montre tout, une fois
    except Exception:  # noqa: BLE001 -- premier tour de la session, ou etat illisible : on montre tout
        vu = {}
    garde = []
    for sec in _sections(texte):
        empreinte = hashlib.sha1(sec.encode("utf-8", "replace")).hexdigest()[:16]
        if maintenant - float(vu.get(empreinte, -1e18)) < rappel_s:
            continue
        vu[empreinte] = maintenant
        garde.append(sec)
    vu = {k: t for k, t in vu.items() if maintenant - t < rappel_s}
    if len(vu) > _PLAFOND_ENTREES:
        vu = dict(sorted(vu.items(), key=lambda kv: kv[1])[-_PLAFOND_ENTREES:])
    try:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        tmp = fichier.with_suffix(".%d.tmp" % os.getpid())
        tmp.write_text(json.dumps(vu), encoding="utf-8")
        os.replace(tmp, fichier)
    except Exception as e:  # noqa: BLE001 -- l'etat ne s'ecrit pas : au pire on re-montre, on le DIT
        print("[hook-rappel] etat non ecrit (%s) : repetition possible" % type(e).__name__, file=sys.stderr)
    return "\n".join(garde) or None


def oublier(session, etat_dir=None) -> bool:
    """Compaction ou /clear : le contexte repart de zero, chaque rappel doit revenir une fois."""
    fichier = _fichier(session, etat_dir) if session else None
    if fichier is None:
        return False
    try:
        fichier.unlink()
        return True
    except FileNotFoundError:
        return False
    except Exception as e:  # noqa: BLE001
        print("[hook-rappel] oubli impossible (%s) : un rappel peut manquer apres la compaction"
              % type(e).__name__, file=sys.stderr)
        return False
