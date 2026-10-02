# -*- coding: utf-8 -*-
"""forge_generation.py — le corps garde ses ETATS, pas seulement ses fichiers.

__FORGE_COLOR__ ci-dessous : ce module appartient a la memoire, pas a la qualite.
Il ne juge rien ; il INSCRIT ce qui a ete mesure et le rend restaurable.

POURQUOI CE MODULE EXISTE
=========================
Nokido sait deja fouiller son passe : `forge_archaeology` (fichiers supprimes),
`forge_constituent_archaeology` (fonctions, entrees de registre, non-.py),
`forge_capability_lineage` (apparu -> modifie -> disparu -> reapparu, avec commit
temoin), `forge_capability_recovery` (derniere version connue avant suppression).
Sept phases. Et pourtant la question la plus simple reste sans reponse :

    « quel etat COMPLET fonctionnait hier ? »

Parce que l'historique conserve des FICHIERS, pas des ETATS. Un commit ne dit ni
quels submodules etaient pointes, ni quels tests passaient, ni sous quel Python,
ni quelles capacites etaient vivantes. Retrouver « le Nokido qui marchait mardi »
demande donc de re-deduire tout cela a chaque fois — et c'est exactement le temps
qu'on reperd.

Une GENERATION repond en un seul objet : sha du depot, sha de chaque submodule,
interpreteur et paquets qui comptent, verdict des tests, capacites observees,
et QUI l'a produite.

CE QUE CE MODULE REFUSE DE FAIRE
================================
1. Il n'ecrit JAMAIS `STABLE` sur declaration. Sans preuve de tests, une capture
   est `CANDIDATE`. La lecon du jour meme : un juge qui note OPTIMAL une tache
   dont tous les providers ont echoue ne protege plus rien.
2. Il ne restaure RIEN tout seul. `plan_restauration()` rend les commandes et
   verifie que les sha existent ENCORE ; l'execution reste une decision humaine.
   Une restauration ecrase un working tree : c'est irreversible, donc ca se
   demande.
3. Il n'ecrase jamais une generation existante. Un etat valide est immuable —
   c'est toute la difference avec un fichier d'etat qu'on reecrit.
"""

from __future__ import annotations

__FORGE_COLOR__ = "memoire/generations"

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOSSIER = ROOT / "docs" / "generations"
# Depot de repli quand l'ACL refuse l'inscription (cf. `capturer`). Constante de
# MODULE, donc visible et patchable : un chemin enterre dans un `except` ne se
# trouve ni en lecture ni en test.
DOSSIER_ATTENTE = ROOT / "sandbox" / "generations_en_attente"

# MODE PREUVE : la generation nait HORS de l'arbre jetable (2026-09-11).
#
# Mesure, CI de reference complete : `GEN-00013.json` avait ete ecrit DANS le
# worktree de preuve. Or ce worktree est jetable par conception -- `remove_proof` le
# supprime. La preuve vivait donc a l'endroit exact qu'on detruit apres l'avoir
# produite, et une preuve qui ne survit pas a son propre contexte n'est pas une
# preuve, c'est une trace d'execution.
#
# `ROOT` derive de `__file__` : en mode reference il vaut le worktree, donc les DEUX
# destinations ci-dessus y tombaient, la cible comme le depot de repli. Quand le juge
# declare un PROOF_DIR, elles le suivent.
#
# Le passeur `tools/forge_generation_inscrire.py` (2026-09-09) prend `--depuis` : il
# remonte de ce depot vers l'arbre versionne, par un chemin GOUVERNE. Rien ici ne
# remplace cette inscription -- on deplace seulement la NAISSANCE de la preuve hors
# de ce qui sera detruit.
# La SEQUENCE appartient a l'etat PRODUIT (elle est versionnee), l'ARTEFACT au
# jugement. Les separer est ce qui permet de deplacer l'un sans emporter l'autre.
DOSSIER_SEQUENCE = DOSSIER

_PROOF_DIR = os.environ.get("NOKIDO_PROOF_DIR")
if _PROOF_DIR:
    DOSSIER = Path(_PROOF_DIR) / "generations"
    DOSSIER_ATTENTE = Path(_PROOF_DIR) / "generations"
    # DOSSIER_SEQUENCE reste l'arbre versionne : sans cela le compteur repart de
    # zero a chaque execution, puisque PROOF_DIR est vierge. Mesure du 2026-09-11 :
    # le juge a produit `GEN-00001` alors que `docs/generations/GEN-00001.json`
    # existait deja avec un autre contenu. Le passeur etant APPEND-ONLY, il aurait
    # REFUSE la divergence -- une preuve qu'on ne peut pas inscrire n'est pas une
    # preuve exploitable, et le defaut se serait vu seulement au moment de publier.

STATUTS = ("STABLE", "CANDIDATE", "REJETEE")

