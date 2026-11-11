"""forge_run_sortie.py -- sortie de `run` bornee A L'ENTREE pour les agents LLM (P1 levier 2, GO owner 22/10).

__FORGE_COLOR__ = 'metabolisme-llm/regulation'

Mesure P0 (22/10, tools/forge_contexte_par_source.py) : les resultats de `run` pesent 11-17 % du cout de relecture
d'une session, les resultats intermediaires des chaines d'outils 22-24 %. Une sortie de 40 000 caracteres entre dans
le contexte et y est RELUE a chaque tour suivant. Veille (token-optimizer-mcp `v1-frontier`, `tee` de rtk) : on
compresse a l'ENTREE seulement -- jamais l'historique deja en cache -- et le retrait est REVERSIBLE.

Contrat :
  - borne seulement les identites d'agents LLM (LISTE BLANCHE) : des demons internes cherchent une chaine n'importe
    ou dans la sortie (en-tete `timed_out=`, `PYTEST_RC: 0`) -- une identite inconnue recoit la sortie intacte ;
  - au-dela de SEUIL_CAR : tete + fin (en-tete et bilan restent lisibles) + volume + chemin du fichier complet ;
  - le fichier recoit la version CAVIARDEE (forge_semantic_firewall.redact_tool_output) ; caviardage ou ecriture
    impossible -> rien n'est deverse et la sortie est rendue ENTIERE (jamais de perte par defaut) ;
  - `sortie_complete=true` dans les arguments de `run` rend tout.
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

SEUIL_CAR = int(os.environ.get("LAFORGE_RUN_SORTIE_SEUIL", "12000"))
TETE_CAR = int(os.environ.get("LAFORGE_RUN_SORTIE_TETE", "4000"))
FIN_CAR = int(os.environ.get("LAFORGE_RUN_SORTIE_FIN", "4000"))

AGENTS_LLM = frozenset({
    "CLAUDE", "CLAUDE_HEADLESS", "CLAUDE_API", "BRIDGE", "GEMINI", "CODEX", "VIBE", "VIBE_CLI", "ANTIGRAVITY", "AGY",
    "CLINE", "COPILOT", "MAMMOUTH", "OPENCODE",
})


def est_agent_llm(agent) -> bool:
    a = str(agent or "").strip().upper()
    if a.startswith("AGT_"):
        a = a[4:]
    return a in AGENTS_LLM or a.startswith("OPENCODE_")


def _dossier(dossier=None) -> Path:
    if dossier:
        return Path(dossier)
    if os.environ.get("LAFORGE_RUN_SORTIE_DIR"):
        return Path(os.environ["LAFORGE_RUN_SORTIE_DIR"])
    from nokido_agent.app.forge_db_path import racine_donnees
    return racine_donnees() / "sandbox" / "run_sorties"


def _caviarder(texte: str):
    """Version caviardee de la sortie, ou None si le caviardage est indisponible."""
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_tool_output
        redige, _bilan = redact_tool_output(texte, "run")
        return redige
    except Exception:  # noqa: BLE001 -- muet-ok : None = pas de deversement, la sortie est rendue entiere
        return None


def _tete(texte: str, n: int) -> str:
    coupe = texte.rfind("\n", 0, n)
    return texte[: coupe + 1 if coupe > 0 else n]


def _fin(texte: str, n: int) -> str:
    debut = texte.find("\n", len(texte) - n)
    return texte[debut + 1 if 0 <= debut < len(texte) - 1 else len(texte) - n:]


def borner(texte, agent, args=None, dossier=None):
    if (not isinstance(texte, str) or len(texte) <= SEUIL_CAR or not est_agent_llm(agent)
            or (args or {}).get("sortie_complete")):
        return texte
    complet = _caviarder(texte)
    if not complet:
        return texte
    try:
        d = _dossier(dossier)
        d.mkdir(parents=True, exist_ok=True)
        nom = "run_%s_%s.txt" % (time.strftime("%Y%m%d_%H%M%S"),
                                 hashlib.sha1(texte.encode("utf-8", "replace")).hexdigest()[:8])
        chemin = d / nom
        chemin.write_text(complet, encoding="utf-8")
        try:
            try:
                from nokido_agent.app.forge_context_ledger import observer
            except ImportError:
                try:
                    from app.forge_context_ledger import observer
                except ImportError:
                    from forge_context_ledger import observer
            essence = ""
            for l in complet.splitlines():
                s = l.strip()
                if s:
                    essence = s[:150]
                    break
            racine_obs = (
                chemin.parent.parent.parent
                if chemin.parent.name == "run_sorties" and chemin.parent.parent.name == "sandbox"
                else None
            )
            observer("run_sortie://" + nom, essence=essence, racine=racine_obs)
        except Exception:  # noqa: BLE001 -- observation seule : jamais casser le bornage
            __import__("logging").getLogger(__name__).debug("observation context_ledger impossible", exc_info=True)
    except Exception:  # noqa: BLE001 -- muet-ok : ecriture impossible = rien de deverse, la sortie est rendue entiere
        return texte
    tete, fin = _tete(texte, TETE_CAR), _fin(texte, FIN_CAR)
    omis = len(texte) - len(tete) - len(fin)
    lignes = texte.count("\n") + 1
    avis = ("\n[run] sortie bornee pour le contexte : %d caracteres, %d lignes ; %d caracteres omis ICI, rien de "
            "perdu. Sortie complete (caviardee) : %s -- la relire par Read offset/limit, ou relancer avec "
            "sortie_complete=true.\n" % (len(texte), lignes, omis, chemin))
    return tete + avis + fin
