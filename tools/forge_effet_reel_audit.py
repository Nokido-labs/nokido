#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_effet_reel_audit.py - l'ecart entre un mecanisme et son EFFET.

Mandat owner 2026-09-16 : « verifier que chaque mecanisme qui existe, se relit
comme actif, et a un effet reel ». L'audit de phase 1 a etabli que SIX familles
sont deja instrumentees -- `forge_reachability_ledger` (ORPHELIN), 
`forge_capability_contracts` (TRANSPORT/APPLICATIF/CAPACITE),
`forge_capability_execution_trace` (GHOST..CRED_INVALID),
`forge_body_regulation_audit` (ZONE_MORTE), `forge_regulation_efficacy` (POMPE),
`vitalite_gardes` (anergie) -- et que QUATRE ne l'etaient pas. Ce sont exactement
celles qui ont RECIDIVE. Ce module ne refait aucune des six ; il ajoute les quatre.

  A. GARDE SANS EMETTEUR. Un signal LU que personne n'ECRIT. Et sa forme sournoise :
     l'emetteur MINORITAIRE. `llama.wanted` etait pose par 1 reveilleur sur 6 ->
     73 arrets de l'inference locale, 312,94 Go recharges en 7,6 jours, pendant que
     `docker.wanted` (pose partout) protegeait Docker. Un detecteur binaire
     present/absent rate ce cas : c'est le RATIO qui parle.
  B. INTERRUPTEUR OUBLIE. `disabled = true` dont la raison n'est ecrite nulle part.
     Paye le jour meme : le commit 43b769366 s'intitule « pilier local reouvert »,
     a borne les args -- donc traite LA CAUSE de l'ecartement -- et n'a jamais
     touche la ligne `disabled`. Dix jours d'embedding local eteint pendant que
     l'historique disait « rouvert ».
  C. ARTEFACT DEVANT PREEXISTER, non versionne. Le gate `anatomie` vert 3x en local
     et rouge des son premier passage sur le runner, parce qu'il lisait
     `module_cards.json` que le depot ne porte pas. Meme forme pour les rapports
     `pip_audit_*.json` ecrits sous `sandbox/`, que `.gitignore` ecarte, donc
     invisibles du worktree DETACHE qui doit les juger.
  D. POLITIQUE A N CHEMINS. Une politique lue par un seul des chemins qui la
     doivent. `embed()` respectait `pillar_policy.json` quand `embed_batch_fast`,
     le chemin REEL du drain, ne la lisait pas ; `.git-publish-rules.json` n'etait
     lu que par le push gouverne quand trois outils de publication l'ignoraient.

PRINCIPE DE CONCEPTION, et il vient de l'audit lui-meme : chaque detecteur est une
fonction PURE qui recoit des donnees et rend un verdict ; la COLLECTE est separee.
Un detecteur qui ne serait testable qu'en lisant le vrai depot ne serait pas
gardable -- c'est le defaut meme qu'on traque.

DEUX REGLES QUE CE MODULE S'APPLIQUE A LUI-MEME :
  - il n'est pas son propre sujet : sa source et son NR sont exclus de la collecte
    (un instrument qui lit son propre vocabulaire se signale lui-meme, paye 5 fois
    en trois jours dans ce depot) ;
  - il rend TOUJOURS le denominateur. « 25 interrupteurs muets » ne veut rien dire
    sans « sur 35 disabled, sur 91 services ».

Usage :
    run action=run_job script=tools/forge_effet_reel_audit.py
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : ecart entre mecanisme declare et effet reel"

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Sa propre source et son NR : sinon les EXEMPLES cites en docstring deviennent
# des constats. C'est la regle « un instrument ne lit jamais son propre
# vocabulaire », et elle a ete payee cinq fois en trois jours.
FICHIERS_EXCLUS = ("forge_effet_reel_audit.py", "test_effet_reel_audit_nr.py")

_DATE = re.compile(r"20\d\d[-/]\d\d[-/]\d\d")