# Paquets dont la version change le comportement observe. Un meme sha ne se
# comporte pas pareil selon eux : c'est la lecon d'hermeticite (un commit qui
# « marchait mardi » peut echouer mercredi sans qu'une ligne ait bouge).
_PAQUETS_TEMOINS = ("torch", "snntorch", "litellm", "pytest", "numpy", "fastapi")


def _git(*args: str, cwd: Path | None = None) -> str:
    """git, en lecture seule. Rend "" si la commande echoue — jamais d'exception
    ici : une generation partiellement renseignee vaut mieux qu'aucune, A CONDITION
    que le champ manquant soit VISIBLE (chaine vide), pas invente."""
    try:
        out = subprocess.run(
            ["git", "-c", "safe.directory=*", *args],
            cwd=str(cwd or ROOT), capture_output=True, text=True, timeout=30,
            # errors="replace" : sans lui, une sortie non-UTF8 (un nom de branche
            # ou un sujet de commit exotique suffit) fait crasher le thread lecteur
            # de subprocess. Incident anti-regression connu du depot.
            errors="replace",
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _paquets() -> dict:
    """Versions des paquets temoins. `absent` est un ETAT, pas une erreur."""
    import importlib.metadata as md

    out = {}
    for nom in _PAQUETS_TEMOINS:
        try:
            out[nom] = md.version(nom)
        except Exception:  # noqa: BLE001 - paquet absent de cet environnement
            out[nom] = "absent"
    return out


def _lock() -> dict:
    """Lock COMPLET des versions installees (hermeticity §14 : reproduire l'ETAT,
    pas seulement le code). Toutes les distributions de l'env courant, triees."""
    import importlib.metadata as md

    out = {}
    for dist in md.distributions():
        try:
            nom = dist.metadata["Name"]
            if nom:
                out[nom] = dist.version
        except Exception:  # noqa: BLE001 - metadata illisible pour cette distribution
            continue
    return dict(sorted(out.items()))


def _submodules() -> dict:
    """{chemin: sha} depuis `git submodule status`. Le prefixe '-' (non initialise)
    et '+' (desynchronise) sont CONSERVES : un submodule desynchronise fait partie
    de l'etat, le masquer rendrait la generation irreproductible."""
    out = {}
    for ligne in (_git("submodule", "status") or "").splitlines():
        ligne = ligne.rstrip()
        if not ligne:
            continue
        marque = ligne[0] if ligne[0] in "-+U" else " "
        reste = ligne[1:].split()
        if len(reste) >= 2:
            out[reste[1]] = {"sha": reste[0], "etat": marque.strip() or "ok"}
    return out


def _prochain_numero() -> int:
    """Le numero suivant, sur l'UNION des TROIS endroits ou une generation peut vivre.

    Lire toutes les sources est ce qui rend le numero stable quel que soit l'endroit
    ou l'artefact atterrit : la sequence dit ou en est le PRODUIT, le depot courant
    ce que CETTE execution a deja produit, et l'ATTENTE ce qui a ete mesure sans
    pouvoir etre inscrit. En mode ordinaire plusieurs de ces repertoires sont le meme
    et rien ne change.

    ⚠️ L'ATTENTE A ETE OUBLIEE, ET CA S'EST VU CINQ JOURS PLUS TARD (2026-09-14).
    Depuis que l'ACL fait DIFFERER l'inscription au lieu de la perdre (2026-09-07),
    les captures atterrissent dans `DOSSIER_ATTENTE` quand `docs/generations` n'est
    pas inscriptible par le compte de la CI. Ce dossier n'etant pas compte,
    `docs/generations` restait fige a GEN-00012 et CHAQUE capture rejouait le numero
    13. Deux etats distincts l'ont porte :

        sandbox/generations_en_attente/GEN-00013.json   sha b55857a799...
        <preuve>/artefacts/generations/GEN-00013.json   sha 37739da46a...

    Pire que l'ambiguite : deux captures differees d'affilee s'ECRASENT dans le
    dossier d'attente, donc la mesure que le correctif de septembre voulait sauver
    etait reperdue. Les deux briques etaient justes, c'est leur croisement qui
    manquait -- et aucune ne pouvait le voir seule.
    """
    DOSSIER.mkdir(parents=True, exist_ok=True)
    nums = []
    for source in {DOSSIER, DOSSIER_SEQUENCE, DOSSIER_ATTENTE}:
        if not source.is_dir():
            continue
        for f in source.glob("GEN-*.json"):
            try:
                nums.append(int(f.stem.split("-")[1]))
            except (IndexError, ValueError):
                continue
    return max(nums, default=0) + 1


def _lock_hash(lock: dict) -> str:
    """Empreinte SHA256 du lock (hermeticity §14 COMPLETE). La veille Bazel/Deno le
    prouve : un lock de versions SANS hash n'est pas hermetique -- il ne detecte pas
    qu'une meme version a ete republiee avec un contenu different."""
    import hashlib
    brut = json.dumps(lock, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(brut).hexdigest()


def _empreinte_capacites() -> dict:
    """Empreinte des capacites vivantes SANS rejeu (evite l'embolie mesuree le
    2026-08-28) : compte les modules forge_* et les tests NR presents. Le GAIN d'une
    generation se lit dans le DELTA de cette empreinte, pas en rejouant la suite."""
    racine = Path(__file__).resolve().parents[1]
    n_forge = sum(len(list((racine / d).glob("forge_*.py")))
                  for d in ("app", "tools") if (racine / d).is_dir())
    nr = racine / "tests" / "nr"
    n_nr = len(list(nr.glob("*.py"))) if nr.is_dir() else 0
    return {"modules_forge": n_forge, "tests_nr": n_nr}


def _verdict_pareto(d_modules: int, d_tests: int) -> str:
    """Verdict SANS mesure de capacite : un compte de fichiers ne prouve JAMAIS un gain.

    Version du 26/09 : les tests etaient une « couverture » (benefice) -- un fichier de test VIDE
    rendait AMELIORE, le Goodhart avait seulement change de compteur (revue claude.ai du
    2026-10-01, mission_rsi_soif, verifiee). Desormais : perdre des tests NR est une
    DEGRADATION (des gardes disparaissent), ajouter des modules est un COUT sans preuve,
    tout le reste est NEUTRE. Le gain se lit dans `_verdict_capacites`."""
    if d_tests < 0:
        return "DEGRADE"                       # des gardes de non-regression ont disparu
    if d_modules > 0:
        return "CROISSANCE_SANS_PREUVE"        # complexite ajoutee, aucun gain mesure
    return "NEUTRE"


def _score_et_bruit(v) -> tuple:
    """Une dimension de capacite : nombre, ou {"score": x, "bruit": b}. (None, 0) si illisible."""
    if isinstance(v, dict):
        v, b = v.get("score"), v.get("bruit", 0)
    else:
        b = 0
    try:
        return float(v), abs(float(b or 0))
    except (TypeError, ValueError):
        return None, 0.0


def _verdict_capacites(cour: dict, prec: dict) -> dict | None:
    """Delta SIGNE par dimension de capacite mesuree des deux cotes ; None si aucune commune.

    Un delta compte seulement au-dela de la bande de bruit DECLAREE par la mesure (la plus
    large des deux) : |delta| <= bruit = NEUTRE, « pas de gain » et non « echec ». Une seule
    dimension qui recule au-dela du bruit suffit a DEGRADE (garde de non-regression)."""
    deltas = {}
    for dim in sorted(set(cour or {}) & set(prec or {})):
        a, ba = _score_et_bruit(cour[dim])
        b, bb = _score_et_bruit(prec[dim])
        if a is None or b is None:
            continue
        deltas[dim] = {"delta": round(a - b, 6), "bruit": max(ba, bb)}
    if not deltas:
        return None
    if any(d["delta"] < -d["bruit"] for d in deltas.values()):
        verdict = "DEGRADE"
    elif any(d["delta"] > d["bruit"] for d in deltas.values()):
        verdict = "AMELIORE"
    else:
        verdict = "NEUTRE"
    return {"verdict": verdict, "capacites_delta": deltas}


def _gain_vs_precedente(empreinte: dict, capacites: dict | None = None) -> dict:
    """Delta d'empreinte vs la derniere generation STABLE deja inscrite, et son VERDICT.

    Avant le 2026-09-26, tout delta positif etait une VICTOIRE : ajouter des fichiers etait
    recompense, dans un corps dont le defaut mesure est la DUPLICATION (bb
    `la_fitness_recompense_l_ajout`, 1326 -> 1401 modules en 13 jours, toutes STABLE). Les
    compteurs restent (retrocompatibles) ; le verdict dit si c'est un gain de Pareto."""
    precedentes = lister("STABLE")
    if not precedentes:
        return {"vs": None, "premiere": True, "verdict": "PREMIERE",
                "modules_forge": empreinte.get("modules_forge", 0),
                "tests_nr": empreinte.get("tests_nr", 0)}
    prev = precedentes[0]
    pe = (prev.get("environnement", {}) or {}).get("empreinte") or {}
    dm = empreinte.get("modules_forge", 0) - pe.get("modules_forge", 0)
    dt = empreinte.get("tests_nr", 0) - pe.get("tests_nr", 0)
    # LE GAIN SE LIT DANS LES CAPACITES (2026-10-01). Les compteurs de fichiers restent
    # (retrocompatibles, et un recul de tests NR reste une degradation) ; un gain ne peut
    # venir que d'une capacite MESUREE des deux cotes. Sans mesure : jamais AMELIORE.
    cap = _verdict_capacites(capacites or {}, prev.get("capacites") or {})
    if cap is None:
        return {"vs": prev.get("generation"), "modules_forge": dm, "tests_nr": dt,
                "verdict": _verdict_pareto(dm, dt), "mesure_de_capacite": False}
    verdict = cap["verdict"]
    if verdict != "DEGRADE" and dt < 0:
        verdict = "DEGRADE"                    # des gardes NR ont disparu : le gain ne les rachete pas
    return {"vs": prev.get("generation"), "modules_forge": dm, "tests_nr": dt,
            "verdict": verdict, "mesure_de_capacite": True,
            "capacites_delta": cap["capacites_delta"]}


# ── FREIN AUTOMATIQUE SUR RECUL DE CAPACITE (mission rsi-frein-auto, 2026-10-02) ──────
# La porte d'evolution sait s'ARRETER ; rien ne la fermait quand une capacite MESUREE
# reculait entre deux generations. Ce bloc compare la generation courante a la derniere
# STABLE, dimension par dimension, et serre le frein sur un recul hors bande.
# Trois regles, chacune un refus de mentir :
#   * MEME CLE seulement : la cle porte l'examen (ex. `retrieval_dense_ndcg10@<sha>`) ; un
#     examen change n'est pas comparable, il ne freine ni ne rassure ;
#   * la bande est le BRUIT DECLARE (le plus large des deux) : sans bruit, pas de bande, donc
#     ABSTENTION ;
#   * une mesure ILLISIBLE n'est ni un frein ni un feu vert : abstention DITE, et le verdict
#     global n'est jamais « dans la bande » s'il reste une dimension non jugee.
PAR_FREIN_AUTO = "auto:capacite"


def _nombre(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _age_s(e: dict, maintenant: float):
    if _nombre(e.get("age_s")) is not None:
        return float(e["age_s"])
    for k in ("measured_at", "mesure_le", "ts", "cree_le"):
        v = e.get(k)
        if _nombre(v) is not None:
            return max(0.0, maintenant - float(v))
        if isinstance(v, str) and v:
            try:
                return max(0.0, maintenant - datetime.fromisoformat(v).timestamp())
            except ValueError:
                continue  # muet-ok : une autre cle de date peut suffire ; sinon age None, dit
    return None


def capacites_normalisees(brut, maintenant: float | None = None) -> dict:
    """{dimension: {score, bruit, n, age_s, lisible, motif}} depuis les formes connues.

    Formes acceptees : {dim: score} ; {dim: {score, bruit, n, ...}} ; {"capacites": ...} ;
    [{dimension, score, bruit, ...}]. Une entree dont le score n'est pas un nombre fini est
    gardee ILLISIBLE (avec son motif) : la retirer la ferait passer pour absente.
    """
    import time as _t

    t = _t.time() if maintenant is None else float(maintenant)
    if isinstance(brut, dict) and isinstance(brut.get("capacites"), (dict, list)):
        brut = brut["capacites"]
    if isinstance(brut, list):
        brut = {str(x.get("dimension")): x for x in brut
                if isinstance(x, dict) and x.get("dimension")}
    if not isinstance(brut, dict):
        return {}
    out = {}
    for dim, e in brut.items():
        e = e if isinstance(e, dict) else {"score": e}
        score = _nombre(e.get("score"))
        bruit = _nombre(e.get("bruit"))
        n = e.get("n")
        out[str(dim)] = {"score": score, "bruit": None if bruit is None else abs(bruit),
                         "n": int(n) if _nombre(n) is not None else None,
                         "age_s": _age_s(e, t), "lisible": score is not None,
                         "motif": "" if score is not None else "score illisible : %r" % (e.get("score"),)}
    return out


def verdict_recul(courantes, precedentes) -> dict:
    """Compare deux jeux de capacites. Pur, sans effet. Verdicts :
    RECUL · DANS_LA_BANDE · ABSTENTION · AUCUNE_DIMENSION_COMMUNE."""
    cur, prev = capacites_normalisees(courantes), capacites_normalisees(precedentes)
    communes = sorted(set(cur) & set(prev))
    reculs, dans_bande, abstentions = [], [], []
    for dim in communes:
        a, b = prev[dim], cur[dim]
        if not (a["lisible"] and b["lisible"]):
            abstentions.append({"dimension": dim, "motif": a["motif"] or b["motif"]})
            continue
        bruits = [x for x in (a["bruit"], b["bruit"]) if x is not None]
        if not bruits:
            abstentions.append({"dimension": dim,
                                "motif": "bruit non declare : la bande est inconnue"})
            continue
        bande = max(bruits)
        delta = b["score"] - a["score"]
        ligne = {"dimension": dim, "avant": a["score"], "apres": b["score"],
                 "delta": round(delta, 6), "bande": bande}
        (reculs if delta < -bande else dans_bande).append(ligne)
    if reculs:
        verdict = "RECUL"
    elif abstentions:
        verdict = "ABSTENTION"
    elif dans_bande:
        verdict = "DANS_LA_BANDE"
    else:
        verdict = "AUCUNE_DIMENSION_COMMUNE"
    return {"verdict": verdict, "reculs": reculs, "dans_bande": dans_bande,
            "abstentions": abstentions,
            "non_comparees": sorted(set(cur) ^ set(prev))}


def _precedente_avec_capacites() -> dict | None:
    """La derniere generation STABLE qui porte des capacites : la reference saine."""
    for g in lister("STABLE"):
        if g.get("capacites"):
            return g
    return None


def _poser_frein_auto(motif: str) -> dict:
    """Serre le frein d'evolution par le juge (qui re-exporte la porte, ou qu'elle vive)."""
    try:
        from nokido_agent.app import forge_mutation_judge as _juge
        f = getattr(_juge, "poser_frein_evolution", None)
        if f is None:
            return {"pose": False, "motif": motif,
                    "pourquoi": "poser_frein_evolution absent de forge_mutation_judge"}
        return {"pose": True, "motif": motif, "retour": f(motif, par=PAR_FREIN_AUTO)}
    except Exception as exc:  # noqa: BLE001 - un frein rate se DIT ; la capture continue
        return {"pose": False, "motif": motif,
                "pourquoi": "%s: %s" % (type(exc).__name__, str(exc)[:160])}


def frein_si_recul(capacites: dict, precedente: dict | None = None) -> dict:
    """Compare a la derniere STABLE ; serre le frein sur un recul hors bande, motif CHIFFRE.

    Rend le verdict (et le frein, s'il a ete serre). N'agit sur rien d'autre."""
    prec = precedente if precedente is not None else _precedente_avec_capacites()
    if not prec:
        return {"verdict": "SANS_REFERENCE", "frein": None,
                "note": "aucune generation STABLE portant des capacites : rien a comparer"}
    v = verdict_recul(capacites, prec.get("capacites") or {})
    v["vs"] = prec.get("generation")
    v["frein"] = None
    if v["verdict"] == "RECUL":
        motif = "recul de capacite hors bande vs %s : %s" % (v["vs"], " ; ".join(
            "%s %.4f -> %.4f (delta %+.4f, bande %.4f)"
            % (r["dimension"], r["avant"], r["apres"], r["delta"], r["bande"])
            for r in v["reculs"]))
        v["frein"] = _poser_frein_auto(motif)
    return v


def _append_oplog(entry: dict) -> None:
    """Op-log APPEND-ONLY des generations stables (patron Codex CLI : journal JSONL
    rejouable + requetable). Chaque ligne = une victoire figee et immuable ; le
    fichier ne se reecrit jamais, il ne fait que croitre. Best-effort."""
    try:
        oplog = DOSSIER / "oplog.jsonl"
        oplog.parent.mkdir(parents=True, exist_ok=True)
        with open(oplog, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        pass  # muet-ok : l'op-log est un journal best-effort, il ne bloque pas la capture


def capturer(tests: dict | None = None, capacites: dict | None = None,
             metriques: dict | None = None, agent: str = "", note: str = "") -> dict:
    """Inscrit l'etat courant. Rend la generation ecrite.

    `tests` : {suite: "PASS"|"FAIL"|"NON_MESURE"}. Le statut en DECOULE, il ne se
    declare pas : STABLE exige au moins une suite et aucune en echec ni non mesuree.
    Sans preuve, la capture est CANDIDATE — et le dit.
    """
    tests = dict(tests or {})
    verdicts = set(tests.values())
    if not tests:
        statut, raison = "CANDIDATE", "aucune suite de tests fournie"
    elif "FAIL" in verdicts:
        statut, raison = "REJETEE", "au moins une suite en echec"
    elif "NON_MESURE" in verdicts:
        statut, raison = "CANDIDATE", "au moins une suite non mesuree"
    else:
        statut, raison = "STABLE", "toutes les suites fournies sont vertes"

    _lock_val = _lock()
    _empr = _empreinte_capacites()
    _gain = _gain_vs_precedente(_empr, capacites) if statut == "STABLE" else None
    # Frein automatique AVANT l'ecriture : un recul mesure se signale meme si l'inscription
    # est ensuite differee par l'ACL -- la mesure, elle, a bien eu lieu.
    _frein_auto = frein_si_recul(dict(capacites)) if capacites else None
    sha = _git("rev-parse", "HEAD")
    if not sha:
        raise RuntimeError("sha HEAD illisible : refus d'inscrire une generation "
                           "qui ne pourrait pas etre restauree")

    num = _prochain_numero()
    gen = {
        "generation": "GEN-%05d" % num,
        "cree_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "statut": statut,
        "statut_raison": raison,
        "agent": agent or os.environ.get("LAFORGE_AGENT", "inconnu"),
        "note": note[:300],
        "depot": {
            "sha": sha,
            "branche": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "sujet": _git("log", "-1", "--format=%s"),
            # SEULES les modifications de fichiers SUIVIS rendent le sha non
            # representatif : un non-suivi n'a jamais fait partie d'un commit. Le
            # depot en porte des dizaines en permanence (manifestes gitingest,
            # artefacts d'audit regeneres) -- les compter rendait `propre` FAUX
            # pour toujours. Meme defaut que ci_local, paye le 2026-09-07.
            "propre": _git("status", "--porcelain", "--untracked-files=no") == "",
            "non_suivis": len([x for x in (_git("status", "--porcelain") or "").splitlines()
                               if x.startswith("??")]),
        },
        "submodules": _submodules(),
        "environnement": {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "paquets": _paquets(),
            "lock": _lock_val,
            "lock_sha256": _lock_hash(_lock_val),
            "empreinte": _empr,
        },
        "tests": tests,
        "capacites": dict(capacites or {}),
        "metriques": dict(metriques or {}),
    }
    if _frein_auto is not None:
        gen["frein_auto"] = _frein_auto

    DOSSIER.mkdir(parents=True, exist_ok=True)
    chemin = DOSSIER / ("%s.json" % gen["generation"])
    if chemin.exists():
        raise FileExistsError("%s existe deja : une generation est IMMUABLE" % chemin.name)
    _brut = json.dumps(gen, ensure_ascii=False, indent=2)
    try:
        chemin.write_text(_brut, encoding="utf-8")
    except OSError as _err:
        # ACL, pas logique. `docs/generations/` est un artefact SUIVI par git : il
        # vit donc dans le depot, or les comptes sandbox n'ont pas l'ecriture sur
        # `docs/` (mesure 2026-09-07 : docs/ NON, tests/nr/ NON, sandbox/ OUI). La
        # CI tourne detachee sous l'un d'eux et ne peut pas davantage deleguer au
        # hub : un run_job ne voit pas le loopback (timeout muet a 120 s, 2026-09-01).
        #
        # On ne ment pas et on ne perd rien : la MESURE est deposee la ou l'ecriture
        # est possible, l'INSCRIPTION reste a faire par un chemin gouverne. Les deux
        # actes restent distincts -- l'instrument de mesure ne doit jamais deduire sa
        # reussite du mecanisme d'ecriture.
        DOSSIER_ATTENTE.mkdir(parents=True, exist_ok=True)
        _depot = DOSSIER_ATTENTE / ("%s.json" % gen["generation"])
        gen["inscription_differee"] = {
            "cible": str(chemin),
            "depot": str(_depot),
            "motif": "%s: %s" % (type(_err).__name__, _err),
            "errno": getattr(_err, "errno", None),
            "fichier": getattr(_err, "filename", None),
            # Le GAIN etait calcule juste au-dessus puis PERDU sur ce chemin : le
            # bloc qui le consigne vit apres le `return` nominal, donc hors de
            # portee ici. L'op-log n'est pas sa place -- un NR anterieur l'arrete
            # explicitement (« l'oplog ne consigne pas un gain qui n'a pas ete
            # inscrit »), et il a raison : ce journal ne porte que des victoires
            # INSCRITES. Le gain voyage donc AVEC sa mesure, dans le fichier
            # depose, pour qu'une inscription ulterieure n'ait pas a le recalculer
            # sur un etat qui aura change. Mesure du 2026-09-20 : 28 generations en
            # attente, 30 produites, 0 gain conserve.
            "gain": _gain,
            "empreinte": _empr,
        }
        # Le marqueur est pose AVANT la serialisation. Il l'etait apres : `_brut`
        # ayant deja ete calcule, le fichier depose ne portait AUCUNE trace du
        # differe (mesure : 0/28). L'appelant l'apprenait, le disque jamais -- une
        # capture differee et une capture ordinaire etaient indistinguables sur
        # artefact, donc personne ne pouvait savoir qu'une inscription restait due.
        _depot.write_text(json.dumps(gen, ensure_ascii=False, indent=2), encoding="utf-8")
        return gen
    if _gain is not None:
        _append_oplog({
            "generation": gen["generation"],
            "sha": sha,
            "ts": gen["cree_le"],
            "statut": statut,
            "empreinte": _empr,
            "lock_sha256": gen["environnement"]["lock_sha256"],
            "gain": _gain,
            "note": note[:120],
        })
    return gen


def _sha_deja_capture(sha: str) -> str | None:
    """Rend le nom de la generation qui porte deja ce sha, sinon None."""
    for g in lister():
        if g.get("depot", {}).get("sha") == sha:
            return g["generation"]
    return None


def capacites_mesurees(dossier: Path | None = None, age_max_s: float = 7 * 86400) -> dict:
    """{dimension: {"score", "bruit"}} des mesures de capacite RECENTES (`sandbox/capacites/*.json`).

    Producteur (2026-10-01) : `forge_bench_beir.mesurer_capacite` -- retrieval dense sur l'examen
    held-out SCELLE. Seul un verdict `MESURE` entre ; INDECIDABLE ne se lit jamais comme un score.
    La dimension porte deja la cle de l'examen et du corpus : ici on ne fait que la transporter.
    Illisible ou perime -> absent (et `_gain_vs_precedente` le traite comme « sans mesure »)."""
    import json as _json
    import time as _time

    base = dossier or (Path(__file__).resolve().parents[1] / "sandbox" / "capacites")
    out = {}
    for f in sorted(base.glob("*.json")) if base.is_dir() else []:
        try:
            rec = _json.loads(f.read_text(encoding="utf-8"))
            ts = _time.mktime(_time.strptime(rec["ts"], "%Y-%m-%dT%H:%M:%S"))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if rec.get("verdict") == "MESURE" and rec.get("dimension") and _time.time() - ts <= age_max_s:
            out[rec["dimension"]] = {"score": rec.get("score"), "bruit": rec.get("bruit", 0)}
    return out


def capturer_si_absent(tests: dict | None = None, capacites: dict | None = None,
                       metriques: dict | None = None, agent: str = "",
                       note: str = "") -> dict:
    """Capture l'etat courant UNE SEULE FOIS par sha.

    C'est le chainon qui rend les generations automatiques : appele au verdict vert
    d'une passe CI, il inscrit un point de retour a chaque etat valide, et il ne
    fait rien si ce meme sha a deja sa generation. Sans le garde par sha, relancer
    la CI sur un working tree inchange creerait une generation par run -- du bruit,
    pas un historique.

    Rend {"skip": <nom>} si le sha est deja capture, sinon la generation ecrite.
    """
    sha = _git("rev-parse", "HEAD")
    if not sha:
        return {"skip": None, "raison": "sha HEAD illisible"}
    deja = _sha_deja_capture(sha)
    if deja:
        return {"skip": deja, "sha": sha}
    return capturer(tests=tests, capacites=capacites, metriques=metriques,
                    agent=agent, note=note)


def lister(statut: str = "") -> list:
    """Generations, de la plus recente a la plus ancienne."""
    if not DOSSIER.exists():
        return []
    out = []
    for f in sorted(DOSSIER.glob("GEN-*.json"), reverse=True):
        try:
            g = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # une generation illisible se SIGNALE plus bas, pas en silence
        if statut and g.get("statut") != statut:
            continue
        out.append(g)
    return out


def derniere_stable() -> dict | None:
    """La reference : le dernier etat dont les tests etaient verts."""
    stables = lister("STABLE")
    return stables[0] if stables else None


def plan_restauration(generation: str) -> dict:
    """Rend les commandes pour revenir a une generation — SANS les executer.

    Verifie d'abord que les sha existent ENCORE : une generation dont le commit a
    ete emporte par un elagage n'est plus restaurable, et le dire vaut mieux que
    rendre un plan qui echouera au milieu.
    """
    gens = {g["generation"]: g for g in lister()}
    g = gens.get(generation)
    if not g:
        return {"ok": False, "raison": "generation inconnue: %s" % generation}

    sha = g["depot"]["sha"]
    joignable = bool(_git("cat-file", "-e", "%s^{commit}" % sha) == "") and \
        _git("rev-parse", "--quiet", "--verify", "%s^{commit}" % sha) != ""
    manquants = [] if joignable else ["depot:%s" % sha]
    for chemin, info in (g.get("submodules") or {}).items():
        sous = ROOT / chemin
        if sous.exists() and not _git("rev-parse", "--quiet", "--verify",
                                      "%s^{commit}" % info["sha"], cwd=sous):
            manquants.append("%s:%s" % (chemin, info["sha"]))

    return {
        "ok": not manquants,
        "generation": generation,
        "manquants": manquants,
        "avertissement": (
            "ces commandes ECRASENT le working tree courant — action irreversible, "
            "a executer par l'owner apres avoir mis de cote le travail en cours"),
        "commandes": [
            'git -C "%s" worktree add ../nokido-%s %s' % (ROOT, generation.lower(), sha),
            'cd ../nokido-%s && git submodule update --init --recursive' % generation.lower(),
        ],
        "pourquoi_worktree": (
            "un worktree restaure l'etat SANS toucher au depot courant : on peut "
            "mesurer l'ancienne generation et la comparer, au lieu de parier"),
    }


def comparer(a: str, b: str) -> dict:
    """Ce qui a change entre deux generations — code, environnement, tests."""
    gens = {g["generation"]: g for g in lister()}
    ga, gb = gens.get(a), gens.get(b)
    if not ga or not gb:
        return {"ok": False, "raison": "generation inconnue"}
    paq_a = ga["environnement"]["paquets"]
    paq_b = gb["environnement"]["paquets"]
    return {
        "ok": True,
        "sha": {a: ga["depot"]["sha"], b: gb["depot"]["sha"]},
        "statut": {a: ga["statut"], b: gb["statut"]},
        "paquets_differents": {
            k: {a: paq_a.get(k), b: paq_b.get(k)}
            for k in set(paq_a) | set(paq_b) if paq_a.get(k) != paq_b.get(k)
        },
        "python_different": (ga["environnement"]["python"] != gb["environnement"]["python"]),
        "tests_differents": {
            k: {a: ga["tests"].get(k, "absent"), b: gb["tests"].get(k, "absent")}
            for k in set(ga["tests"]) | set(gb["tests"])
            if ga["tests"].get(k) != gb["tests"].get(k)
        },
    }


def promouvoir() -> dict:
    """Inscrit les generations restees en ATTENTE. Le PENDANT du differe.

    Le mecanisme de report a ete pose le 2026-09-07 pour ne pas perdre la mesure
    quand l'ACL refuse `docs/` au compte de la CI, et son commentaire annonce la
    suite : « l'INSCRIPTION reste a faire par un chemin gouverne ». Ce chemin
    n'avait jamais ete ecrit. Mesure du 2026-09-20 : 28 generations en attente,
    la plus recente a 5 h, `docs/generations` fige a GEN-00012 depuis 11,2 jours.
    Le dossier d'attente etait un CUL-DE-SAC -- `produit(n) != consomme(n+1)`.

    Trois refus, parce que trois choses distinctes peuvent arriver :

      promues   inscrites a l'instant -> l'op-log parle ICI, et nulle part
                ailleurs : c'est le seul moment ou une generation devient une
                victoire INSCRITE, ce qu'un NR anterieur exige.
      conflits  le numero est deja pris par une AUTRE mesure. On n'ecrase pas :
                une generation est immuable, et deux mesures ne partagent pas un
                numero. Le conflit se DIT, il ne se resout pas tout seul.
      refusees  la cible refuse encore l'ecriture. La mesure reste en attente,
                intacte. On ne detruit jamais une mesure qu'on n'a pas su placer.

    Le gain n'est PAS recalcule : il est repris tel quel depuis
    `inscription_differee`. L'empreinte a change depuis la capture -- recalculer
    donnerait un chiffre d'aujourd'hui presente comme la mesure d'hier.
    """
    res = {"promues": [], "conflits": [], "refusees": [], "attente": str(DOSSIER_ATTENTE)}
    if not DOSSIER_ATTENTE.is_dir():
        return res
    for src in sorted(DOSSIER_ATTENTE.glob("GEN-*.json")):
        try:
            gen = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            res["refusees"].append({"fichier": src.name, "motif": "illisible: %s" % exc})
            continue
        nom = gen.get("generation") or src.stem
        cible = DOSSIER / ("%s.json" % nom)
        if cible.exists():
            res["conflits"].append({"generation": nom, "motif": "deja inscrite, non ecrasee"})
            continue
        differe = gen.pop("inscription_differee", {}) or {}
        gain = differe.get("gain")
        gen["inscription_rattrapee"] = {
            "le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "depuis": str(src),
            "motif_initial": differe.get("motif"),
        }
        try:
            DOSSIER.mkdir(parents=True, exist_ok=True)
            cible.write_text(json.dumps(gen, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            res["refusees"].append({"generation": nom, "motif": "%s: %s" % (type(exc).__name__, exc)})
            continue
        if gain is not None:
            _append_oplog({
                "generation": nom,
                "sha": (gen.get("depot") or {}).get("sha"),
                "ts": gen.get("cree_le"),
                "statut": gen.get("statut"),
                "empreinte": differe.get("empreinte")
                or (gen.get("environnement") or {}).get("empreinte"),
                "lock_sha256": (gen.get("environnement") or {}).get("lock_sha256"),
                "gain": gain,
                "note": str(gen.get("note", ""))[:120],
                "inscription": "RATTRAPEE",
            })
        # Le contenu vit maintenant dans DOSSIER : retirer la copie d'attente est un
        # DEPLACEMENT, pas une suppression -- et seulement apres ecriture reussie.
        try:
            src.unlink()
        except OSError:
            pass  # muet-ok : la mesure est inscrite, un doublon d'attente ne la menace pas
        res["promues"].append(nom)
    return res


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Registre des generations Nokido")
    ap.add_argument("action", choices=("capturer", "lister", "plan", "comparer", "promouvoir"))
    ap.add_argument("--tests", default="", help="suite=PASS,suite2=FAIL")
    ap.add_argument("--agent", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--gen", default="")
    ap.add_argument("--gen2", default="")
    a = ap.parse_args()

    if a.action == "promouvoir":
        r = promouvoir()
        print(json.dumps(r, ensure_ascii=False, indent=2))
        # `refusees` non vide = rien n'a pu etre inscrit la ou on le demandait :
        # le rc le DIT, pour qu'un appelant ne lise pas 0 comme « tout est inscrit ».
        return 1 if r["refusees"] else 0

    if a.action == "capturer":
        tests = {}
        for part in filter(None, a.tests.split(",")):
            k, _, v = part.partition("=")
            tests[k.strip()] = (v.strip() or "NON_MESURE").upper()
        g = capturer(tests=tests, agent=a.agent, note=a.note)
        print(json.dumps(g, ensure_ascii=False, indent=2))
    elif a.action == "lister":
        for g in lister():
            print("%s  %s  %-9s  %s  %s" % (
                g["generation"], g["cree_le"], g["statut"],
                g["depot"]["sha"][:9], g["depot"]["sujet"][:60]))
    elif a.action == "plan":
        print(json.dumps(plan_restauration(a.gen), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(comparer(a.gen, a.gen2), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
