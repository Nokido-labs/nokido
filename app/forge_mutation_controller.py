#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""app/forge_mutation_controller.py -- le KERNEL DE MUTATION (brief §6, §9, §11).

UNIFIE les briques existantes en UN flux "agent = producteur de patch" :
    worktree(agent) -> agent edite+commit dans wip/<agent> -> MERGE GATE (juge sur
    invariants tests/nr) -> si AMELIORE : merge -> MESURE APRES -> garde + GENERATION
    restaurable, ou REVERT prouve.

ANTI-DUP total : n'implemente RIEN, orchestre forge_worktree (isolation),
forge_merge_gate (juge wip->alpha), forge_generation (etat immuable restaurable).
Le brief §11 listait forge_mutation_controller / forge_baseline / forge_provenance /
forge_recovery ; les trois derniers EXISTENT deja sous d'autres noms -- baseline =
forge_mutation_judge.mesurer, provenance = forge_session_provenance, recovery =
forge_capability_recovery. Ce module est le CONTROLEUR qui les enchaine, pas un doublon.

MESURE APRES APPLICATION (mission regeneration du 2026-10-01, note RSI §2.3-2.4)
-------------------------------------------------------------------------------
Le juge decide AVANT d'appliquer. Rien ne regardait APRES : une mutation fusionnee qui
degradait le canonique restait en place, et aucune trace ne reliait l'effet a son
experience. `mesurer_apres` ferme ce maillon pour les deux niveaux :
  L1  un reglage pose par `forge_proposal_applier` (`set_param`) ;
  L3  un merge wip -> alpha fait par la merge gate.
Sequence : mesure APRES, comparee a la reference d'AVANT dimension par dimension ;
une dimension qui recule au-dela de sa bande de bruit (ou qui disparait) = regression
-> REVERT (valeur memorisee en L1, `git revert -m 1` en L3). Le revert n'est PROUVE que
si l'empreinte redevient celle d'avant ET si la mesure revient dans la bande. Tout est
inscrit au registre d'evolution chaine, rattache a l'`exp_id`.

Ce que ce module ne fait PAS : juger un GAIN. La question ici est plus etroite -- « la
mesure est-elle restee, ou revenue, dans la bande de la reference ? ». Le gain reste au
juge (`forge_mutation_judge.juger_gain`, `forge_generation._verdict_capacites`).

