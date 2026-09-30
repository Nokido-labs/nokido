"""Garde PreToolUse : interroger la MEMOIRE avant d'instrumenter un domaine neuf.

Trou de couverture mesure le 24-07. `forge_recon_breaker` force la delegation sur
`read`/`search` ; `RULES_SHARED` le dit lui-meme : « pour run/query/ask la DISCIPLINE
est le seul filet ». Or une campagne NPU entiere est passee par `run` et
`trusted_script` : 14 mesures, 4 scripts, plusieurs dizaines de milliers de tokens —
quand `rag_fts` sur « NPU VitisAI » rendait la reponse au premier appel (note du
2026-05-02 : env `ryzen-ai-1.7.0`, 567 eps, 12.5 s de compilation).

Une regle qui repose sur la vigilance echoue exactement quand l'agent est absorbe
par un diagnostic — c'est-a-dire toujours. Ce hook la rend structurelle.

Contrat : UN seul blocage par domaine et par jour. Ce n'est pas un garde qui
harcele, c'est un garde qui force le PREMIER reflexe. Toute consultation memoire
(`rag`, `query`, `read_function_body`, un `Grep` sur les memoires) marque le domaine
comme interroge et le hook se tait ensuite.

Entree/sortie : protocole hook Claude Code (JSON sur stdin, exit 2 = deny).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parents[1]
ETAT = ROOT / "sandbox" / "recon_first_state.json"
TTL_S = 86400  # une journee : un domaine re-interroge chaque jour, pas a chaque tour
# FRAICHEUR EXIGEE POUR UNE CREATION (mesure owner 2026-09-13). `__memoire__` est
# un drapeau GLOBAL : il dit « cet agent a consulte quelque chose », pas « il a
# consulte CE sujet ». Avec le TTL de 24 h, une consultation faite la veille sur
# un tout autre domaine desarmait le garde pour la journee entiere. Mesure du
# jour : drapeau pose il y a 13,1 h, dix scripts d'instrument crees, dont trois
# refaisant un outil existant, et le garde n'a pas mordu une seule fois.
# Une heure : assez pour ne pas re-consulter a chaque fichier d'une meme tache,
# trop peu pour qu'une consultation d'hier vaille autorisation aujourd'hui.
TTL_CONSULTATION_CREATION_S = 3600

# Domaines a fort historique — ceux ou repartir de zero coute cher. Volontairement
# COURT : un garde qui couvre tout est un garde qu'on desarme.
# `\b` traite « _ » comme un caractere de MOT : `\bnpu\b` ne matche donc PAS
# `forge_npu_bench.py` — or les noms de fichiers Nokido sont exactement ce qu'on
# passe a ce hook (mesure 24-07 : le domaine npu passait au travers, docker etait
# attrape). Frontiere explicite sur [a-z0-9] : « _ » et « . » separent.
_F = r"(?<![a-z0-9])%s(?![a-z0-9])"
DOMAINES = {
    "npu": (_F % "npu") + r"|vitisai|xdna|ryzen[-_]ai|xclbin|vaiml|aie2",
    "rag": (_F % "rag") + r"|embed|rerank|bge|qdrant|chunk",
    "docker": (_F % "docker") + r"|wsl|sawtooth|keeper",
    "agy": (_F % "agy") + r"|gemini|antigravity|postal",
    "eviction": r"evict|resource_manager|non_essential|homeostas",
    "hub": r"nokido_hub|mcp_registry|supervisor|ensure_service",
}

# Outils qui CONSOMMENT (instrumentent, mesurent, executent) vs qui CONSULTENT.
OUTILS_ACTION = ("__run", "__orchestrate", "__task", "__forge_spawn_swarm", "__auto_test")
OUTILS_MEMOIRE = ("__rag", "__query", "__read_function_body", "__read", "__biblio",
                  "__forge_deep_explore", "__skill")
# Outils qui CREENT un module. L'anti-dup de RULES_SHARED protege la creation, et
# c'est le motif le plus recidivant mesure par forge_recurrence_audit : re-consigne
# sur mai->juillet, alors que la regle existe depuis toujours. Une regle qu'on doit
# se rappeler echoue quand on est absorbe — donc on la cable, comme les domaines.
OUTILS_ECRITURE = ("__governed_edit", "Write")
CIBLE_MODULE = re.compile(r"(?:^|/)(?:app|tools)/forge_[a-z0-9_]+\.py$", re.I)


def _charger() -> dict:
    try:
        d = json.loads(ETAT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - etat absent ou corrompu = on repart propre
        return {}
    maintenant = time.time()
    return {k: v for k, v in d.items() if maintenant - v < TTL_S}


def _ecrire(d: dict) -> None:
    try:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        ETAT.write_text(json.dumps(d), encoding="utf-8")
    except OSError:  # muet-ok : un garde ne casse jamais sur son propre journal
        pass


# La PROSE n'instrumente rien. Mesure du 2026-09-14 : un `git commit` dont le
# message citait « GATE-KO /rag » a ete refuse au motif « domaine rag
# instrumente sans consultation ». Le commit ne mesurait aucun domaine — le mot
# vivait dans le message. Un garde qui crie a faux se fait desarmer, et sa
# precision compte donc autant que sa portee : on RETIRE les arguments de `-m`
# avant de chercher un domaine. Le risque symetrique (rater une instrumentation
# ecrite DANS un message de commit) n'existe pas : un message ne s'execute pas.
_ARG_MESSAGE = re.compile(r"""-m\s+(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")


def _sans_prose(texte: str) -> str:
    """Retire le contenu des `-m "..."` : ce sont des mots, pas des mesures."""
    return _ARG_MESSAGE.sub(" -m <message> ", texte or "")


def _domaines(texte: str) -> set[str]:
    t = _sans_prose(texte or "").lower()
    return {nom for nom, motif in DOMAINES.items() if re.search(motif, t)}


def _pieges_anterieurs(ev: dict, charge: str, vus: dict) -> int:
    """Rend 2 (deny) si la charge touche un symptome deja explore AILLEURS.

    Fail-open par construction : index absent, trop gros ou illisible => 0. Un
    garde de memoire ne doit jamais empecher d'agir, seulement rappeler.
    """
    try:
        sys.path.insert(0, str(ROOT))
        # anti-dup : on reutilise l'outil, y compris son CHARGEMENT. `charger_index`
        # fait l'union index local + memoire partagee (`docs/enquetes_partagees.jsonl`).
        # Ce hook lisait le fichier local par un chemin en dur : chez un
        # contributeur du dist, ou ce fichier n'existe pas, il serait reste
        # AVEUGLE alors que la memoire partagee, elle, est livree. Trois lecteurs
        # existaient, un seul branchement aurait reproduit le motif « deux chemins
        # pour une capacite, un seul lit la politique ».
        from nokido_agent.tools.forge_symptom_index import JETON_RES, charger_index, demander

        idx = charger_index()
        if not idx.get("sessions"):
            return 0
    except Exception as e:  # noqa: BLE001
        print(f"[recon_first] index d'enquetes ignore: {type(e).__name__}",
              file=sys.stderr)
        return 0

    ici = str(ev.get("session_id") or "")[:8]
    # Ne balayer que le TEXTE LIBRE. Les valeurs STRUCTURELLES (action, chemin, nom de
    # service) sont des noms propres d'appel, pas des symptomes : le garde a mordu sur
    # `run_job` puis `proxy_deno` puis `laforge_py314`, un tour perdu chaque fois. Un
    # symptome se decrit dans du code, une requete ou un message — jamais dans le nom
    # de l'action qu'on invoque.
    _STRUCTURELS = {"action", "script", "path", "file_path", "timeout", "limit",
                    "agent", "to", "service", "desired_state", "offset", "lines",
                    "domain", "pattern", "glob", "output_mode", "name", "id"}
    _entree = ev.get("tool_input") or {}
    if isinstance(_entree, dict):
        charge = json.dumps(
            {k: v for k, v in _entree.items() if k not in _STRUCTURELS},
            ensure_ascii=False,
        )
    # Les CHEMINS ne sont pas des symptomes. Mesure 2026-07-30 : le garde a mordu
    # sur `laforge_py314`, nom de l'environnement present dans le chemin de
    # l'interpreteur — donc sur n'importe quelle commande. Un garde qui crie a faux
    # se fait desarmer, ce qui est pire que pas de garde.
    sans_chemins = re.sub(r"[A-Za-z]:[\\/][^\s\"']+|[\w.-]*[\\/][\w.\\/-]+", " ", charge)
    jetons: list[str] = []
    for rx in JETON_RES:
        for brut in rx.findall(sans_chemins):
            j = (brut if isinstance(brut, str) else brut[0]).lower()
            if len(j) >= 6 and j not in jetons:
                jetons.append(j)
    for j in jetons[:40]:
        cle = "symptome:" + j
        if cle in vus:
            continue
        # Un jeton qui NOMME un artefact du depot (dossier, module) est un nom
        # propre, pas un symptome. Mesure 2026-07-30 : le garde a mordu sur
        # `proxy_deno` puis `laforge_py314`, coutant un tour chacun. Le critere est
        # mecanique — le disque tranche, pas une liste de mots a maintenir.
        if (ROOT / j).exists() or (ROOT / "app" / f"{j}.py").exists() \
                or (ROOT / "tools" / f"{j}.py").exists():
            continue
        # EXIGER des pieges SUR LE SUJET : une correspondance de session sans
        # paragraphe pertinent n'apprend rien et ne justifie pas d'interrompre.
        trouves = [
            t for t in demander(j, idx, limite=3)
            if t["session"] != ici and t["n_pieges"] > 0
            and t.get("pieges_sur_le_sujet")
        ]
        if not trouves:
            continue
        vus[cle] = time.time()  # marquer AVANT de refuser : un seul rappel
        _ecrire(vus)
        lignes = [
            f"[recon_first] STOP — « {j} » a DEJA ete explore, et ca s'est mal passe.",
        ]
        for t in trouves[:2]:
            lignes.append(f"  {t['date']} session {t['session']} :")
            for p in t["pieges"][:2]:
                lignes.append(f"    — {p['extrait'][:170]}")
        lignes.append("  Lis ces pieges AVANT de rouvrir l'enquete. Un seul rappel :")
        lignes.append("  relance ton appel. Detail complet :")
        lignes.append(f"    run action=shell code=\"tools\\\\forge_symptom_index.py "
                      f"--ask {j}\"")
        print("\n".join(lignes), file=sys.stderr)
        return 2
    return 0


_MODULE_NOMME = re.compile(r"\b((?:forge|hook)_[a-z0-9_]+\.py)\b")


def _historique_module(charge: str) -> str:
    """Les 3 derniers commits des modules nommes dans la charge, WIP/UNTESTED en tete.

    Mesure les 01-02/08 : un pivot tague UNTESTED avait casse searxng ; une session
    entiere est passee sur l'effet de bord (portproxy, mirrored, firewall, reboot) sans
    jamais regarder ce que ce commit avait REMPLACE — la version d'avant marchait, et
    elle etait deja en git. L'index des symptomes rend les enquetes passees ; il ne dit
    pas « ce fichier a change recemment, et son auteur l'annoncait non teste ».

    Appele UNIQUEMENT dans les branches de refus : cout nul en regime normal. Rend une
    chaine vide si git est injoignable — on ne fabrique pas un silence rassurant, le
    message principal reste affiche.
    """
    modules = sorted(set(_MODULE_NOMME.findall(charge)))[:3]
    if not modules:
        return ""
    blocs = []
    for mod in modules:
        try:
            r = subprocess.run(
                ["git", "-c", "safe.directory=*", "-C", str(ROOT), "--no-pager",
                 "log", "-3", "--oneline", "--", f"*{mod}"],
                capture_output=True, text=True, errors="replace", timeout=5,
            )
        except Exception as exc:  # noqa: BLE001
            blocs.append(f"  {mod} : historique ILLISIBLE ({type(exc).__name__})")
            continue
        lignes = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
        if not lignes:
            continue
        rendu = []
        for ln in lignes:
            drapeau = "  <-- ANNONCE NON TESTE" if re.search(r"wip|untested", ln, re.I) else ""
            rendu.append(f"    {ln}{drapeau}")
        blocs.append(f"  {mod} :\n" + "\n".join(rendu))
    if not blocs:
        return ""
    return ("\n  --- ce qui a CHANGE recemment (regarder AVANT de traiter le symptome) ---\n"
            + "\n".join(blocs)
            + "\n  Un composant qui marchait avant : `git log` + diff du commit suspect"
              " AVANT toute nouvelle construction.\n")


def main() -> int:
    try:
        ev = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - entree illisible : ne jamais bloquer a l'aveugle
        return 0

    outil = str(ev.get("tool_name") or "")
    charge = json.dumps(ev.get("tool_input") or {}, ensure_ascii=False)
    vus = _charger()

    # Consultation memoire -> le domaine est marque, le garde se taira. On marque
    # aussi le fait BRUT d'avoir consulte : c'est ce que le garde de creation exige.
    if any(m in outil for m in OUTILS_MEMOIRE):
        vus["__memoire__"] = time.time()
        for d in _domaines(charge):
            vus[d] = time.time()
        _ecrire(vus)
        return 0

    # Symptome DEJA EXPLORE dans une session anterieure -> STOP, avec les pieges.
    # Mesure 2026-07-30 : le 26-07 une enquete sur `never_read` s'etait conclue par
    # « j'avais tort, mon never_read partout venait de 4 echantillons dont aucun ne
    # POUVAIT etre lu » ; le 29-07 la meme enquete a ete refaite de zero, 3
    # hypotheses fausses, 4 redemarrages, une journee. L'index existe desormais
    # (forge_symptom_index) ; ce garde le CONSULTE a ma place, puisque l'experience
    # montre que je ne le fais pas spontanement.
    if any(a in outil for a in OUTILS_ACTION):
        rc = _pieges_anterieurs(ev, charge, vus)
        if rc:
            return rc

    # Creation d'un module forge_* SANS aucune consultation prealable -> STOP.
    # Ne mord QUE sur une creation (fichier absent) : editer un module existant
    # n'est pas concerne, sinon le garde devient un peage et on le desarme.
    if any(w in outil for w in OUTILS_ECRITURE):
        entree = ev.get("tool_input") or {}
        chemin = str(entree.get("path") or entree.get("file_path") or "").replace("\\", "/")
        # ZONE D'OMBRE FERMEE (owner 2026-09-13 : « plus de zone d'ombre »).
        # Le garde ne mordait que sur la creation d'un `forge_*.py` DU DEPOT. Or
        # la reinvention ne passe pas par la : elle passe par des scripts
        # d'INSTRUMENT ecrits hors depot. Mesure du 2026-09-13 : dix scripts
        # crees dans C:/tmp en une session, dont TROIS refaisaient un outil
        # existant -- `forge_ci_profil` (profil de la suite pure, ecrit sur
        # demande owner le 04/09), `forge_service_rss_watch` (capteur de derive
        # memoire) et le profilage scalene (recette + harnais du 20/08, qui
        # disait DEJA que scalene n'atteint pas la memoire native sous Windows).
        # Aucun n'a declenche ce garde : aucun n'etait un `forge_*.py` du depot.
        # Mesure du corps qui justifie l'elargissement : 2 886 editions depuis le
        # 2026-08-31, 381 avec consultation prealable -- 13,2 %.
        est_module_depot = bool(chemin and CIBLE_MODULE.search(chemin))
        est_script_neuf = bool(chemin and chemin.endswith(".py"))
        if est_module_depot or est_script_neuf:
            existe = (ROOT / chemin).exists() or Path(chemin).exists()
            cle = "creation:" + chemin.rsplit("/", 1)[-1]
            # On juge la FRAICHEUR, pas la simple presence : voir
            # TTL_CONSULTATION_CREATION_S. Un drapeau vieux de 13 h vaut absence.
            _age_consult = time.time() - float(vus.get("__memoire__") or 0)
            _consulte_frais = _age_consult < TTL_CONSULTATION_CREATION_S
            if not existe and not _consulte_frais and cle not in vus:
                vus[cle] = time.time()  # marquer AVANT de refuser : un seul blocage
                _ecrire(vus)
                module = chemin.rsplit("/", 1)[-1]
                _quoi = "module" if est_module_depot else "script d'instrument"
                print(
                    f"[recon_first] STOP — creation du {_quoi} « {module} » sans"
                    f" avoir rien consulte.\n"
                    f"  `introspect question=\"<le probleme>\"` rend en UN appel les"
                    f" procedures deja appliquees,\n"
                    f"  les enquetes anterieures et leurs pieges. Et"
                    f" `tools/forge_retrieval_sweep.py <terme>` balaie les 8\n"
                    f"  surfaces, dont les OUTILS par leur nom — c'est ce que"
                    f" chercher le seul CONTENU rate.\n"
                    f"  Motif le plus RECIDIVANT mesure (re-consigne de mai a juillet,"
                    f" jamais eteint) :\n"
                    f"  recoder une primitive qui existait deja. Les 3 etapes de"
                    f" RULES_SHARED :\n"
                    f"    1. query sql=\"SELECT source, substr(text,1,300) FROM rag_fts"
                    f" WHERE rag_fts MATCH '<domaine>' LIMIT 8\"\n"
                    f"    2. lire les [[liens]] des memoires du domaine\n"
                    f"    3. lire le module Nokido qui couvre deja le domaine\n"
                    f"  Un seul blocage : relance apres avoir consulte (ou tout de"
                    f" suite si rien n'existe)."
                    + _historique_module(charge),
                    file=sys.stderr,
                )
                return 2  # deny
        return 0

    if not any(a in outil for a in OUTILS_ACTION):
        return 0

    neufs = sorted(_domaines(charge) - set(vus))
    if not neufs:
        return 0

    # Marquer AVANT de refuser : un seul blocage, jamais deux sur le meme domaine.
    for d in neufs:
        vus[d] = time.time()
    _ecrire(vus)

    d = neufs[0]
    print(
        f"[recon_first] STOP — domaine « {d} » instrumente sans consultation memoire.\n"
        f"  Nokido garde une trace de ce domaine. La chercher AVANT de mesurer :\n"
        f"    query   sql=\"SELECT source, substr(text,1,300) FROM rag_fts "
        f"WHERE rag_fts MATCH '{d} AND (solution OR bench OR fix)' LIMIT 8\"\n"
        f"  Mesure 24-07 : 14 mesures NPU et 4 scripts pour retrouver ce qu'une\n"
        f"  requete rendait — la note du 2026-05-02 disait deja quel environnement\n"
        f"  fonctionnait. Ce blocage ne se repete pas : relance ton appel apres avoir\n"
        f"  regarde (ou immediatement si la trace n'existe pas)."
        + _historique_module(charge),
        file=sys.stderr,
    )
    return 2  # deny


if __name__ == "__main__":
    sys.exit(main())
