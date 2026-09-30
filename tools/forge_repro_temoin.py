# -*- coding: utf-8 -*-
"""P4_REPRO_WITNESS — ce qu'un inconnu obtient vraiment en clonant ce depot.

    installe   !=   demarre   !=   sain   !=   MCP fonctionnel

Quatre etages, quatre confusions deja payees dans ce corps :
  - des fichiers presents ne disent rien de l'execution ;
  - un process vivant peut etre bloque -- un CPU a 0 % n'est pas une preuve, un
    travail I/O-bound y ressemble (paye le 2026-09-01, un job tue alors qu'il
    travaillait) ;
  - un port en LISTEN ne prouve pas le service rendu (`TRANSPORT != APPLICATIF`) ;
  - un registre n'est pas une mesure : `list_providers` annoncait « grade A,
    ttft 3,1 ms » sur un service mort.

L'INVARIANT QUI PORTE TOUT : un etage NON ATTEINT n'est pas un etage EN ECHEC.
Si l'installation echoue, le MCP n'est pas casse -- il est INCONNU. La confusion
inverse enverrait chercher une panne dans un composant que personne n'a essaye.
C'est `UNKNOWN != NO` applique a une chaine d'etages.

Ce module est ECRIT AVANT la reproduction qu'il mesure. Un temoin redige apres coup
se decouvre illisible pendant le run qu'il devait eclairer -- paye le 2026-09-09
(run 34381575702 : specification detaillee pour un job structurellement `skipped`).
"""

__FORGE_COLOR__ = "qualite/gate : temoin de reproduction externe (Public Alpha)"

# ANTI-CLONE : `_tri` vit deja dans le temoin UI et fait exactement ce qu'il faut
# (None reste None). Le recopier aurait cree un groupe de clones -- le cliquet en a
# NOMME un le 2026-09-09, sur deux noteurs qui ne differaient que par leurs champs.
# --- amorce namespace (point d'entree) : la RACINE avant tout import nokido_agent,
# sinon ModuleNotFoundError quand ce fichier est lance par son chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
from nokido_agent.tools.forge_ui_temoin import _tri  # noqa: F401


import re

# Modes d'installation qui demontrent un acces PUBLIC ANONYME. `git_vcs_authenticated`
# n'y figure pas : reproduire un depot PRIVE avec un jeton prouve le packaging, pas la
# promesse faite au lecteur du README. Confondre les deux serait annoncer une
# reproductibilite qu'on n'a pas mesuree.
_MODES_PUBLICS = {"git_vcs", "pypi", "sdist", "wheel"}

# Taxonomie des echecs d'installation. `pip failed` recouvre six causes qui ne se
# traitent pas pareil -- meme defaut qu'« interface injoignable », qui en agregeait
# trois. L'ordre compte : les motifs les plus SPECIFIQUES d'abord, un timeout reseau
# pouvant par ailleurs produire un « could not find a version ».
_FAMILLES = (
    ("NETWORK", r"name resolution|temporarily unavailable|timed out|timeout|"
                r"connection (refused|reset|aborted)|winerror 100\d\d|"
                r"failed to establish a new connection|max retries exceeded"),
    ("UNSUPPORTED", r"requires a different python|no matching distribution found for "
                    r"[^\s]+ *$|not supported on this platform|unsupported platform|"
                    r"requires-python"),
    ("BUILD", r"failed building wheel|error: microsoft visual c\+\+|"
              r"command 'gcc' failed|command 'cl\.exe' failed|"
              r"metadata-generation-failed|error: legacy-install-failure"),
    ("DEPENDENCY", r"could not find a version|no matching distribution|"
                   r"conflicting dependencies|resolutionimpossible|"
                   r"cannot install .* because these package versions"),
    ("ENVIRONMENT", r"permission denied|access is denied|acces refuse|errno 13|"
                    r"no such file or directory|winerror 5\b|disk quota|no space left"),
)