# CARTE DES POLITIQUES -- elle se DECLARE, elle ne s'infere pas.
# Une politique ne gouverne que les chemins qui la LISENT ; savoir lesquels
# DEVRAIENT la lire est une connaissance de conception, qu'aucune analyse ne
# retrouve. Chaque entree est SOURCEE par l'incident qui l'a etablie.
CARTE_POLITIQUES = {
    # Les trois outils de publication ont ete alignes le 2026-09-15 (P0 du SSoT) :
    # avant cela, seul le push gouverne lisait le manifeste, et `forge_dist_publish`
    # assemblait par `git archive` export-ignore SEUL -- donc tout `blocked_paths`
    # ne protegeait pas ce chemin. Le gate existe pour que ca ne se defasse pas.
    ".git-publish-rules.json": [
        "forge_git_egress.py", "forge_public_mirror.py", "forge_dist_publish.py",
        "launch_public_mirror.py", "forge_release_gate.py",
    ],
}

# CE QUE LA CARTE NE COUVRE PAS, et il faut le DIRE plutot que de le taire :
# la granularite est le FICHIER. Le defaut de `config/pillar_policy.json` etait
# INTRA-module -- `embed()` lisait la politique, `embed_batch_fast()` du meme
# fichier ne la lisait pas -- et aucune collecte par fichier ne peut le voir.
# Cette granularite-la demande une lecture AST par fonction : non couverte.
POLITIQUES_HORS_PORTEE = {
    "config/pillar_policy.json": "defaut INTRA-module (embed vs embed_batch_fast) : "
                                 "granularite fonction, non couverte par une "
                                 "collecte par fichier",
}


# ---------------------------------------------------------------------------
# A. GARDE SANS EMETTEUR
# ---------------------------------------------------------------------------

def signaux_sans_emetteur(lectures: dict, ecritures: dict,
                          ratio_alerte: float = 0.5) -> list:
    """Signaux LUS dont personne, ou trop peu de monde, n'est l'EMETTEUR.

    Deux motifs, et le second est celui qu'un detecteur naif rate :
      AUCUN_EMETTEUR  le signal est lu, aucun chemin ne l'ecrit. Le garde branche
                      dessus ne s'est jamais declenche et ne se declenchera pas.
      MINORITAIRE     le signal EST ecrit, mais par une minorite des chemins qui
                      le devraient (ratio ecrivains/lecteurs sous le seuil). C'est
                      la forme de `llama.wanted` : un declarant sur six, garde
                      correct, journal accablant.

    Un signal ni lu ni ecrit n'est pas un defaut : il n'est pas invente ici.
    """
    out = []
    for signal, lecteurs in sorted(lectures.items()):
        if not lecteurs:
            continue
        ecrivains = list(ecritures.get(signal) or [])
        if not ecrivains:
            out.append({"signal": signal, "motif": "AUCUN_EMETTEUR",
                        "lecteurs": list(lecteurs), "emetteurs": []})
            continue
        if len(ecrivains) / float(len(lecteurs)) < ratio_alerte:
            out.append({"signal": signal, "motif": "MINORITAIRE",
                        "lecteurs": list(lecteurs), "emetteurs": ecrivains,
                        "ratio": round(len(ecrivains) / float(len(lecteurs)), 2)})
    return out


# ---------------------------------------------------------------------------
# B. INTERRUPTEUR OUBLIE
# ---------------------------------------------------------------------------

def _blocs_service(texte: str) -> list:
    blocs, courant = [], None
    for ligne in texte.splitlines():
        if ligne.strip().startswith("[[service]]"):
            if courant is not None:
                blocs.append(courant)
            courant = []
        if courant is not None:
            courant.append(ligne)
    if courant is not None:
        blocs.append(courant)
    return blocs


def compter_services(texte: str) -> dict:
    """Le DENOMINATEUR. Une liste sans son total se lit comme une catastrophe."""
    blocs = _blocs_service(texte)
    off = sum(1 for b in blocs if any(re.match(r"\s*disabled\s*=\s*true", l) for l in b))
    return {"services": len(blocs), "actifs": len(blocs) - off, "disabled": off}