LA PORTE ET LE FREIN. L'acte (appliquer) passe par la porte unique
`forge_mutation_judge.evolution_autorisee()` ; une porte absente ou illisible est
FERMEE. Le RETOUR ARRIERE, lui, ne la consulte pas : un frein arrete les mutations,
il n'empeche jamais de revenir a l'etat sur. Revert non prouve, ou deux reverts
consecutifs -> `poser_frein_evolution` (seul l'owner le retire).

Owner-run. dry-run par defaut (le merge reel exige --apply, propage au merge gate).

API ajoutee depuis le 2026-10-01 (premiere ligne de la docstring de chaque symbole) :
- `mesurer_apres` — Mesure APRES un acte deja fait ; garde, ou revient en arriere et le PROUVE.
- `appliquer_et_mesurer` — Porte -> reference AVANT -> acte -> `mesurer_apres`. Le chemin L1.
- `mesurer_apres_merge` — L3 : mesure apres un merge DEJA fait ; regression -> `git revert -m 1`.
"""
from __future__ import annotations

__FORGE_COLOR__ = "locomoteur/orchestr : kernel de mutation, unifie les briques d'automutation"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

# Verdicts de la mesure apres application. Ceux de REVERTS comptent pour le frein.
CONSERVE = "CONSERVE"
REVERTE = "REVERTE"
REVERT_NON_PROUVE = "REVERT_NON_PROUVE"
REVERTS = (REVERTE, REVERT_NON_PROUVE)
# Au-dela, la boucle s'arrete d'elle-meme : deux reverts de suite disent que le producteur
# degrade plus vite que le juge ne filtre -- on cesse de muter avant d'accumuler.
REVERTS_CONSECUTIFS_FREIN = 2


# ── Porte et frein (API du juge ; absente = fermee / non posee, et DIT) ─────────────
def _porte() -> dict:
    """Etat de la porte d'evolution. Fail-closed (cf. forge_proposal_applier.porte_evolution)."""
    from nokido_agent.app.forge_proposal_applier import porte_evolution
    return porte_evolution()


def _poser_frein(motif: str) -> dict:
    """Pose le frein d'evolution. Un frein qu'on n'a pas pu poser se DIT dans le resultat."""
    try:
        from nokido_agent.app import forge_mutation_judge as _juge
        f = getattr(_juge, "poser_frein_evolution", None)
        if f is None:
            return {"pose": False, "motif": motif,
                    "pourquoi": "poser_frein_evolution absent de forge_mutation_judge"}
        r = f(motif, par="forge_mutation_controller")
        return {"pose": True, "motif": motif, "retour": r}
    except Exception as exc:  # noqa: BLE001 - le frein rate se dit, il ne masque pas le revert
        return {"pose": False, "motif": motif,
                "pourquoi": "%s: %s" % (type(exc).__name__, str(exc)[:160])}


# ── Registre d'evolution (chaine) ────────────────────────────────────────────────────
def _inscrire(rec: dict) -> str:
    from nokido_agent.app.forge_autonomous_loops import record_evolution_experience
    return record_evolution_experience(rec)


def _reverts_consecutifs() -> int:
    """Nombre de `post_application` REVERTES a la suite, en partant de la plus recente.

    Lu dans le registre (persistant, chaine) et non en memoire : le compte survit au
    process, et un CONSERVE intercale le remet a zero."""
    from nokido_agent.app import forge_autonomous_loops as _al
    try:
        lignes = Path(_al._EVOLUTION_LEDGER).read_text(encoding="utf-8",
                                                       errors="replace").splitlines()
    except FileNotFoundError:
        return 0
    n = 0
    for ligne in reversed(lignes):
        try:
            e = json.loads(ligne)
        except ValueError:
            continue  # muet-ok : verifier_chaine_evolution compte et nomme les lignes illisibles
        if e.get("kind") != "post_application" or e.get("verdict") == "NON_APPLIQUE":
            continue  # un acte qui n'a pas eu lieu n'interrompt ni ne prolonge une serie
        if e.get("verdict") in REVERTS:
            n += 1
        else:
            break
    return n


def _generation_avant() -> dict | None:
    """La derniere generation STABLE : la reference durable a laquelle l'acte se rattache."""
    try:
        from nokido_agent.app.forge_generation import derniere_stable
        g = derniere_stable()
    except Exception:  # noqa: BLE001 - registre illisible : la trace le dit (None)
        return None
    if not g:
        return None
    return {"generation": g.get("generation"), "sha": (g.get("depot") or {}).get("sha"),
            "capacites": g.get("capacites") or {}}


# ── Bande de bruit ───────────────────────────────────────────────────────────────────
def _nombre(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def ecarts_hors_bande(reference: dict, mesure: dict | None, bruit: dict,
                      sens: str = "recul") -> list[dict]:
    """Dimensions de `reference` sorties de la bande. Plus haut = mieux, par convention.

    `sens="recul"` : regression seulement (delta < -bruit) -- le critere pour REVERTER.
    `sens="ecart"` : tout ecart (|delta| > bruit) -- le critere « REVENU dans la bande ».
    Une dimension ABSENTE ou non numerique apres coup compte toujours : une mesure perdue
    ne prouve pas que rien n'a recule. Bruit non declare pour une dimension = 0 (strict).
    """
    if not isinstance(mesure, dict):
        return [{"dimension": "*", "motif": "mesure absente"}]
    out = []
    for dim, ref in sorted(reference.items()):
        r, m = _nombre(ref), _nombre(mesure.get(dim))
        b = abs(_nombre(bruit.get(dim)) or 0.0)
        if r is None:
            continue  # une reference non numerique ne juge rien (elle se voit dans la trace)
        if m is None:
            out.append({"dimension": dim, "reference": ref, "mesure": mesure.get(dim),
                        "motif": "dimension absente ou non numerique apres l'acte"})
            continue
        d = m - r
        if d < -b or (sens == "ecart" and d > b):
            out.append({"dimension": dim, "reference": r, "mesure": m,
                        "delta": round(d, 6), "bruit": b})
    return out


def _empreinte_sure(empreinte) -> str | None:
    """Empreinte courante, ou None si illisible. None n'est JAMAIS egal a rien : deux
    lectures ratees ne prouvent pas que l'etat est revenu."""
    try:
        e = empreinte()
    except Exception:  # noqa: BLE001 - muet-ok : None porte l'echec, la preuve le refusera
        return None
    if not isinstance(e, str) or not e or e.startswith("illisible"):
        return None
    return e


def _dimensions_jugeables(reference: dict) -> int:
    return sum(1 for v in (reference or {}).values() if _nombre(v) is not None)


def _mesure_sure(mesurer) -> tuple[dict | None, str | None]:
    try:
        m = mesurer()
    except Exception as exc:  # noqa: BLE001 - une mesure qui leve est une mesure ABSENTE
        return None, "%s: %s" % (type(exc).__name__, str(exc)[:160])
    if not isinstance(m, dict):
        return None, "mesure non conforme (%s)" % type(m).__name__
    return m, None


# ── Le maillon : mesurer APRES, garder ou revenir et le PROUVER ─────────────────────
def mesurer_apres(niveau: str, cible: str, exp_id: str | None, reference: dict,
                  empreinte_avant: str | None, mesurer, reverter, empreinte, bruit: dict,
                  application: dict | None = None, apres_conserve=None) -> dict:
    """Mesure APRES un acte deja fait ; garde, ou revient en arriere et le PROUVE.

    `reference`       mesure d'AVANT l'acte, {dimension: score} (plus haut = mieux) ;
    `empreinte_avant` empreinte de l'etat d'avant (arbre git en L3, magasin L1) ;
    `mesurer()`       rend la mesure courante ; `reverter()` defait l'acte ;
    `empreinte()`     rend l'empreinte courante ; `bruit` = bande par dimension ;
    `apres_conserve()` (optionnel) : appele seulement si l'acte est GARDE (ex. generation).

    Ne consulte PAS la porte : revenir a l'etat sur reste permis frein serre.
    """
    bruit = dict(bruit or {})
    apres, err_apres = _mesure_sure(mesurer)
    rec = {"kind": "post_application", "niveau": niveau, "cible": cible, "ref_exp": exp_id,
           "reference": reference, "apres": apres, "bruit": bruit,
           "empreinte_avant": empreinte_avant, "application": application or {},
           "generation_avant": _generation_avant()}
    if not _dimensions_jugeables(reference):
        # Aucune dimension numerique a laquelle comparer : « rien n'a recule » serait vrai
        # PAR VIDE. On ne defait pas un acte que le juge a admis, mais la boucle ne continue
        # pas a l'aveugle : le frein appelle un regard humain.
        rec.update(verdict="INDECIDABLE", status="INDECIDABLE",
                   pourquoi="reference sans dimension jugeable : l'apres ne se compare a rien")
        rec_id = _inscrire(rec)
        frein = _poser_frein("mesure apres INDECIDABLE (%s, %s) : reference vide" % (niveau, cible))
        return {"verdict": "INDECIDABLE", "exp_id": exp_id, "post_id": rec_id, "applique": True,
                "reference": reference, "apres": apres, "frein": frein}
    ecarts = ecarts_hors_bande(reference, apres, bruit)
    if err_apres:
        ecarts = [{"dimension": "*", "motif": "mesure APRES illisible : %s" % err_apres}]

    if not ecarts:
        rec["verdict"] = CONSERVE
        rec["status"] = "CONSERVE"
        if apres_conserve is not None:
            try:
                rec["apres_conserve"] = apres_conserve()
            except Exception as exc:  # noqa: BLE001 - l'acte garde reste garde ; la trace dit l'echec
                rec["apres_conserve"] = {"erreur": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
        rec_id = _inscrire(rec)
        return {"verdict": CONSERVE, "exp_id": exp_id, "post_id": rec_id, "applique": True,
                "reference": reference, "apres": apres, "ecarts": [],
                "apres_conserve": rec.get("apres_conserve")}

    # REGRESSION (ou mesure perdue) : on defait, puis on PROUVE le retour.
    try:
        rev = reverter() or {}
    except Exception as exc:  # noqa: BLE001 - un revert qui leve n'est pas prouve, et le frein suit
        rev = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
    empreinte_revert = _empreinte_sure(empreinte)
    mesure_revert, err_rev = _mesure_sure(mesurer)
    hors = ecarts_hors_bande(reference, mesure_revert, bruit, sens="ecart")
    preuve = {"revert_ok": bool(rev.get("ok")),
              "empreinte_identique": (empreinte_avant is not None
                                      and empreinte_revert == empreinte_avant),
              "empreinte_revert": empreinte_revert,
              "mesure_revenue_dans_bande": not hors and err_rev is None,
              "mesure_revert": mesure_revert, "hors_bande_apres_revert": hors,
              "detail_revert": rev}
    prouve = (preuve["revert_ok"] and preuve["empreinte_identique"]
              and preuve["mesure_revenue_dans_bande"])
    verdict = REVERTE if prouve else REVERT_NON_PROUVE
    rec.update({"verdict": verdict, "status": verdict, "ecarts": ecarts, "preuve": preuve})
    rec_id = _inscrire(rec)

    frein = None
    if not prouve:
        frein = _poser_frein("revert NON PROUVE (%s, %s) : etat sur non garanti"
                             % (niveau, cible))
    else:
        n = _reverts_consecutifs()
        if n >= REVERTS_CONSECUTIFS_FREIN:
            frein = _poser_frein("%d reverts consecutifs (dernier : %s, %s) -- le producteur "
                                 "degrade plus vite que le juge ne filtre" % (n, niveau, cible))
    return {"verdict": verdict, "exp_id": exp_id, "post_id": rec_id, "applique": True,
            "reference": reference, "apres": apres, "ecarts": ecarts, "preuve": preuve,
            "frein": frein}


def appliquer_et_mesurer(niveau: str, cible: str, exp_id: str | None, appliquer, reverter,
                         mesurer, empreinte, bruit: dict, apres_conserve=None) -> dict:
    """Porte -> reference AVANT -> acte -> `mesurer_apres`. Le chemin L1.

    Porte FERMEE (HALTED, DESARMEE, VERROU_HUMAIN, INCONNU) : rien n'est mesure, rien
    n'est ecrit, ni dans l'etat ni au registre -- le verdict est l'etat de la porte.
    Mesure d'AVANT illisible : on n'applique pas, faute de reference pour juger l'apres.
    """
    porte = _porte()
    if not porte.get("autorisee"):
        return {"verdict": porte.get("etat") or "INCONNU", "applique": False,
                "porte": porte, "exp_id": exp_id}
    reference, err = _mesure_sure(mesurer)
    if err:
        return {"verdict": "INDECIDABLE", "applique": False, "exp_id": exp_id,
                "pourquoi": "mesure d'AVANT illisible (%s) : sans reference, l'apres ne se "
                            "juge pas -- acte NON fait" % err}
    empreinte_avant = _empreinte_sure(empreinte)
    if empreinte_avant is None:
        return {"verdict": "INDECIDABLE", "applique": False, "exp_id": exp_id,
                "pourquoi": "empreinte d'AVANT illisible : un retour ne pourrait pas etre "
                            "prouve -- acte NON fait"}
    # L'experience d'APPLICATION est inscrite AVANT l'acte : si le process meurt entre
    # l'acte et la mesure, le registre dit qu'un acte etait en cours, et sur quoi.
    app_id = _inscrire({"kind": "application", "status": "EN_COURS", "niveau": niveau,
                        "cible": cible, "ref_exp": exp_id, "reference": reference,
                        "empreinte_avant": empreinte_avant})
    exp_id = exp_id or app_id
    try:
        fait = appliquer() or {}
    except Exception as exc:  # noqa: BLE001 - un acte qui leve peut avoir ecrit a moitie
        fait = {"ok": False, "detail": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
    if not fait.get("ok"):
        if _empreinte_sure(empreinte) == empreinte_avant:
            rec_id = _inscrire({"kind": "post_application", "niveau": niveau, "cible": cible,
                                "ref_exp": exp_id, "application_id": app_id,
                                "verdict": "NON_APPLIQUE", "status": "NON_APPLIQUE",
                                "detail": fait})
            return {"verdict": "NON_APPLIQUE", "applique": False, "exp_id": exp_id,
                    "post_id": rec_id, "detail": fait}
        # L'acte a echoue MAIS l'etat a bouge : on le traite comme une regression.
    r = mesurer_apres(niveau, cible, exp_id, reference, empreinte_avant, mesurer, reverter,
                      empreinte, bruit, application=dict(fait, application_id=app_id),
                      apres_conserve=apres_conserve)
    r["application_id"] = app_id
    return r


# ── L3 : merge wip -> alpha ─────────────────────────────────────────────────────────
def _git(racine, *args) -> tuple[int, str, str]:
    r = subprocess.run(["git", "-c", "safe.directory=*", *args], cwd=str(racine),
                       capture_output=True, text=True, errors="replace", timeout=120)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _arbre(racine, ref: str = "HEAD") -> str | None:
    """sha de l'ARBRE (pas du commit) : un revert cree un commit neuf, mais redonne
    l'arbre d'avant a l'octet pres -- c'est l'arbre qui prouve le retour."""
    rc, out, _err = _git(racine, "rev-parse", "%s^{tree}" % ref)
    return out if rc == 0 and out else None


def _dimensions_tests(m: dict) -> dict:
    """Mesure de tests -> dimensions : une par test (1 vert, 0 rouge) + le total.

    Par test, et pas seulement le compte : reparer un test et en casser un autre laisse
    le compte egal ; une dimension par test rend chaque recul visible (bruit 0)."""
    passes = set(m.get("tests_passes") or [])
    dims = {"nr:%s" % t: (1.0 if t in passes else 0.0) for t in (m.get("tests") or [])}
    dims["tests_ok"] = float(m.get("tests_ok", 0))
    return dims


def _mesure_tests(tests: list[str], racine) -> dict:
    from nokido_agent.app.forge_mutation_judge import mesurer
    m = mesurer(tests, cwd=str(racine))
    return _dimensions_tests(dict(m, tests=list(tests)))


def mesurer_apres_merge(merge_sha: str, exp_id: str | None, reference: dict,
                        racine=None, mesurer=None, bruit: dict | None = None,
                        cible: str = "", apres_conserve=None) -> dict:
    """L3 : mesure apres un merge DEJA fait ; regression -> `git revert -m 1`.

    L'etat d'avant est l'arbre du PREMIER parent du merge (le canonique tel qu'il etait).
    Le revert est un commit de plus, jamais une reecriture : « rien n'est supprime ».
    """
    racine = Path(racine) if racine is not None else ROOT
    bruit = dict(bruit or {})
    rc, parents, _ = _git(racine, "rev-list", "--parents", "-n", "1", merge_sha)
    if rc != 0 or len(parents.split()) < 3:
        return {"verdict": "INDECIDABLE", "applique": True, "exp_id": exp_id,
                "pourquoi": "%s n'est pas un commit de merge lisible : le revert -m 1 n'a "
                            "pas de premier parent sur" % merge_sha}
    premier_parent = parents.split()[1]

    def _reverter():
        rc2, out, err = _git(racine, "revert", "-m", "1", "--no-edit", merge_sha)
        if rc2 != 0:
            # Un revert en CONFLIT laisse le canonique a moitie defait : on l'annule, et
            # l'echec se lit dans la preuve (revert_ok False -> frein).
            rc3, _o, err3 = _git(racine, "revert", "--abort")
            return {"ok": False, "detail": (err or out)[:200], "revert_de": merge_sha,
                    "abort": "ok" if rc3 == 0 else (err3[:120] or "abort impossible")}
        return {"ok": True, "detail": (err or out)[:200], "revert_de": merge_sha}

    return mesurer_apres(
        "L3", cible or "merge:%s" % merge_sha[:12], exp_id, reference,
        _arbre(racine, premier_parent), mesurer or (lambda: {}), _reverter,
        lambda: _arbre(racine, "HEAD"), bruit,
        application={"merge": merge_sha, "premier_parent": premier_parent},
        apres_conserve=apres_conserve)


def _capturer_generation(agent: str, note: str) -> dict:
    """Generation de l'etat GARDE. Rend un RESUME : le registre ne porte pas le lock entier."""
    from nokido_agent.app.forge_generation import capturer_si_absent
    g = capturer_si_absent(tests={"invariants_nr": "PASS"}, agent=agent, note=note) or {}
    return {"generation": g.get("generation") or g.get("skip"), "statut": g.get("statut"),
            "deja_capture": bool(g.get("skip")),
            "inscription_differee": bool(g.get("inscription_differee"))}


def cycle(agent: str, tests=None, apply: bool = False, exp_id: str | None = None,
          mesurer=None, bruit: dict | None = None, racine=None) -> dict:
    """Flux complet pour <agent>. Suppose que l'agent a DEJA commite son travail dans
    sa branche wip/<agent> (via son worktree isole). Enchaine isolation -> arbitrage
    -> mesure apres -> generation, sans creer/juger/merger RIEN de plus que les briques
    dediees.

    `mesurer` (optionnel) : mesure de capacite {dimension: score} ; par defaut, les
    tests de la merge gate, une dimension par test. `bruit` : bande par dimension.
    """
    from nokido_agent.tools.forge_merge_gate import merger

    from nokido_agent.tools.forge_merge_gate import suite_nr

    r = {"agent": agent, "etapes": {}}
    racine = Path(racine) if racine is not None else ROOT
    reference = None
    if apply:
        # La merge gate consulte deja la porte (alpha) ; la relire ici coute un appel et
        # garde le controleur sur meme si une version de la gate l'oubliait.
        porte = _porte()
        if not porte.get("autorisee"):
            r.update(verdict=porte.get("etat") or "INCONNU", porte=porte,
                     decision="porte d'evolution fermee : aucun merge tente")
            return r
        if mesurer is not None:
            # Une mesure de CAPACITE se prend AVANT le merge : apres, le canonique a deja
            # change et il n'y a plus de reference honnete a laquelle comparer.
            reference, err = _mesure_sure(mesurer)
            if err:
                r.update(verdict="INDECIDABLE",
                         decision="mesure d'AVANT illisible (%s) : aucun merge tente" % err)
                return r
    # ARBITRAGE : merge gate -- mesure alpha vs worktree sur les invariants, merge
    # wip->alpha SEULEMENT si AMELIORE. L'ISOLATION (create du worktree) est en AMONT
    # (declencheur au lancement de l'agent, forge_cli_route) ; merger() gere proprement
    # son absence (PAS_DE_WORKTREE) -- le controleur ne cree donc rien.
    ev = merger(agent, tests, apply)
    r["etapes"]["merge_gate"] = ev
    r["verdict"] = ev.get("verdict")
    r["decision"] = ev.get("decision")
    if not ev.get("applique"):
        return r

    rc, merge_sha, _ = _git(racine, "rev-parse", "HEAD")
    if exp_id is None:
        # Un merge sans experience d'origine en recoit une : la mesure d'apres doit se
        # rattacher a QUELQUE CHOSE, sinon l'effet n'a pas de cause dans le registre.
        exp_id = _inscrire({"kind": "merge_applique", "status": "APPLIQUE", "agent": agent,
                            "branche": ev.get("branch"), "merge": merge_sha,
                            "verdict_gate": ev.get("verdict")})
    if mesurer is None:
        # Defaut : la suite de la gate, rejouee sur le canonique fusionne. La reference est
        # la baseline que la gate a mesuree sur alpha AVANT le merge (meme suite).
        tests_suite = suite_nr(tests)
        base = ev.get("baseline") or {}
        # Sans baseline MESUREE, des dimensions a zero rendraient tout « dans la bande » :
        # la reference reste VIDE et mesurer_apres le dit (INDECIDABLE + frein).
        reference = (_dimensions_tests(dict(base, tests=tests_suite))
                     if isinstance(base.get("tests_passes"), list) else {})
        mesurer = (lambda: _mesure_tests(tests_suite, racine))
    post = mesurer_apres_merge(
        merge_sha, exp_id, reference, racine=racine, mesurer=mesurer, bruit=bruit,
        cible="merge:%s" % (ev.get("branch") or agent),
        apres_conserve=lambda: _capturer_generation(
            agent, "merge %s (AMELIORE via merge gate, CONSERVE apres mesure, exp %s)"
            % (agent, exp_id)))
    r["etapes"]["mesure_apres"] = post
    r["verdict_apres"] = post.get("verdict")
    if post.get("apres_conserve") is not None:
        r["etapes"]["generation"] = post["apres_conserve"]
    return r


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Kernel de mutation : worktree -> juge -> merge -> mesure apres -> generation")
    ap.add_argument("--agent", required=True)
    ap.add_argument("--apply", action="store_true", help="merge reel si AMELIORE (defaut: dry-run)")
    ap.add_argument("--tests", nargs="*", default=None, help="suite d'invariants (defaut: tests/nr)")
    ap.add_argument("--exp", default=None, help="exp_id d'origine au registre d'evolution")
    a = ap.parse_args()
    print(json.dumps(cycle(a.agent, a.tests, a.apply, exp_id=a.exp), ensure_ascii=False,
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
