# -*- coding: utf-8 -*-
"""forge_palier_effort -- UNE table : modele ET effort par taille de tache (S|M|L) et par surface headless.

Levier A (owner 23/10). Source UNIQUE : l'executeur (`_MODELE_CLAUDE_PAR_TAILLE`, `_args_claude`) et la facade
`nokido_headless` la consomment, aucune valeur n'est dispersee.

Regles :
- un modele que le census (sandbox/free_tier_census.json) PROUVE a 0 req/min est REFUSE, jamais tente ;
- un drapeau d'effort se LIT dans l'aide du binaire (DRAPEAUX_LUS) ; drapeau absent = UNKNOWN journalise, pas d'invention ;
- S = bas, M = bas, L = moyen ; effort HAUT seulement sur escalade apres echec VERIFIE (nr_rouge | juge), jamais par defaut.
"""
from __future__ import annotations

import logging
from pathlib import Path

__FORGE_COLOR__ = "interface/lanceur_client : table unique modele+effort par palier S|M|L (levier A)"

_LOG = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parent.parent

TAILLES = ("S", "M", "L")
SURFACES = ("claude", "agy", "vibe", "opencode", "claude_api", "codex")
ESCALADES = ("nr_rouge", "juge")          # echecs VERIFIES : seuls motifs d'un effort haut
EFFORT_ESCALADE = "high"
EFFORTS_HAUTS = ("high", "xhigh", "max")

# Fournisseur tel que nomme au census (cle `fournisseur:modele`).
FOURNISSEUR = {"claude": "anthropic", "agy": "google", "vibe": "mistral", "opencode": "ollama", "claude_api": "anthropic", "codex": "openai"}

# Drapeaux d'effort LUS dans l'aide du binaire. `drapeau` None = absent/illisible = UNKNOWN.
DRAPEAUX_LUS = {
    # codex : cle `model_reasoning_effort` VERIFIEE dans config-reference.md (30/10), passee par `codex exec -c`.
    "codex": {"drapeau": "-c model_reasoning_effort", "commande_aide": "developers.openai.com/codex/config-file/config-reference.md",
              "niveaux_aide": ("low", "medium", "high")},
    "claude": {"drapeau": "--effort", "commande_aide": "claude --help",
               "niveaux_aide": ("low", "medium", "high", "xhigh", "max")},
    # agy : aide RELUE le 30/10 (sortie owner) : --effort low|medium|high|xhigh|max, --model, `agy models`.
    "agy": {"drapeau": "--effort", "commande_aide": "agy --help (relue le 30/10, sortie owner)",
            "niveaux_aide": ("low", "medium", "high", "xhigh", "max")},
    "vibe": {"drapeau": None, "commande_aide": "vibe --help (non relue le 23/10 : binaire hors portee)",
             "niveaux_aide": ()},
    "opencode": {"drapeau": None, "commande_aide": "opencode run --help (non relue le 23/10 : binaire hors portee)",
                 "niveaux_aide": ()},
    "claude_api": {"drapeau": "effort", "commande_aide": "API Messages : parametre effort (doc platform.claude.com)",
                   "niveaux_aide": ("low", "medium", "high")},
}

# LA table : (modele, effort) par surface et taille. Effort None = pas de drapeau connu.
TABLE = {
    # modele None : celui du profil Codex de l'owner (aucun modele Codex mesure au census) ; seul l'effort est regle.
    # aligne sur _EFFORT_CODEX_PAR_TAILLE (decision deja en place, NR test_codex_effort_selon_taille_nr)
    "codex": {"S": (None, "low"), "M": (None, "medium"), "L": (None, "high")},
    "claude": {"S": ("claude-haiku-5-5", "low"), "M": ("claude-sonnet-5-5", "low"), "L": ("claude-opus-5-5", "medium")},
    # agy (owner 30/10 « Gemini 4 Argon tres puissant mais vide les tokens ») : modele LEGER pose par taille, jamais le
    # /model de l'owner par defaut ; `agy models` (30/10) : gemini-3.8-flash-{low,medium,high}, gemini-4-argon-* --
    # Argon reserve a l'escalade verifiee, jamais par defaut.
    "agy": {"S": ("gemini-3.8-flash-low", "low"), "M": ("gemini-3.8-flash-low", "low"),
            "L": ("gemini-3.8-flash-medium", "medium")},
    "vibe": {t: ("codestral-latest", None) for t in TAILLES},
    # opencode : S local (Ollama, 0 jeton cloud) ; M/L = modele de l'instance (config), non pose par la facade.
    "opencode": {"S": ("qwen2.5-coder:7b", None), "M": (None, None), "L": (None, None)},
    "claude_api": {"S": ("claude-haiku-5-5", "low"), "M": ("claude-sonnet-5-5", "low"), "L": ("claude-opus-5-5", "medium")},
}