def interrupteurs_sans_motif(texte: str) -> list:
    """Services coupes dont la RAISON n'est ecrite nulle part dans leur bloc.

    Un commentaire sans DATE ne compte pas : « coupe parce que ca ne marchait
    pas » ne dit pas si la cause a ete traitee depuis. C'est precisement ce qui
    rend un interrupteur indecidable -- et ce qui a laisse `NokidoLlamaEmbed`
    ferme dix jours apres la reparation de sa cause.

    Ce detecteur ne dit PAS « ce service devrait tourner ». Il dit : depuis ce
    fichier, personne ne peut savoir si ce choix est encore valide.
    """
    out = []
    for bloc in _blocs_service(texte):
        nom, coupe = "?", False
        for l in bloc:
            m = re.match(r'\s*name\s*=\s*"([^"]+)"', l)
            if m:
                nom = m.group(1)
            if re.match(r"\s*disabled\s*=\s*true", l):
                coupe = True
        if not coupe:
            continue
        commentaires = [l for l in bloc if l.strip().startswith("#")]
        if not any(_DATE.search(c) for c in commentaires):
            out.append({"service": nom, "commentaires": len(commentaires),
                        "motif": "MUET" if not commentaires else "SANS_DATE"})
    return out


# ---------------------------------------------------------------------------
# C. ARTEFACT DEVANT PREEXISTER
# ---------------------------------------------------------------------------

def artefacts_a_preexister(sites: list, est_ignore) -> list:
    """Artefacts LUS par un module, ECRITS par aucun, et absents du versionnement.

    LA RESERVE QUI EVITE LES FAUX POSITIFS, et elle est massive : une SORTIE a le
    droit d'etre ignoree par git, puisque le run la produit. Sur six artefacts
    ignores examines le 2026-09-16, CINQ etaient des sorties -- les compter aurait
    fabrique cinq alertes fausses. On ne retient donc que ce que PERSONNE n'ecrit
    et que le depot ne porte pas : cet artefact doit preexister, et rien ne
    garantit qu'il existera dans un worktree detache.
    """
    par_artefact = {}
    for s in sites:
        e = par_artefact.setdefault(s["artefact"], {"ecrit": False, "lecteurs": []})
        if s.get("ecrit_ici"):
            e["ecrit"] = True
        else:
            e["lecteurs"].append(s.get("module", "?"))
    out = []
    for artefact, e in sorted(par_artefact.items()):
        if e["ecrit"] or not e["lecteurs"]:
            continue
        if est_ignore(artefact):
            out.append({"artefact": artefact, "lecteurs": e["lecteurs"],
                        "motif": "DOIT_PREEXISTER_NON_VERSIONNE"})
    return out


# ---------------------------------------------------------------------------
# D. POLITIQUE A N CHEMINS
# ---------------------------------------------------------------------------

def politiques_a_lecteur_unique(lecteurs: dict, chemins_du_domaine: dict) -> list:
    """Politiques que TOUS leurs chemins ne lisent pas.

    Quand une politique gouverne une capacite, elle gouverne TOUS ses chemins.
    Sinon le chemin qui ne la lit pas devient une porte derobee silencieuse --
    mesure : `embed_batch_fast`, le chemin REEL du drain, ignorait
    `pillar_policy.json` et tentait des backends payants que la politique
    excluait.

    INDETERMINE n'est pas SAIN : ne pas savoir quels chemins devraient lire une
    politique ne prouve pas qu'ils la lisent tous. UNKNOWN n'est ni NO ni YES.
    """
    out = []
    for politique, lus in sorted(lecteurs.items()):
        attendus = chemins_du_domaine.get(politique)
        if attendus is None:
            out.append({"politique": politique, "motif": "INDETERMINE",
                        "lecteurs": list(lus), "chemins_sans_lecture": None})
            continue
        manquants = [c for c in attendus if c not in lus]
        if manquants:
            out.append({"politique": politique, "motif": "LECTURE_PARTIELLE",
                        "lecteurs": list(lus), "chemins_sans_lecture": manquants})
    return out


# ---------------------------------------------------------------------------
# COLLECTE (separee des detecteurs : elle touche le disque et git)
# ---------------------------------------------------------------------------