# Redaction. Une URL VCS authentifiee porte le jeton, et pip la REIMPRIME dans ses
# messages d'erreur : rediger « apres coup » a deja ecrit le secret sur disque.
_MASQUES = (
    (r"https://[^/\s:@]+:[^/\s@]+@", "https://***@"),          # user:token@host
    (r"\bgh[pousr]_[A-Za-z0-9]{20,}", "***"),                  # jetons GitHub
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", "***"),
    (r"(?i)\b(token|api[_-]?key|password|secret)\s*[=:]\s*\S+", r"\1=***"),
    (r"(?i)([A-Za-z]:\\Users\\)[^\\\s\"']+", r"\1***"),        # profil Windows
    (r"(?i)(/(?:home|Users)/)[^/\s\"']+", r"\1***"),           # profil POSIX
)


def rediger(texte):
    """Masque ce qui est sensible SANS effacer ce qui est diagnostiquable.

    Un `stderr` illisible ne vaut pas mieux qu'un `stderr` absent : l'URL du depot,
    le nom du paquet et le message d'erreur doivent survivre a la redaction.
    """
    if not texte:
        return texte
    out = str(texte)
    for motif, remplacement in _MASQUES:
        out = re.sub(motif, remplacement, out)
    return out


def classer_echec_install(phase, message, exit_code=None):
    """UNSUPPORTED | BUILD | DEPENDENCY | NETWORK | ENVIRONMENT | BROKEN, ou None.

    LISTE BLANCHE : ce qu'on ne sait pas reconnaitre tombe sur BROKEN, jamais sur
    NETWORK. Ranger un inconnu du cote « transitoire » ferait conseiller de
    reessayer sur un paquet reellement casse -- c'est le corollaire habituel, un
    agregat ne range jamais l'inconnu du cote favorable.
    """
    if not phase and not message:
        return None
    bas = (message or "").lower()
    for famille, motif in _FAMILLES:
        if re.search(motif, bas):
            return famille
    return "BROKEN"


def _ok_install(install: dict):
    """True / False / None — None quand l'etape n'a pas ete tentee."""
    res = install.get("result")
    return None if res is None else (str(res).upper() == "OK")


def _ok_runtime(runtime: dict):
    """Demarre ET joignable. Un demarrage sans health ne conclut pas."""
    demarre = _tri(runtime.get("process_started"))
    joignable = _tri(runtime.get("health_reachable"))
    if demarre is False or joignable is False:
        return False
    if demarre is None or joignable is None:
        return None
    return True


def _ok_mcp(mcp: dict):
    """Se serrer la main n'est pas rendre un service.

    Un handshake reussi sans APPEL REEL laisse l'etage INCONNU, jamais vert : c'est
    la difference entre un registre et une mesure. Il faut qu'un outil ait ete
    appele ET qu'il ait rendu un resultat exploitable.
    """
    for cle in ("server_reachable", "handshake_ok", "tool_result_ok"):
        if _tri(mcp.get(cle)) is False:
            return False
    if not mcp.get("one_real_tool_call"):
        return None
    for cle in ("server_reachable", "handshake_ok", "tool_result_ok"):
        if _tri(mcp.get(cle)) is not True:
            return None
    return True