# Efforts supportes par modele connu sur sa surface.
# Modele absent = pas de plafond connu (INCONNU, on ne bride pas).
# Faits tires de DRAPEAUX_LUS, TABLE, `agy models` (30/10) et platform.claude.com.
EFFORTS_SUPPORTES: dict[tuple[str, str], tuple[str, ...]] = {
    # agy : gemini-3.8-flash-{low,medium,high} supportent low, medium, high selon `agy models`
    ("agy", "gemini-3.8-flash-low"): ("low", "medium", "high"),
    ("agy", "gemini-3.8-flash-medium"): ("low", "medium", "high"),
    # claude_api : platform.claude.com specifie low, medium, high pour l'API Messages
    ("claude_api", "claude-haiku-5-5"): ("low", "medium", "high"),
    ("claude_api", "claude-sonnet-5-5"): ("low", "medium", "high"),
    ("claude_api", "claude-opus-5-5"): ("low", "medium", "high"),
    # claude CLI : aide binaire
    ("claude", "claude-haiku-5-5"): ("low", "medium", "high", "xhigh", "max"),
    ("claude", "claude-sonnet-5-5"): ("low", "medium", "high", "xhigh", "max"),
    ("claude", "claude-opus-5-5"): ("low", "medium", "high", "xhigh", "max"),
}

ORDRE_EFFORT = ("low", "medium", "high", "xhigh", "max")


def borner_effort(surface: str, modele: str | None, effort: str | None) -> tuple[str | None, str | None]:
    """Si l'effort demande n'est pas supporte pour ce (surface, modele), rend le plus haut
    niveau supporte INFERIEUR et un motif ; sinon (effort, None).
    Un modele absent de EFFORTS_SUPPORTES = pas de plafond connu (INCONNU, inchange)."""
    if effort is None or modele is None:
        return effort, None
    cle = (surface, modele)
    if cle not in EFFORTS_SUPPORTES:
        return effort, None
    supportes = EFFORTS_SUPPORTES[cle]
    if effort in supportes:
        return effort, None
    # Chercher le plus haut niveau supporte inferieur a `effort`
    if effort in ORDRE_EFFORT:
        idx = ORDRE_EFFORT.index(effort)
        candidats_inferieurs = [niv for niv in ORDRE_EFFORT[:idx] if niv in supportes]
        if candidats_inferieurs:
            repli = candidats_inferieurs[-1]
            motif = "effort %r non supporte par %s:%s -> borne a %r" % (effort, surface, modele, repli)
            return repli, motif
    # Effort demande SOUS tous les niveaux supportes (ou hors echelle) : le plus BAS supporte -- un bornage
    # n'augmente jamais l'effort (et donc le cout) au-dela du minimum accepte par le modele.
    repli = supportes[0] if supportes else effort
    motif = "effort %r non supporte par %s:%s -> borne a %r" % (effort, surface, modele, repli)
    return repli, motif

_TOURS_CLAUDE = {"S": 15, "M": 40, "L": 80}


class ModeleHorsQuota(ValueError):
    """Le census prouve le modele hors d'usage (0 req/min ou mort) : refuse, jamais tente."""


def _taille(valeur) -> str:
    t = str(valeur if valeur is not None else "M").strip().upper()
    if t not in TAILLES:
        raise ValueError("taille refusee : %r (attendu : %s)" % (valeur, "|".join(TAILLES)))
    return t


def modele_de(surface: str, taille: str):
    """Modele de la table (sans census) -- pour les modules qui derivent leur constante de la table."""
    return TABLE[surface][_taille(taille)][0]


def resoudre(surface: str, taille="M", effort=None, escalade=None, census=None) -> dict:
    """Modele + effort retenus pour (surface, taille). ValueError : surface/taille/escalade/effort refuses ;
    ModeleHorsQuota : census a 0 req/min. `effort` n'est accepte que s'il n'est pas haut (sinon escalade exigee)."""
    if surface not in TABLE:
        raise ValueError("surface refusee : %r (attendu : %s)" % (surface, "|".join(SURFACES)))
    t = _taille(taille)
    if escalade is not None and escalade not in ESCALADES:
        raise ValueError("escalade refusee : %r (preuve attendue : %s)" % (escalade, "|".join(ESCALADES)))
    if effort in EFFORTS_HAUTS and escalade is None:
        raise ValueError("effort %r refuse sans escalade verifiee (%s)" % (effort, "|".join(ESCALADES)))
    modele, effort_table = TABLE[surface][t]
    drap = DRAPEAUX_LUS[surface]
    inconnu = None
    if drap["drapeau"] is None:
        if escalade is not None:
            raise ValueError("escalade impossible sur %s : drapeau d'effort UNKNOWN" % surface)
        inconnu = "UNKNOWN : drapeau d'effort absent/non lu pour %s (%s)" % (surface, drap["commande_aide"])
        _LOG.warning(inconnu)
        retenu = None
    elif escalade is not None:
        retenu = EFFORT_ESCALADE if EFFORT_ESCALADE in drap["niveaux_aide"] else effort_table
    else:
        retenu = effort if effort is not None else effort_table
        if retenu is not None and retenu not in drap["niveaux_aide"]:
            raise ValueError("effort %r absent de l'aide de %s" % (retenu, surface))
    if modele:
        import forge_task_executor
        motif = forge_task_executor._modele_hors_quota(FOURNISSEUR[surface], modele, census)
        if motif:
            raise ModeleHorsQuota(motif)
    retenu, motif_borne = borner_effort(surface, modele, retenu)
    if motif_borne:
        _LOG.info(motif_borne)
    res = {"surface": surface, "taille": t, "modele": modele, "effort": retenu,
           "drapeau_effort": drap["drapeau"], "inconnu": inconnu}
    if motif_borne:
        res["motif_borne"] = motif_borne
    return res