def _sources(dossiers=("tools", "app")) -> list:
    """(nom, texte) des modules, en DISANT ce qui a ete ecarte et pourquoi."""
    out, illisibles = [], []
    for d in dossiers:
        for f in sorted((ROOT / d).glob("forge_*.py")):
            if f.name in FICHIERS_EXCLUS:
                continue
            try:
                out.append((f.name, f.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                illisibles.append(f.name)
    return out, illisibles


def famille_A_deleguee() -> dict:
    """La famille A est DEJA instrumentee : on delegue, on ne re-derive pas.

    ERREUR MESUREE LE 2026-09-16, et elle est de ma main. J'ai declare cette
    famille « sans instrument » apres une recherche par NOM qui couvrait
    `reachab`, `capability`, `regulation`, `vitalite` -- et jamais `signal` ni
    `intention`. Or le depot porte :

      app/forge_signal_coupling.py    signaux d'intention, avec une `policy`
                                      fail_closed / fail_open par signal, parce
                                      que le remede d'un orphelin DEPEND du sens :
                                      neutraliser `llama.wanted` aurait SUPPRIME
                                      la protection au lieu d'ajouter l'emetteur.
      app/forge_endocrine.orphans()   l'autre moitie : hormone sans recepteur.
      tools/forge_audit_intention_effet.py  intention x effet x cout, par unite
                                      VIVANTE, cout mesure en `private` et non en
                                      `rss` (qdrant : 4,48 Go de rss pour 0,14 Go
                                      engages -- imputer sur le rss designe des
                                      coupables innocents).

    ET SA METHODE REFUTE LA MIENNE. `forge_signal_coupling` etablit noir sur blanc
    que l'analyse STATIQUE ne suffit pas ici : un grep sur `llama.wanted` a rendu
    14 lectures et 0 ecriture, et c'etait FAUX -- l'ecriture passait par
    `CIBLES[cible]["drapeau"]`, invisible au litteral. Un emetteur se CONSTATE a
    l'execution. Ma premiere passe l'a reprouve en direct : elle a annonce
    `docker.wanted : AUCUN_EMETTEUR` alors que `forge_docker_agent.ensure_daemon`
    le pose (WANT_FLAG, ligne 47), et `snn.wanted` alors que le commit 2b4445855
    l'emet. Dix signaux annonces, au moins deux faux a la premiere lecture.

    La fonction pure `signaux_sans_emetteur` est CONSERVEE : sa logique -- dont le
    motif MINORITAIRE, qu'un detecteur binaire rate -- est juste et testee. Ce qui
    est retire, c'est la COLLECTE par regex, qui etait fausse. Qu'un organe fournisse
    des lectures/ecritures CONSTATEES, et elle redevient utile.
    """
    return {"famille": "A", "motif": "DEJA_INSTRUMENTE",
            "delegue_a": ["app/forge_signal_coupling.py",
                          "app/forge_endocrine.orphans()",
                          "tools/forge_audit_intention_effet.py"],
            "reserve": "collecte statique retiree : un emetteur se constate a "
                       "l'execution, pas au litteral (CIBLES[x]['drapeau'])"}


# Etats RUNTIME : un service les cree en tournant. Les compter comme « devant
# preexister » est un faux positif, et la premiere passe en a produit 28 d'un coup
# (a2a.log, git_proxy.log, *.heartbeat, llama.wanted...). Un artefact d'ETAT n'est
# pas un artefact de PREUVE.
_SUFFIXES_RUNTIME = (".log", ".heartbeat", ".wanted", ".pid", ".lock", ".trigger")


def collecte_artefacts(sources) -> list:
    """Sites de lecture/ecriture d'artefacts de PREUVE sous `sandbox/`.

    DEUX CALIBRAGES, tous deux imposes par la premiere passe reelle :
      1. les etats runtime sont ecartes (voir `_SUFFIXES_RUNTIME`) : le service
         qui les lit est celui qui les ecrit, en tournant ;
      2. `ecrit_ici` est teste PRES DU NOM de l'artefact et non n'importe ou dans
         le module. La premiere version cherchait `write_text` dans TOUT le
         fichier : un module qui ecrit un fichier quelconque etait declare
         producteur de tous ceux qu'il cite.
    """
    sites = []
    r = re.compile(r'["\']((?:sandbox|workspace)[/\\][A-Za-z0-9_./\\-]+\.(?:json|jsonl|xml))["\']')
    for nom, src in sources:
        for a in set(r.findall(src)):
            a_norm = a.replace("\\", "/")
            if a_norm.endswith(_SUFFIXES_RUNTIME):
                continue
            base = a_norm.rsplit("/", 1)[-1]
            # Fenetre autour de CHAQUE mention : l'ecriture doit concerner CET
            # artefact, pas un autre du meme module.
            ecrit = False
            for m in re.finditer(re.escape(base), src):
                zone = src[max(0, m.start() - 200): m.end() + 200]
                if re.search(r"(write_text|json\.dump|\.dump\(|open\s*\([^)]{0,60}['\"]w)", zone):
                    ecrit = True
                    break
            sites.append({"artefact": a_norm, "module": nom, "ecrit_ici": ecrit})
    return sites


def collecte_lecteurs_politiques(sources) -> dict:
    """Quels modules CITENT chaque politique de la carte.

    Citer n'est pas lire -- un module peut nommer un fichier de politique dans un
    commentaire. C'est donc un detecteur d'ALERTE : un chemin qui ne cite meme pas
    la politique ne la lit certainement pas ; l'inverse n'est pas garanti.
    """
    lect = {p: [] for p in CARTE_POLITIQUES}
    for nom, src in sources:
        for politique in CARTE_POLITIQUES:
            base = politique.rsplit("/", 1)[-1]
            if base in src:
                lect[politique].append(nom)
    return lect


def _ignore_par_git(chemins) -> dict:
    """git check-ignore en UN appel. Un echec rend INDETERMINE, jamais 'suivi'."""
    if not chemins:
        return {}
    try:
        p = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                            "check-ignore", *chemins],
                           capture_output=True, text=True, errors="replace",
                           timeout=60)
    except Exception:  # noqa: BLE001
        return {c: None for c in chemins}
    ignores = {l.strip().replace("\\", "/") for l in p.stdout.splitlines() if l.strip()}
    return {c: (c in ignores) for c in chemins}