def construire(obs: dict) -> dict:
    """Observations -> P4_REPRO_WITNESS, avec son verdict et sa raison.

    Fonction PURE : ni fichier ni reseau, donc testable sur donnees synthetiques
    avant qu'une machine externe n'existe.
    """
    obs = obs or {}
    identity = dict(obs.get("identity") or {})
    env = dict(obs.get("environment") or {})
    install = dict(obs.get("install") or {})
    runtime = dict(obs.get("runtime") or {})
    mcp = dict(obs.get("mcp") or {})

    i_ok, r_ok, m_ok = _ok_install(install), _ok_runtime(runtime), _ok_mcp(mcp)
    sha = identity.get("tested_sha")
    mode = env.get("installation_mode")
    # REDACTION AVANT STOCKAGE : le flux brut ne quitte jamais cette fonction.
    stderr_redige = rediger(install.get("stderr"))
    famille = (classer_echec_install(install.get("phase"), install.get("stderr"),
                                     install.get("exit_code"))
               if i_ok is False else None)

    # UNE INSTALLATION RATEE REND LES ETAGES SUIVANTS INATTEIGNABLES, et le temoin
    # le FORCE au lieu de recopier ce qu'on lui donne. Un appelant qui remplirait
    # `runtime` ou `mcp` apres un echec d'install y mettrait forcement des valeurs
    # fausses -- au mieux celles d'un run precedent. Le contrat se protege lui-meme
    # plutot que de faire confiance a son appelant.
    if i_ok is False:
        r_ok = m_ok = None
        runtime = {k: None for k in runtime}
        mcp = {k: None for k in mcp}

    # ORDRE NON COMMUTATIF. Un echec MESURE se dit avant toute question d'identite :
    # savoir sur quel sha on a echoue est utile, mais l'echec, lui, est etabli.
    if False in (i_ok, r_ok, m_ok):
        etage = ("install" if i_ok is False
                 else "runtime" if r_ok is False else "MCP")
        verdict = "FAILED"
        raison = "echec mesure a l'etage %s ; les etages suivants restent INCONNUS" % etage
    elif not sha:
        verdict, raison = "UNKNOWN", (
            "sha NON RENSEIGNE : le temoin ne dit pas quel etat a ete reproduit")
    elif not mode:
        # `pip install nokido-agent` et `git clone` ne promettent pas la meme chose :
        # reproduire par clone ne prouve pas ce que lit celui qui tape `pip install`.
        verdict, raison = "UNKNOWN", (
            "mode d'installation NON RENSEIGNE : on ignore quelle promesse a ete "
            "reproduite (paquet publie ou clone du depot)")
    elif (i_ok, r_ok, m_ok) == (True, True, True):
        verdict, raison = "PROVEN", ""
    else:
        manquants = [n for n, v in (("install", i_ok), ("runtime", r_ok),
                                    ("MCP", m_ok)) if v is None]
        verdict, raison = "UNKNOWN", (
            "etage(s) non atteint(s) : %s — rien n'a echoue, on n'a pas regarde"
            % ", ".join(manquants))

    return {
        "identity": {"tested_sha": sha},
        "environment": {"os": env.get("os"), "python": env.get("python"),
                        "architecture": env.get("architecture"),
                        "installation_mode": mode,
                        # Dit par le temoin lui-meme, pas deduit du nom du mode par
                        # son lecteur : une reproduction authentifiee est PROUVEE
                        # dans son perimetre et ne demontre AUCUN acces public.
                        "public_access_demonstrated": (mode in _MODES_PUBLICS
                                                       if mode else None)},
        "install": {"started": install.get("started"),
                    "finished": install.get("finished"),
                    "result": install.get("result"),
                    "phase": install.get("phase"),
                    "exit_code": install.get("exit_code"),
                    "failure_class": famille,
                    "stderr_tail": stderr_redige},
        "runtime": {"process_started": _tri(runtime.get("process_started")),
                    "health_reachable": _tri(runtime.get("health_reachable")),
                    "health_result": runtime.get("health_result")},
        "mcp": {"server_reachable": _tri(mcp.get("server_reachable")),
                "handshake_ok": _tri(mcp.get("handshake_ok")),
                "one_real_tool_call": mcp.get("one_real_tool_call"),
                "tool_result_ok": _tri(mcp.get("tool_result_ok"))},
        "final": {"INSTALL_OK": i_ok, "RUNTIME_OK": r_ok, "MCP_OK": m_ok,
                  "verdict": verdict},
        "reason": raison,
    }