def rapport() -> dict:
    sources, illisibles = _sources()
    toml = (ROOT / "proxy_deno" / "core" / "services.toml")
    texte_toml = toml.read_text(encoding="utf-8", errors="replace") if toml.exists() else ""

    sites = collecte_artefacts(sources)
    etat = _ignore_par_git(sorted({s["artefact"] for s in sites}))
    # Un chemin dont git n'a rien dit est INDETERMINE : on ne le compte pas comme
    # versionne (ce serait ranger l'inconnu du cote sain).
    return {
        "denominateurs": {
            "modules_lus": len(sources), "modules_illisibles": illisibles,
            "services": compter_services(texte_toml),
            "artefacts_vus": len(etat),
        },
        "A_signaux_sans_emetteur": famille_A_deleguee(),
        "B_interrupteurs_sans_motif": interrupteurs_sans_motif(texte_toml),
        "C_artefacts_a_preexister": artefacts_a_preexister(
            sites, lambda p: etat.get(p) is True),
        # D : COLLECTE, avec sa portee DITE. Ce qui est hors portee reste nomme
        # (`POLITIQUES_HORS_PORTEE`) : une famille partiellement couverte qui se
        # tairait sur le reste rendrait un vert pour ce qu'elle n'a pas regarde.
        "D_politiques": {
            "famille": "D",
            "ecarts": politiques_a_lecteur_unique(
                collecte_lecteurs_politiques(sources), CARTE_POLITIQUES),
            "hors_portee": POLITIQUES_HORS_PORTEE,
            "reserve": "citer n'est pas lire : detecteur d'alerte, pas de preuve",
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ecart entre mecanisme declare et effet reel.")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = rapport()
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    d = r["denominateurs"]
    print("[effet-reel] %d modules lus (%d illisibles) | services %s"
          % (d["modules_lus"], len(d["modules_illisibles"]), d["services"]))
    a = r["A_signaux_sans_emetteur"]
    print("\nA signaux sans emetteur : %s -> %s"
          % (a.get("motif"), ", ".join(a.get("delegue_a") or [])))
    print("    %s" % a.get("reserve", ""))
    d = r["D_politiques"]
    print("\nD politiques a lecture partielle : %d ecart(s) | hors portee : %d"
          % (len(d.get("ecarts") or []), len(d.get("hors_portee") or {})))
    for e in (d.get("ecarts") or [])[:8]:
        print("   ", json.dumps(e, ensure_ascii=False)[:190])
    for pol, motif in (d.get("hors_portee") or {}).items():
        print("    HORS PORTEE %s : %s" % (pol, motif))
    for cle, titre in (("B_interrupteurs_sans_motif", "B interrupteurs sans motif date"),
                       ("C_artefacts_a_preexister", "C artefacts devant preexister")):
        items = r[cle]
        print("\n%s : %d" % (titre, len(items)))
        for it in items[:15]:
            print("   ", json.dumps(it, ensure_ascii=False)[:190])
        if len(items) > 15:
            print("    ... %d de plus (borne d'affichage, pas de mesure)" % (len(items) - 15))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
